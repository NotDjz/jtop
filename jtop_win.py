#!/usr/bin/env python3
"""jtop for Windows: same tabs and keys as jtop.py, data from psutil, the registry and one Win32 call.

Needs: pip install psutil windows-curses
Keys: Tab switch, ↑ ↓ scroll, q quit.
Self-test: python jtop_win.py --check
"""
import ctypes
import curses
import functools
import itertools
import os
import platform
import struct
import sys
import time
import winreg

import psutil

from jtop import LABEL, TABS, component_lines, cpu_percent, deltas, header, human, level, put_line
from jtop import init_styles as jtop_styles

if sys.maxsize < 2 ** 32:
    sys.exit("jtop_win needs a 64-bit Python")  # the struct offsets below are the x64 layouts

GPU_CLASS = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
NET_CLASS = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e972-e325-11ce-bfc1-08002be10318}"
CONNECTIONS = r"SYSTEM\CurrentControlSet\Control\Network\{4D36E972-E325-11CE-BFC1-08002BE10318}"

ntdll = ctypes.WinDLL("ntdll")


def reg(path, name, default="?"):
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return default


def subkeys(path):
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as k:
            return [f"{path}\\{winreg.EnumKey(k, i)}" for i in range(winreg.QueryInfoKey(k)[0])]
    except OSError:
        return []


def physical_nics():
    """{connection name: 'Wi-Fi' or 'Ethernet'} for PCI and USB adapters: no VPN, Hyper-V, Bluetooth or WAN miniport."""
    nics = {}
    for k in subkeys(NET_CLASS):
        if reg(k, "DeviceInstanceID", "").startswith(("PCI\\", "USB\\", "SDIO\\", "VMBUS\\")):  # VMBUS: in a Hyper-V VM
            name = reg(f"{CONNECTIONS}\\{reg(k, 'NetCfgInstanceId')}\\Connection", "Name")
            nics[name] = "Wi-Fi" if reg(k, "*PhysicalMediaType", 0) in (1, 9) else "Ethernet"  # WirelessLan, Native802_11
    return nics


NICS = physical_nics()  # ponytail: read once like jtop.DISKS, restart to see an adapter plugged in later


# ---------- measurements ----------

def cpu_times():
    """Same shape as jtop.cpu_times, in 100 ns units: jtop.cpu_percent floors the total at 1, made for ticks, not
    seconds. interrupt and dpc are already inside system: not summed twice."""
    times = {"cpu": psutil.cpu_times()}
    times.update((f"cpu{i}", t) for i, t in enumerate(psutil.cpu_times(percpu=True)))
    return {k: (round((t.user + t.system) * 1e7), round((t.user + t.system + t.idle) * 1e7)) for k, t in times.items()}


def disk_io():
    return {d: (c.read_bytes, c.write_bytes) for d, c in psutil.disk_io_counters(perdisk=True).items()}


def net_io():
    up = {n for n, s in psutil.net_if_stats().items() if s.isup}
    return {n: (c.bytes_recv, c.bytes_sent) for n, c in psutil.net_io_counters(pernic=True).items()
            if n in NICS and n in up}  # ponytail: ~30 ms a refresh, one GetIfTable2 call if that ever matters


def processes():
    """{(pid, create time): (name, cpu seconds, working set)} for every process, in one call. psutil opens them one
    by one and, without admin, rescans the whole system for each protected one: half a second per refresh."""
    buf = ctypes.create_string_buffer(1 << 22)  # ponytail: ~4000 processes; grow it if a machine ever has more
    if ntdll.NtQuerySystemInformation(5, buf, len(buf), None):  # SystemProcessInformation
        return {}  # skip this refresh, like the Linux readers do
    out, off = {}, 0
    while True:  # SYSTEM_PROCESS_INFORMATION entries, chained by NextEntryOffset
        nxt, = struct.unpack_from("<I", buf, off)
        ctime, user, kernel = struct.unpack_from("<qqq", buf, off + 32)  # 100 ns units
        nlen, nptr = struct.unpack_from("<H6xQ", buf, off + 56)  # ImageName, a UNICODE_STRING
        pid, = struct.unpack_from("<Q", buf, off + 80)
        wset, = struct.unpack_from("<Q", buf, off + 144)
        if pid:  # pid 0 is the idle time, not a process
            # keyed by (pid, create time) like jtop.proc_times: a reused pid is a new process
            out[pid, ctime] = (ctypes.wstring_at(nptr, nlen // 2) if nptr else "", (user + kernel) / 1e7, wset)
        if not nxt:
            return out
        off += nxt


@functools.lru_cache(maxsize=1024)
def owner(pid, ctime):
    """(user, command line) of one process. psutil opens it, so only for the rows listed, and once per process:
    ctime is only there so a reused pid is a new cache entry."""
    try:
        p = psutil.Process(pid).as_dict(["username", "cmdline"])  # None where it needs admin
    except (psutil.Error, OSError):  # psutil lets some raw WinErrors through
        return "?", ""
    cmd = " ".join(" ".join(p["cmdline"] or []).split())  # newlines in args would break the row
    return (p["username"] or "?").rsplit("\\", 1)[-1], cmd  # PC\JEREMY -> JEREMY


def sample():
    return time.monotonic(), cpu_times(), disk_io(), net_io(), processes()


def filesystems():
    out = []
    for p in psutil.disk_partitions():
        try:
            u = psutil.disk_usage(p.mountpoint)
        except OSError:
            continue  # card reader or DVD drive with nothing in it
        if u.total:
            out.append((p.mountpoint, u.used, u.total))
    return out


def uptime():
    s = time.time() - psutil.boot_time()
    return f"{int(s // 86400)}d {int(s % 86400 // 3600)}h {int(s % 3600 // 60):02}m"


def components():
    cpu = r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
    bios = lambda f: reg(r"HARDWARE\DESCRIPTION\System\BIOS", f)
    mhz = reg(cpu, "~MHz", 0)
    release = 11 if sys.getwindowsversion().build >= 22000 else platform.release()  # Python < 3.12 says 10 on 11

    out = [
        ("Processor", [
            ("Model", reg(cpu, "ProcessorNameString").strip()),
            ("Cores / threads", f"{psutil.cpu_count(logical=False) or '?'} / {os.cpu_count()}"),
            ("Base frequency", f"{mhz / 1000:.2f} GHz" if mhz else "?"),  # the max needs a driver on Windows
            ("Architecture", platform.machine()),
        ]),
        ("Memory", [("RAM", human(psutil.virtual_memory().total)), ("Swap", human(psutil.swap_memory().total))]),
        ("System", [
            ("Machine", f"{bios('SystemManufacturer')} {bios('SystemProductName')}"),
            ("Motherboard", f"{bios('BaseBoardManufacturer')} {bios('BaseBoardProduct')}"),
            ("BIOS", f"{bios('BIOSVendor')} {bios('BIOSVersion')} ({bios('BIOSReleaseDate')})"),
            ("OS", f"Windows {release} {platform.win32_edition()} ({platform.version()})"),
        ]),
    ]

    # PCI only: no Basic Display, remote desktop or streaming virtual displays
    gpus = [k for k in subkeys(GPU_CLASS) if reg(k, "MatchingDeviceId", "").lower().startswith("pci\\")]
    if gpus:
        out.append(("Graphics", [(f"gpu{i}", f"{reg(k, 'DriverDesc')}  (driver {reg(k, 'DriverVersion')})")
                                 for i, k in enumerate(gpus)]))

    # ponytail: model only, no size or SSD/HDD; assumes disk\Enum lists them in PhysicalDriveN order
    enum = r"SYSTEM\CurrentControlSet\Services\disk\Enum"
    devices = [reg(enum, str(i)) for i in range(reg(enum, "Count", 0))]
    out.append(("Disks", [(f"PhysicalDrive{i}", reg(f"SYSTEM\\CurrentControlSet\\Enum\\{d}", "FriendlyName"))
                          for i, d in enumerate(devices)]))

    stats, addrs = psutil.net_if_stats(), psutil.net_if_addrs()
    nets = []
    for n, kind in sorted(NICS.items()):
        if n not in stats:
            continue  # unplugged: the registry keeps every adapter it has seen
        mac = next((a.address for a in addrs.get(n, ()) if a.family == psutil.AF_LINK), "?")
        speed = f"  {stats[n].speed} Mb/s" if stats[n].speed > 0 else ""
        nets.append((n, f"{kind}  {mac}  {'up' if stats[n].isup else 'down'}{speed}"))
    out.append(("Network", nets))
    return out


# ---------- layout: jtop.py's, fed by psutil ----------
# ponytail: bar, row, usage_lines, process_lines, draw and main copy jtop.py's so it stays untouched; share them if
# they drift.

def bar(label, pct, width, value=None, extra="", color=None):
    """jtop.bar as a VU meter: each cell takes jtop.level's color at its end, so the hot end shows without reading
    the number and the last cell matches level(pct). A forced color (battery: low charge is the bad end) stays one."""
    pct = max(0.0, min(pct, 100.0))
    value = value or f"{pct:5.1f}%"
    extra = f" {extra:<24}" if extra else ""
    n = max(width - len(label) - len(value) - len(extra) - 3, 5)
    fill = round(n * pct / 100)
    ends = (100 * i / n for i in range(1, fill + 1))  # where each filled cell ends, in %
    cells = [("█" * len(list(g)), s) for s, g in itertools.groupby(color or level(e) for e in ends)]
    return ([(label, "bold"), ("▕", "dim")] + cells +
            [("░" * (n - fill), "dim"), ("▏", "dim"), (value + " ", "bold"), (extra, "dim")])


def row(label, pct, w, value=None, extra=" ", color=None):
    return bar(f"  {label[:LABEL - 3]:<{LABEL - 2}}", pct, w - 1, value, extra, color)


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

    m, swap = psutil.virtual_memory(), psutil.swap_memory()  # m.used is total - available, like jtop
    lines += [[], header("Memory", w), row("RAM", m.percent, w, extra=f"{human(m.used)} / {human(m.total)}")]
    if swap.total:
        lines.append(row("Swap", swap.percent, w, extra=f"{human(swap.used)} / {human(swap.total)}"))

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

    b = psutil.sensors_battery()
    if b:
        status = "Plugged in" if b.power_plugged else "On battery"  # Windows doesn't say if it is charging
        color = "crit" if b.percent < 15 else "warn" if b.percent < 30 else "good"  # low charge is the bad end
        lines += [[], header("Battery", w), row("Battery", b.percent, w, extra=status, color=color)]
    return lines


def process_lines(w, prev, cur, show_all=False):
    """jtop.process_lines without STATE: Windows only knows running or suspended."""
    dt = max(cur[0] - prev[0], 1e-3)
    total = psutil.virtual_memory().total
    procs = [(100 * (secs - prev[4][key][1]) / dt, rss, key, name)
             for key, (name, secs, rss) in cur[4].items() if key in prev[4]]
    procs.sort(reverse=True)  # busiest first, then biggest memory

    columns = f"{'PID':>7}  {'USER':<10} {'CPU%':>6} {'MEM%':>5} {'MEM':>9}  COMMAND"
    title = f"Processes  all {len(procs)}  a: top 10" if show_all else f"Processes  top 10 of {len(procs)}  a: show all"
    lines = [[], header(title, w), [(columns.ljust(w), "title")]]  # tab_off is gray here, like the PIDs below
    for cpu, rss, (pid, ctime), name in procs if show_all else procs[:10]:
        user, cmd = owner(pid, ctime)
        lines.append([(f"{pid:>7}  ", "dim"), (f"{user[:10]:<10} ", ""), (f"{cpu:6.1f} ", level(cpu) if cpu else "dim"),
                      (f"{100 * rss / total:5.1f} ", ""), (f"{human(rss):>9}  ", ""),
                      ((cmd or name) if show_all else name, "bold")])
    return lines


# ---------- curses ----------

def init_styles():
    """jtop's styles with a real gray: PDCurses ignores A_DIM, so secondary text was as bright as the data, and the
    reversed tabs and footer outweighed it."""
    styles = jtop_styles()
    if curses.has_colors() and curses.COLORS >= 16:
        # bright black, from the constant: PDCurses numbers colors like the Windows console (red 4, not 1)
        curses.init_pair(6, curses.COLOR_BLACK + 8, -1)
        gray = curses.color_pair(6)
        styles.update(dim=gray, tab_off=gray, tab_on=styles["title"] | curses.A_UNDERLINE)
    return styles


def draw(scr, tab, scroll, lines, styles):
    scr.erase()
    h, w = scr.getmaxyx()
    x = 1
    for i, name in enumerate(TABS):
        label = f" {i + 1} {name} "
        scr.addnstr(0, x, label, max(w - x, 0), styles["tab_on" if i == tab else "tab_off"])
        x += len(label) + 1
    info = f"host {platform.node()}  uptime {uptime()}  {time.strftime('%H:%M:%S')} "
    if w - len(info) > x:
        scr.addstr(0, w - len(info), info, styles["dim"])

    for y, line in enumerate(lines[scroll:scroll + h - 2], 1):
        put_line(scr, y, 0, w, line, styles)

    footer = " Tab switch   ↑↓ scroll   q quit"
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
    a = sample()
    time.sleep(0.2)
    b = sample()
    act, tot = deltas(a[1], b[1])["cpu"]
    assert 0 <= act <= tot
    assert tot > 1000, "CPU times in seconds: jtop.cpu_percent's floor of 1 would cap the bars"
    vu = lambda pct, width=104, color=None: [s for t, s in bar("", pct, width, color=color) if "█" in t]
    assert vu(90) == ["good", "warn", "crit"] and vu(50) == ["good"], "VU meter zones"
    assert all(vu(p, w)[-1] == level(p) for p in (30, 70, 87, 100) for w in (20, 104)), "last cell != level(pct)"
    assert vu(90, color="warn") == ["warn"], "a forced color must stay one color"
    assert any(pid == os.getpid() and name.lower().startswith("python")
               for (pid, _), (name, _, _) in b[4].items()), "process snapshot misread"
    procs = process_lines(120, a, b, show_all=True)
    assert any(str(os.getpid()) in "".join(t for t, _ in l) for l in procs), "own process missing"
    assert len(process_lines(120, a, b)) == 3 + min(10, len(procs) - 3), "top 10"
    comps = components()
    assert comps[0][1][0][1] != "?", "CPU model not read from the registry"
    for w in (90, 160):
        lines = component_lines(comps, w) + usage_lines(w, a, b) + process_lines(w, a, b)
        assert all(len("".join(t for t, _ in l)) <= w for l in lines if l[:1] and l[0][1] != "dim"), "overflow"
    print("ok")


if __name__ == "__main__":
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
