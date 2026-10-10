#!/usr/bin/env python3
"""jtop: hardware components and live usage, htop style. Linux, stdlib only.

Keys: Tab switch, ↑ ↓ scroll, q quit.
Self-test: python3 jtop.py --check
"""
import curses
import functools
import os
import re
import sys
import time
import unicodedata
from pathlib import Path

TABS = ("Components", "Usage", "Processes")
LABEL = 24  # label width, keeps every bar aligned

if sys.platform != "win32":  # jtop_win.py imports the layout helpers below
    import pwd
    PAGE = os.sysconf("SC_PAGE_SIZE")
    HZ = os.sysconf("SC_CLK_TCK")
    DISKS = [d for d in sorted(os.listdir("/sys/block")) if not d.startswith(("loop", "ram", "zram", "dm-"))]


def read(path, default=""):
    try:
        return Path(path).read_text(errors="replace").strip()
    except OSError:
        return default


def physical(iface):
    return os.path.exists(f"/sys/class/net/{iface}/device")  # lo, docker, bridges, veth have none


def human(n, unit="B"):
    for prefix in ("", "K", "M", "G", "T"):
        if abs(n) < 1024:
            return f"{n:.1f} {prefix}{unit}"
        n /= 1024
    return f"{n:.1f} P{unit}"


# ---------- measurements ----------

def cpu_times():
    out = {}
    for line in read("/proc/stat").splitlines():
        if line.startswith("cpu"):
            name, *v = line.split()
            v = [int(x) for x in v[:8]]
            out[name] = (sum(v) - v[3] - v[4], sum(v))  # (busy, total); idle + iowait = not busy
    return out


def disk_io():
    io = {}
    for line in read("/proc/diskstats").splitlines():
        f = line.split()
        if f[2] in DISKS:
            io[f[2]] = (int(f[5]) * 512, int(f[9]) * 512)  # sectors read / written -> bytes
    return io


def net_io():
    io = {}
    for line in read("/proc/net/dev").splitlines()[2:]:
        name, data = line.split(":", 1)
        f = data.split()
        name = name.strip()
        if physical(name) and read(f"/sys/class/net/{name}/operstate") == "up":
            io[name] = (int(f[0]), int(f[8]))
    return io


def proc_stat(pid):
    """(comm, fields after the comm) from /proc/<pid>/stat, or None if the process is gone."""
    stat = read(f"/proc/{pid}/stat")
    if not stat:
        return None
    return stat[stat.find("(") + 1:stat.rfind(")")], stat[stat.rfind(")") + 2:].split()


def proc_times():
    out = {}
    for pid in os.listdir("/proc"):
        if pid.isdigit() and (st := proc_stat(pid)):
            # keyed by (pid, start time): a reused pid is a new process, not a negative CPU delta
            out[int(pid), st[1][19]] = (int(st[1][11]) + int(st[1][12]),)  # utime + stime, in ticks
    return out


def sample():
    return time.monotonic(), cpu_times(), disk_io(), net_io(), proc_times()


def cpu_percent(prev, cur):
    return {k: 100 * busy / max(total, 1) for k, (busy, total) in deltas(prev[1], cur[1]).items()}


def deltas(a, b):
    """For each key present in both a and b: field-by-field difference of the tuples."""
    return {k: tuple(y - x for x, y in zip(a[k], b[k])) for k in b if k in a}


def meminfo():
    m = {}
    for line in read("/proc/meminfo").splitlines():
        k, v = line.split(":", 1)
        m[k] = int(v.split()[0]) * 1024
    return m


def temps():
    out = []
    for hw in sorted(Path("/sys/class/hwmon").glob("hwmon*"), key=lambda h: int(h.name[5:])):
        name = read(hw / "name", hw.name)
        for t in sorted(hw.glob("temp*_input"), key=lambda t: int(t.name[4:-6])):  # temp2 before temp10
            label = read(str(t).replace("_input", "_label"), t.name.split("_")[0])
            out.append((f"{name} {label}", int(read(t, "0")) / 1000))
    return out


def filesystems():
    seen, out = set(), []
    for line in read("/proc/mounts").splitlines():
        dev, mnt, *_ = line.split()
        mnt = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), mnt)  # /proc/mounts writes a space as \040
        if not dev.startswith("/dev/") or dev in seen:
            continue
        seen.add(dev)
        try:
            st = os.statvfs(mnt)
        except OSError:
            continue
        total = st.f_blocks * st.f_frsize
        if total:
            out.append((mnt, total - st.f_bfree * st.f_frsize, total))
    return out


def batteries():
    return sorted(Path("/sys/class/power_supply").glob("BAT*"))


@functools.lru_cache(maxsize=None)
def username(uid):
    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError:
        return str(uid)


def pci_name(pci_id):
    """'8086:46A8' -> 'Intel Corporation Alder Lake-UP3 GT2 [Iris Xe Graphics]', from the pci.ids database."""
    vendor, device = pci_id.lower().split(":")
    for path in ("/usr/share/misc/pci.ids", "/usr/share/hwdata/pci.ids"):
        try:
            f = open(path, encoding="utf-8", errors="replace")
        except OSError:
            continue
        with f:
            name = None
            for line in f:
                if line.startswith(vendor + "  "):
                    name = line[6:].strip()
                elif name and line.startswith("\t" + device + "  "):
                    return f"{name} {line[7:].strip()}"
                elif name and line[:1] not in ("\t", "#", "\n"):
                    return name  # next vendor reached: device unknown
    return None


def uptime():
    s = float(read("/proc/uptime", "0").split()[0])
    return f"{int(s // 86400)}d {int(s % 86400 // 3600)}h {int(s % 3600 // 60):02}m"


def components():
    cpuinfo = read("/proc/cpuinfo").splitlines()
    model = next((l.split(":", 1)[1].strip() for l in cpuinfo if l.startswith("model name")), "?")
    sysd = Path("/sys/devices/system/cpu")
    cores = len({read(p) for p in sysd.glob("cpu[0-9]*/topology/core_cpus_list")})
    fmax = read(sysd / "cpu0/cpufreq/cpuinfo_max_freq")
    mem = meminfo()
    dmi = lambda f: read(f"/sys/class/dmi/id/{f}", "?")

    out = [
        ("Processor", [
            ("Model", model),
            ("Cores / threads", f"{cores} / {os.cpu_count()}"),
            ("Max frequency", f"{int(fmax) / 1e6:.2f} GHz" if fmax else "?"),
            ("Architecture", os.uname().machine),
        ]),
        ("Memory", [("RAM", human(mem["MemTotal"])), ("Swap", human(mem.get("SwapTotal", 0)))]),
        ("System", [
            ("Machine", f"{dmi('sys_vendor')} {dmi('product_name')}"),
            ("Motherboard", f"{dmi('board_vendor')} {dmi('board_name')}"),
            ("BIOS", f"{dmi('bios_vendor')} {dmi('bios_version')} ({dmi('bios_date')})"),
            ("Kernel", os.uname().release),
        ]),
    ]

    gpus = []
    for card in sorted(Path("/sys/class/drm").glob("card[0-9]")):
        ue = dict(l.split("=", 1) for l in read(card / "device/uevent").splitlines() if "=" in l)
        pci = ue.get("PCI_ID", "?")
        name = pci_name(pci) if ":" in pci else None
        gpus.append((card.name, f"{name or 'PCI ' + pci}  (driver {ue.get('DRIVER', '?')})"))
    if gpus:
        out.append(("Graphics", gpus))

    bats = []
    for b in batteries():
        full = read(b / "energy_full") or read(b / "charge_full")
        design = read(b / "energy_full_design") or read(b / "charge_full_design")
        health = f"  health {100 * int(full) / int(design):.0f}%" if full and int(design or 0) else ""
        bats.append((b.name, f"{read(b / 'manufacturer', '?')} {read(b / 'model_name', '?')}  "
                             f"{read(b / 'technology', '?')}{health}"))
    if bats:
        out.append(("Battery", bats))

    disks = []
    for d in DISKS:
        size = human(int(read(f"/sys/block/{d}/size", "0")) * 512)
        kind = "HDD" if read(f"/sys/block/{d}/queue/rotational") == "1" else "SSD"
        disks.append((d, f"{read(f'/sys/block/{d}/device/model', '?')}  {size}  {kind}"))
    out.append(("Disks", disks))

    nets = []
    for n in sorted(filter(physical, os.listdir("/sys/class/net"))):
        p = f"/sys/class/net/{n}"
        kind = "Wi-Fi" if os.path.exists(p + "/wireless") else "Ethernet"
        speed = read(p + "/speed")
        speed = f"  {speed} Mb/s" if speed.isdigit() and int(speed) > 0 else ""
        nets.append((n, f"{kind}  {read(p + '/address')}  {read(p + '/operstate')}{speed}"))
    out.append(("Network", nets))
    return out


# ---------- layout: a line is a list of (text, style) ----------

def header(title, w):
    return [("─ ", "dim"), (title, "title"), (" " + "─" * max(w - len(title) - 4, 0), "dim")]


def level(pct):
    return "good" if pct < 60 else "warn" if pct < 85 else "crit"


def bar(label, pct, width, value=None, extra="", color=None):
    pct = max(0.0, min(pct, 100.0))
    value = value or f"{pct:5.1f}%"
    extra = f" {extra:<24}" if extra else ""
    n = max(width - len(label) - len(value) - len(extra) - 3, 5)
    fill = round(n * pct / 100)
    return [(label, "bold"), ("▕", "dim"), ("█" * fill, color or level(pct)), ("░" * (n - fill), "dim"),
            ("▏", "dim"), (value + " ", "bold"), (extra, "dim")]


def row(label, pct, w, value=None, extra=" ", color=None):
    return bar(f"  {label[:LABEL - 3]:<{LABEL - 2}}", pct, w - 1, value, extra, color)


def component_lines(comps, w):
    lines = []
    for section, items in comps:
        lines += [[], header(section, w)]
        lines += [[(f"  {k:<18}", "dim"), (str(v), "")] for k, v in items]
    return lines


def usage_lines(w, prev, cur):
    t0, _, dsk0, net0, _ = prev
    t1, _, dsk1, net1, _ = cur
    dt = max(t1 - t0, 1e-3)
    pct = cpu_percent(prev, cur)

    lines = [[], header("CPU", w)]
    cores = sorted((k for k in pct if k != "cpu"), key=lambda k: int(k[3:]))
    cols = max(1, min(4, w // 45))
    cw = w // cols
    for i in range(0, len(cores), cols):
        line = []
        for k in cores[i:i + cols]:
            line += bar(f"  {k[3:]:>3} ", pct[k], cw - 1) + [(" ", "")]
        lines.append(line)

    m = meminfo()
    used = m["MemTotal"] - m["MemAvailable"]
    lines += [[], header("Memory", w),
              row("RAM", 100 * used / m["MemTotal"], w, extra=f"{human(used)} / {human(m['MemTotal'])}")]
    if m.get("SwapTotal"):
        su = m["SwapTotal"] - m["SwapFree"]
        lines.append(row("Swap", 100 * su / m["SwapTotal"], w, extra=f"{human(su)} / {human(m['SwapTotal'])}"))

    lines += [[], header("Disks", w)]
    for d, (r, wr) in deltas(dsk0, dsk1).items():
        lines.append([(f"  {d[:LABEL - 3]:<{LABEL - 2}}", "bold"), (f"▼ read  {human(r / dt)}/s".ljust(24), "good"),
                      (f"▲ write  {human(wr / dt)}/s", "warn")])
    for mnt, u, total in filesystems():
        lines.append(row(mnt, 100 * u / total, w, extra=f"{human(u)} / {human(total)}"))

    lines += [[], header("Network", w)]
    for n, (rx, tx) in deltas(net0, net1).items():
        lines.append([(f"  {n[:LABEL - 3]:<{LABEL - 2}}", "bold"), (f"▼ {human(rx / dt)}/s".ljust(24), "good"),
                      (f"▲ {human(tx / dt)}/s", "warn")])

    ts = temps()
    if ts:
        lines += [[], header("Temperatures", w)]
        lines += [row(name, c, w, value=f"{c:4.0f}°C") for name, c in ts]  # full bar = 100 °C

    bats = batteries()
    if bats:
        lines += [[], header("Battery", w)]
        for b in bats:
            pct = int(read(b / "capacity", "0"))
            color = "crit" if pct < 15 else "warn" if pct < 30 else "good"  # low charge is the bad end
            lines.append(row(b.name, pct, w, extra=read(b / "status", "?"), color=color))
    return lines


STATES = {"R": ("run", "good"), "S": ("sleep", "dim"), "D": ("disk", "warn"), "I": ("idle", "dim"),
          "T": ("stop", "warn"), "t": ("trace", "warn"), "Z": ("zombie", "crit"), "X": ("dead", "crit")}


def process_lines(w, prev, cur, show_all=False):
    dt = max(cur[0] - prev[0], 1e-3)
    total = meminfo()["MemTotal"]
    procs = []
    for (pid, _), (ticks,) in deltas(prev[4], cur[4]).items():
        st = proc_stat(pid)
        try:
            uid = os.stat(f"/proc/{pid}").st_uid
        except OSError:
            st = None
        if not st:
            continue  # process exited between two samples
        comm, f = st
        cmd = " ".join(read(f"/proc/{pid}/cmdline").replace("\0", " ").split())  # newlines in args would break the row
        if not cmd:
            cmd = comm = f"[{comm}]"  # kernel thread
        procs.append((100 * ticks / (dt * HZ), int(f[21]) * PAGE, pid, username(uid), f[0], cmd if show_all else comm))
    procs.sort(reverse=True)  # busiest first, then biggest memory

    columns = f"{'PID':>7}  {'USER':<10} {'CPU%':>6} {'MEM%':>5} {'MEM':>9}  {'STATE':<6}  COMMAND"
    title = f"Processes · all {len(procs)} · a: top 10" if show_all else f"Processes · top 10 of {len(procs)} · a: show all"
    lines = [[], header(title, w), [(columns.ljust(w), "tab_off")]]
    for cpu, rss, pid, user, state, cmd in procs if show_all else procs[:10]:
        word, color = STATES.get(state, (state, "dim"))
        lines.append([(f"{pid:>7}  ", "dim"), (f"{user[:10]:<10} ", ""), (f"{cpu:6.1f} ", level(cpu) if cpu else "dim"),
                      (f"{100 * rss / total:5.1f} ", ""), (f"{human(rss):>9}  ", ""), (f"{word:<6}  ", color),
                      (cmd, "bold")])
    return lines


# ---------- curses ----------

def init_styles():
    try:
        curses.curs_set(0)
    except curses.error:
        pass  # terminal can't hide the cursor (vt100, serial console)
    if curses.has_colors():
        curses.use_default_colors()
        colors = (curses.COLOR_GREEN, curses.COLOR_YELLOW, curses.COLOR_RED, curses.COLOR_CYAN)
        for i, c in enumerate(colors, 1):
            curses.init_pair(i, c, -1)
        curses.init_pair(5, curses.COLOR_BLACK, curses.COLOR_CYAN)
    cp = curses.color_pair
    return {"": 0, "bold": curses.A_BOLD, "dim": curses.A_DIM, "good": cp(1), "warn": cp(2), "crit": cp(3),
            "title": cp(4) | curses.A_BOLD, "tab_on": cp(5) | curses.A_BOLD, "tab_off": curses.A_REVERSE}


def put_line(scr, y, x, w, line, styles):
    """Write one (text, style) line at (y, x), clipped to w columns. CJK and emoji take two columns, and
    curses shows a control character as ^X: counting them as one would wrap the overflow onto the next row."""
    for text, style in line:
        if w <= 0:
            break
        used = 0
        for i, c in enumerate(text):
            cw = 2 if not c.isprintable() or unicodedata.east_asian_width(c) in "WF" else 1
            if used + cw > w:
                text = text[:i]
                break
            used += cw
        scr.addstr(y, x, text, styles[style])
        x += used
        w -= used


def draw(scr, tab, scroll, lines, styles):
    scr.erase()
    h, w = scr.getmaxyx()
    x = 1
    for i, name in enumerate(TABS):
        label = f" {i + 1} {name} "
        scr.addnstr(0, x, label, max(w - x, 0), styles["tab_on" if i == tab else "tab_off"])
        x += len(label) + 1
    info = f"host {os.uname().nodename} · uptime {uptime()} · {time.strftime('%H:%M:%S')} "
    if w - len(info) > x:
        scr.addstr(0, w - len(info), info, styles["dim"])

    for y, line in enumerate(lines[scroll:scroll + h - 2], 1):
        put_line(scr, y, 0, w, line, styles)

    footer = " Tab switch · ↑↓ scroll · q quit"
    scr.addnstr(h - 1, 0, footer.ljust(w), w - 1, styles["tab_off"])
    scr.refresh()


def main(scr):
    styles = init_styles()
    scr.timeout(250)

    comps = components()
    tab = scroll = 0
    show_all = False
    shown = None
    prev = sample()
    time.sleep(0.2)
    cur = sample()
    while True:
        h, w = scr.getmaxyx()
        key = (tab, w, show_all, cur[0])
        if key != shown:  # data changes once a second: don't rebuild on every key or tick
            shown = key
            if tab == 0:
                lines = component_lines(comps, w)
            elif tab == 1:
                lines = usage_lines(w, prev, cur)
            else:
                lines = process_lines(w, prev, cur, show_all)
        scroll = max(0, min(scroll, len(lines) - (h - 2)))
        try:
            draw(scr, tab, scroll, lines, styles)
        except curses.error:
            pass  # terminal too small: retry next tick

        k = scr.getch()
        if k == ord("q"):
            break
        if k == 9:
            tab, scroll = (tab + 1) % len(TABS), 0
        elif ord("1") <= k < ord("1") + len(TABS):
            tab, scroll = k - ord("1"), 0
        elif k == ord("a") and tab == 2:
            show_all, scroll = not show_all, 0
        elif k == curses.KEY_UP:
            scroll -= 1
        elif k == curses.KEY_DOWN:
            scroll += 1
        elif k == curses.KEY_PPAGE:
            scroll -= h - 2
        elif k == curses.KEY_NPAGE:
            scroll += h - 2
        if time.monotonic() - cur[0] >= 1:
            prev, cur = cur, sample()


def check():
    assert deltas({"a": (1, 10)}, {"a": (4, 20), "b": (0, 0)}) == {"a": (3, 10)}
    assert human(1536) == "1.5 KB"
    drawn = []
    scr = type("Scr", (), {"addstr": lambda self, y, x, text, attr: drawn.append((x, text))})()
    put_line(scr, 0, 0, 10, [("abc", ""), ("日本語日本語", ""), ("x", "")], {"": 0})
    assert drawn == [(0, "abc"), (3, "日本語"), (9, "x")], "wide characters must be clipped by width, not length"
    a = sample()
    time.sleep(0.2)
    b = sample()
    act, tot = deltas(a[1], b[1])["cpu"]
    assert 0 <= act <= tot
    assert meminfo()["MemTotal"] > 0
    assert pci_name("8086:46a8") in (None, "Intel Corporation Alder Lake-UP3 GT2 [Iris Xe Graphics]")
    procs = process_lines(120, a, b, show_all=True)
    assert any(str(os.getpid()) in "".join(t for t, _ in l) for l in procs), "own process missing"
    assert len(process_lines(120, a, b)) == 3 + min(10, len(procs) - 3), "top 10"
    for w in (90, 160):
        lines = component_lines(components(), w) + usage_lines(w, a, b) + process_lines(w, a, b)
        assert all(len("".join(t for t, _ in l)) <= w for l in lines if l[:1] and l[0][1] != "dim"), "overflow"
    print("ok")


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.exit("jtop.py is the Linux version: on Windows, install jtop with pipx and run jtop (see README)")
    if "--check" in sys.argv:
        check()
    elif "--fun" in sys.argv or "-fun" in sys.argv:
        import jtop_fun  # easter egg, not a real feature: see jtop_fun.py
        jtop_fun.run()
    else:
        try:
            curses.wrapper(main)
        except KeyboardInterrupt:
            pass  # Ctrl-C quits like q, without a traceback
