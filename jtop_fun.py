#!/usr/bin/env python3
"""jtop --fun : EASTER EGG / TROLL. Nothing in here is real, except the top-left pane and the CPU graph.

A fake "Hollywood hacker" screen: a grid of panes spamming fake processes hacks, fake network
requests, random hexdumps, Matrix rain, fake password cracking and a fake build log.

To remove it: delete this file and the `--fun` branch at the bottom of jtop.py.
Self-test: python3 jtop_fun.py --check
"""
import collections
import curses
import itertools
import os
import random
import sys
import time

from jtop import (bar, batteries, cpu_percent, cpu_times, deltas, human, init_styles, meminfo, proc_stat, put_line,
                  read, sample, temps, uptime)

# A pane is a function (w, h, ctx) -> lines. Only the top-left pane and the CPU graph show real data.

FONT = {
    "Y": ["█  █", "█  █", " ██ ", " ██ ", " ██ "], "E": ["████", "█   ", "███ ", "█   ", "████"],
    "S": [" ███", "█   ", " ██ ", "   █", "███ "], "I": ["███", " █ ", " █ ", " █ ", "███"],
    "'": ["█", "█", " ", " ", " "], "M": ["█   █", "██ ██", "█ █ █", "█   █", "█   █"],
    "A": [" ██ ", "█  █", "████", "█  █", "█  █"], "H": ["█  █", "█  █", "████", "█  █", "█  █"],
    "C": [" ███", "█   ", "█   ", "█   ", " ███"], "K": ["█  █", "█ █ ", "██  ", "█ █ ", "█  █"],
    "R": ["███ ", "█  █", "███ ", "█ █ ", "█  █"], " ": ["  "] * 5,
}
GLITCH = "#@$%&*!?/\\<>=+"


def big(text):
    return [" ".join(FONT[c][i] for c in text) for i in range(5)]


def banner(w, h, ctx):
    for words in (["YES I'M", "A HACKER"], ["YES", "I'M A", "HACKER"]):
        rows = [r for word in words for r in big(word) + [""]][:-1]
        if max(map(len, rows)) <= w and len(rows) <= h:
            break
    else:
        rows = ["YES I'M A HACKER"]
    color = ("good", "title", "crit", "warn")[ctx["frame"] // 8 % 4]
    lines = [[]] * ((h - len(rows)) // 2)
    for r in rows:
        if random.random() < 0.08:  # glitch
            i = random.randrange(len(r) or 1)
            r = r[:i] + random.choice(GLITCH) + r[i + 1:]
        lines.append([(" " * ((w - len(r)) // 2) + r, color)])
    return lines


def summary(w, h, ctx):
    s = ctx["stats"]
    lines = [bar("CPU  ", s["cpu"], w), bar("RAM  ", s["ram"], w), bar("TEMP ", s["temp"], w, value=f"{s['temp']:4.0f}°C")]
    if s["bat"] is not None:
        lines.append(bar("BAT  ", s["bat"], w, color="good"))
    return lines + [[], [(f"▼ {human(s['rx'])}/s  ▲ {human(s['tx'])}/s", "good")],
                    [(f"{s['procs']} processes · up {uptime()}", "dim")], [], [("q quit", "dim")]]


def cpu_graph(w, h, ctx):
    """Real total CPU %, one column per frame, auto-zoomed so an idle machine still moves."""
    hist = ([0.0] * w + ctx["history"])[-w:]
    top = max(5.0, *hist)
    lines = [[(f"peak {top:.0f}%", "dim")]]
    for r in range(h - 1):
        base = (h - 2 - r) * 8
        cells = (max(0, min(8, int(v / top * (h - 1) * 8) - base)) for v in hist)
        lines.append([("".join(" ▁▂▃▄▅▆▇█"[n] for n in cells), "good")])
    return lines


def matrix():
    drops = {}

    def step(w, h, ctx):
        for x in range(w):
            if x not in drops and random.random() < 0.04:
                drops[x] = 0
        grid = [[(" ", "")] * w for _ in range(h)]
        for x, y in list(drops.items()):
            for k in range(8):
                if 0 <= y - k < h and x < w:
                    grid[y - k][x] = (random.choice("01$#@%&*+=<>?ABCDEFXYZ"), "bold" if k == 0 else "good")
            drops[x] = y + 1
            if y - 8 > h:
                del drops[x]
        return [list(r) for r in grid]
    return step


def feed(make, per_frame=2):
    buf = collections.deque(maxlen=200)

    def step(w, h, ctx):
        for _ in range(per_frame):
            buf.append(make(w, ctx))
        return list(buf)[-h:]
    return step


def proc_line(w, ctx):
    pid = random.choice(list(ctx["cur"][4]))
    st = proc_stat(pid)
    verdict = random.choice((("SCANNED", "good"), ("HOOKED", "warn"), ("INJECTED", "title"), ("PWNED", "crit")))
    return [(f"{pid:>7} ", "dim"), (f"{(st[0] if st else '?')[:15]:<15} ", "bold"),
            (f"0x{random.getrandbits(32):08x} ", "dim"), verdict]


def net_line(w, ctx):
    ip = lambda: f"{random.choice(('192.0.2', '198.51.100', '203.0.113', '10.13.37'))}.{random.randint(1, 254)}"
    path = random.choice(("/api/v1/users", "/admin/login", "/mainframe/core", "/satellite/uplink", "/vault/keys",
                          "/coffee/brew", "/.env", "/matrix/reload", "/gibson/garbage"))
    status = random.choice((("200 OK", "good"), ("200 OK", "good"), ("403 DENIED", "crit"), ("301 MOVED", "warn"),
                            ("418 TEAPOT", "title")))
    return [(time.strftime("%H:%M:%S "), "dim"), (f"{ip()} → {ip()}:443 ", ""),
            (f"{random.choice(('GET', 'POST', 'PUT'))} {path} ", "bold"), status, (f" {random.randint(3, 999)}ms", "dim")]


def hex_line():
    offsets = itertools.count(0, 8)

    def make(w, ctx):
        data = os.urandom(8)
        text = "".join(chr(b) if 32 <= b < 127 else "." for b in data)
        return [(f"{next(offsets):08x}  ", "dim"), (data.hex(" ") + "  ", "good"), (text, "bold")]
    return make


def build_line(w, ctx):
    msg = random.choice((
        f"Compiling quantum_{random.choice(('driver', 'kernel', 'flux', 'core'))}.c",
        f"Bypassing firewall layer {random.randint(1, 7)}/7",
        f"Decrypting sector 0x{random.getrandbits(16):04x}",
        f"Rerouting through proxy {random.randint(1, 99)}",
        f"Downloading more RAM ({random.choice((8, 16, 64, 640))} GB)",
        "Reticulating splines", "Enhancing image... ENHANCE", "Disabling the mainframe's mainframe",
    ))
    tag = random.choice((("[ OK ] ", "good"), ("[ OK ] ", "good"), ("[WARN] ", "warn"), ("[ .. ] ", "dim")))
    return [tag, (msg, "")]


# Names for the "loading" pane: loading.txt, shipped next to this file. One name per line;
# anything after a tab is ignored, so a pasted 2-column table works.
LOADING_FILE = os.path.join(os.path.dirname(os.path.realpath(__file__)), "loading.txt")


def loading_names():
    try:
        with open(LOADING_FILE, encoding="utf-8", errors="replace") as f:
            names = [line.split("\t")[0].strip() for line in f if line.strip()]
    except OSError:
        names = []
    return random.sample(names, len(names)) or ["(no loading.txt)"]


def loader():
    """Fake loading screen: each name runs 0 -> 100 %, shows "done" for a moment, then the next one starts."""
    names = itertools.cycle(loading_names())
    jobs = []

    def step(w, h, ctx):
        while len(jobs) < max(1, h // 2):
            jobs.append([next(names), 0.0, 0])
        spin = "|/-\\"[ctx["frame"] % 4]  # ASCII: braille spinners are double-width in some fonts
        lines = []
        for job in jobs:
            job[1] = min(100.0, job[1] + random.random() * 2.5)
            done = job[1] >= 100
            job[2] += done
            lines += [[(f"{'+' if done else spin} {job[0]} ", "bold"), ("done" if done else "is running...", "good" if done else "dim")],
                      bar("  ", job[1], w, color="good" if done else "warn")]
        jobs[:] = [j for j in jobs if j[2] < 15]  # keep "done" visible ~1 s
        return lines
    return step


def layout(h, w):
    """Grid of panes: our real stats top-left, the banner top-right, effects everywhere else."""
    cols, rows = (3, 3) if w < 180 else (4, 3)
    effects = itertools.cycle([
        ("/proc", feed(proc_line, 3)), ("net", feed(net_line, 2)), ("matrix", matrix()),
        ("hexdump", feed(hex_line(), 3)), ("loading", loader()), ("cpu % (live)", cpu_graph),
        ("build", feed(build_line, 1)),
    ])
    panes = []
    for i in range(cols * rows):
        r, c = divmod(i, cols)
        title, step = ("jtop", summary) if i == 0 else ("yes", banner) if i == cols - 1 else next(effects)
        x, y = c * (w // cols), r * (h // rows)
        pw = w // cols if c < cols - 1 else w - x
        ph = h // rows if r < rows - 1 else h - y
        panes.append((y, x, ph, pw, title, step))
    return panes


def fun_stats(prev, cur):
    dt = max(cur[0] - prev[0], 1e-3)
    m = meminfo()
    net = deltas(prev[3], cur[3]).values()
    bats = batteries()
    return {"cpu": cpu_percent(prev, cur).get("cpu", 0), "ram": 100 * (m["MemTotal"] - m["MemAvailable"]) / m["MemTotal"],
            "temp": max((c for _, c in temps()), default=0), "procs": len(cur[4]),
            "bat": int(read(bats[0] / "capacity", "0")) if bats else None,
            "rx": sum(v[0] for v in net) / dt, "tx": sum(v[1] for v in net) / dt}


def fun(scr):
    styles = init_styles()
    scr.timeout(60)
    prev = sample()
    time.sleep(0.2)
    cur = sample()
    stats = fun_stats(prev, cur)
    ctx = {"prev": prev, "cur": cur, "frame": 0, "stats": stats, "history": []}
    last = cpu_times()["cpu"]
    size = panes = None
    while True:
        h, w = scr.getmaxyx()
        if (h, w) != size:
            size, panes = (h, w), layout(h, w)
        if time.monotonic() - ctx["cur"][0] >= 1:
            ctx["prev"], ctx["cur"] = ctx["cur"], sample()
            ctx["stats"] = fun_stats(ctx["prev"], ctx["cur"])
        now = cpu_times()["cpu"]
        ctx["history"] = ctx["history"][-500:] + [100 * (now[0] - last[0]) / max(now[1] - last[1], 1)]
        last = now
        scr.erase()
        for y, x, ph, pw, title, step in panes:
            try:
                scr.addnstr(y, x, "┌" + "─" * (pw - 2) + "┐", pw, styles["dim"])
                for i in range(1, ph - 1):
                    scr.addstr(y + i, x, "│", styles["dim"])
                    scr.addstr(y + i, x + pw - 1, "│", styles["dim"])
                scr.addnstr(y + ph - 1, x, "└" + "─" * (pw - 2) + "┘", pw - (y + ph == h and x + pw == w), styles["dim"])
                scr.addnstr(y, x + 2, f" {title} ", pw - 4, styles["title"])
                for i, line in enumerate(step(pw - 2, ph - 2, ctx)[:ph - 2]):
                    put_line(scr, y + 1 + i, x + 1, pw - 2, line, styles)
            except curses.error:
                pass  # pane too small for this terminal size
        scr.refresh()
        ctx["frame"] += 1
        if scr.getch() == ord("q"):
            break


def run():
    print("\033[10;1t", end="", flush=True)  # ask the terminal for fullscreen; ignored where unsupported
    try:
        curses.wrapper(fun)
    finally:
        print("\033[10;0t", end="", flush=True)


def check():
    a = sample()
    time.sleep(0.2)
    b = sample()
    ctx = {"prev": a, "cur": b, "frame": 0, "stats": fun_stats(a, b), "history": [10.0, 50.0, 100.0]}
    for h, w in ((24, 80), (40, 120), (60, 240)):  # every fun pane renders, a few frames each
        for frame in range(20):
            ctx["frame"] = frame
            for _, _, ph, pw, _, step in layout(h, w):
                step(pw - 2, ph - 2, ctx)
    assert any("█" in "".join(t for t, _ in l) for l in banner(38, 11, ctx)), "banner too big for a 3x3 pane"
    print("ok")


if __name__ == "__main__":
    check() if "--check" in sys.argv else run()
