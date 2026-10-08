#!/usr/bin/env python3
"""jtop: hardware components and live usage, htop style. Linux, stdlib only.

Keys: Tab switch, ↑ ↓ scroll, q quit.
Self-test: python3 jtop.py --check
"""
import curses
import os
import sys
import time
from pathlib import Path

TABS = ("Components", "Usage")
LABEL = 24  # label width, keeps every bar aligned


def read(path, default=""):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return default


def human(n, unit="B"):
    for prefix in ("", "K", "M", "G", "T"):
        if abs(n) < 1024:
            return f"{n:.1f} {prefix}{unit}"
        n /= 1024
    return f"{n:.1f} P{unit}"


DISKS = [d for d in sorted(os.listdir("/sys/block")) if not d.startswith(("loop", "ram", "zram", "dm-"))]


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
        if name != "lo" and read(f"/sys/class/net/{name}/operstate") == "up":
            io[name] = (int(f[0]), int(f[8]))
    return io


def sample():
    return time.monotonic(), cpu_times(), disk_io(), net_io()


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
    for hw in sorted(Path("/sys/class/hwmon").glob("hwmon*")):
        name = read(hw / "name", hw.name)
        for t in sorted(hw.glob("temp*_input")):
            label = read(str(t).replace("_input", "_label"), t.name.split("_")[0])
            out.append((f"{name} {label}", int(read(t, "0")) / 1000))
    return out


def filesystems():
    seen, out = set(), []
    for line in read("/proc/mounts").splitlines():
        dev, mnt, *_ = line.split()
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
        gpus.append((card.name, f"driver {ue.get('DRIVER', '?')}  [PCI {ue.get('PCI_ID', '?')}]"))
    if gpus:
        out.append(("Graphics", gpus))

    disks = []
    for d in DISKS:
        size = human(int(read(f"/sys/block/{d}/size", "0")) * 512)
        kind = "HDD" if read(f"/sys/block/{d}/queue/rotational") == "1" else "SSD"
        disks.append((d, f"{read(f'/sys/block/{d}/device/model', '?')}  {size}  {kind}"))
    out.append(("Disks", disks))

    nets = []
    for n in sorted(os.listdir("/sys/class/net")):
        if n == "lo":
            continue
        p = f"/sys/class/net/{n}"
        kind = "Wi-Fi" if os.path.exists(p + "/wireless") else "Ethernet" if os.path.exists(p + "/device") else "virtual"
        speed = read(p + "/speed")
        speed = f"  {speed} Mb/s" if speed.isdigit() and int(speed) > 0 else ""
        nets.append((n, f"{kind}  {read(p + '/address')}  {read(p + '/operstate')}{speed}"))
    out.append(("Network", nets))
    return out


# ---------- layout: a line is a list of (text, style) ----------

def header(title, w):
    return [("─ ", "dim"), (title, "title"), (" " + "─" * max(w - len(title) - 4, 0), "dim")]


def bar(label, pct, width, value=None, extra=""):
    pct = max(0.0, min(pct, 100.0))
    value = value or f"{pct:5.1f}%"
    extra = f" {extra:<24}" if extra else ""
    n = max(width - len(label) - len(value) - len(extra) - 3, 5)
    fill = round(n * pct / 100)
    color = "good" if pct < 60 else "warn" if pct < 85 else "crit"
    return [(label, "bold"), ("▕", "dim"), ("█" * fill, color), ("░" * (n - fill), "dim"),
            ("▏", "dim"), (value + " ", "bold"), (extra, "dim")]


def row(label, pct, w, value=None, extra=" "):
    return bar(f"  {label[:LABEL - 3]:<{LABEL - 2}}", pct, w - 1, value, extra)


def component_lines(comps, w):
    lines = []
    for section, items in comps:
        lines += [[], header(section, w)]
        lines += [[(f"  {k:<18}", "dim"), (str(v), "")] for k, v in items]
    return lines


def usage_lines(w, prev, cur):
    t0, cpu0, dsk0, net0 = prev
    t1, cpu1, dsk1, net1 = cur
    dt = max(t1 - t0, 1e-3)
    pct = {k: 100 * act / max(tot, 1) for k, (act, tot) in deltas(cpu0, cpu1).items()}

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
    return lines


# ---------- curses ----------

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
        x = 0
        for text, style in line:
            if x >= w:
                break
            scr.addnstr(y, x, text, w - x, styles[style])
            x += len(text)

    footer = " Tab switch · ↑↓ scroll · q quit"
    scr.addnstr(h - 1, 0, footer.ljust(w), w - 1, styles["tab_off"])
    scr.refresh()


def main(scr):
    curses.curs_set(0)
    curses.use_default_colors()
    colors = (curses.COLOR_GREEN, curses.COLOR_YELLOW, curses.COLOR_RED, curses.COLOR_CYAN)
    for i, c in enumerate(colors, 1):
        curses.init_pair(i, c, -1)
    curses.init_pair(5, curses.COLOR_BLACK, curses.COLOR_CYAN)
    cp = curses.color_pair
    styles = {"": 0, "bold": curses.A_BOLD, "dim": curses.A_DIM, "good": cp(1), "warn": cp(2), "crit": cp(3),
              "title": cp(4) | curses.A_BOLD, "tab_on": cp(5) | curses.A_BOLD, "tab_off": curses.A_REVERSE}
    scr.timeout(250)

    comps = components()
    tab = scroll = 0
    prev = sample()
    time.sleep(0.2)
    cur = sample()
    while True:
        h, w = scr.getmaxyx()
        lines = component_lines(comps, w) if tab == 0 else usage_lines(w, prev, cur)
        scroll = max(0, min(scroll, len(lines) - (h - 2)))
        try:
            draw(scr, tab, scroll, lines, styles)
        except curses.error:
            pass  # terminal too small: retry next tick

        k = scr.getch()
        if k == ord("q"):
            break
        if k == 9:
            tab, scroll = 1 - tab, 0
        elif k in (ord("1"), ord("2")):
            tab, scroll = k - ord("1"), 0
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
    a = sample()
    time.sleep(0.2)
    b = sample()
    act, tot = deltas(a[1], b[1])["cpu"]
    assert 0 <= act <= tot
    assert meminfo()["MemTotal"] > 0
    for w in (90, 160):
        lines = component_lines(components(), w) + usage_lines(w, a, b)
        assert all(len("".join(t for t, _ in l)) <= w for l in lines if l[:1] and l[0][1] != "dim"), "overflow"
    print("ok")


if __name__ == "__main__":
    check() if "--check" in sys.argv else curses.wrapper(main)
