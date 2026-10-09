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
import math
import os
import random
import sys
import time

from jtop import (TABS, bar, component_lines, components, cpu_times, init_styles, process_lines, put_line,
                  sample, usage_lines)

# A pane is a function (w, h, ctx) -> lines. Only the top-left pane and the CPU graph show real data.

FONT = {
    "Y": ["█  █", "█  █", " ██ ", " ██ ", " ██ "], "E": ["████", "█   ", "███ ", "█   ", "████"],
    "S": [" ███", "█   ", " ██ ", "   █", "███ "], "I": ["███", " █ ", " █ ", " █ ", "███"],
    "'": ["█", "█", " ", " ", " "], "M": ["█   █", "██ ██", "█ █ █", "█   █", "█   █"],
    "A": [" ██ ", "█  █", "████", "█  █", "█  █"], "H": ["█  █", "█  █", "████", "█  █", "█  █"],
    "C": [" ███", "█   ", "█   ", "█   ", " ███"], "K": ["█  █", "█ █ ", "██  ", "█ █ ", "█  █"],
    "R": ["███ ", "█  █", "███ ", "█ █ ", "█  █"], " ": ["  "] * 5,
    "L": ["█   ", "█   ", "█   ", "█   ", "████"], "O": [" ██ ", "█  █", "█  █", "█  █", " ██ "],
    "W": ["█   █", "█   █", "█ █ █", "██ ██", "█   █"], "D": ["███ ", "█  █", "█  █", "█  █", "███ "],
}
GLITCH = "#@$%&*!?/\\<>=+"


def big(text):
    return [" ".join(FONT[c][i] for c in text) for i in range(5)]


def banner(w, h, ctx):
    hello = ctx["frame"] // 50 % 4 == 3  # ~3 s of "HELLO WORLD" every ~12 s
    layouts = [["HELLO", "WORLD"]] if hello else [["YES I'M", "A HACKER"], ["YES", "I'M A", "HACKER"]]
    for words in layouts:
        rows = [r for word in words for r in big(word) + [""]][:-1]
        if max(map(len, rows)) <= w and len(rows) <= h:
            break
    else:
        rows = ["HELLO WORLD" if hello else "YES I'M A HACKER"]
    color = ("good", "title", "crit", "warn")[ctx["frame"] // 8 % 4]
    lines = [[]] * ((h - len(rows)) // 2)
    for r in rows:
        if random.random() < 0.08:  # glitch
            i = random.randrange(len(r) or 1)
            r = r[:i] + random.choice(GLITCH) + r[i + 1:]
        lines.append([(" " * ((w - len(r)) // 2) + r, color)])
    return lines


def runs(cells):
    """(char, style) cells -> a put_line line, one segment per run of the same style."""
    return [("".join(ch for ch, _ in g), st) for st, g in itertools.groupby(cells, key=lambda c: c[1])]


SKULL = """\
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣀⣠⣤⣤⣤⣤⢖⣶⣶⠶⣤⣤⣤⣀⢀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣾⣿⣿⡟⠻⠛⠉⠛⠛⠙⠝⠋⠙⢿⣍⣯⣿⡷⣶⣤⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣨⠿⡽⣥⢏⡏⠂⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠙⢿⣷⣄⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⢀⠼⠃⠀⢹⣧⠀⢳⣄⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠙⢿⣿⣷⣤⡀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⡠⠫⢶⠀⠀⠀⢻⡧⠰⠉⣷⠄⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢠⠛⢿⣿⣷⡀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⣠⠎⠁⠀⠀⠀⠀⣀⣸⣏⠀⠀⢹⢷⠄⠀⠀⠀⠀⠀⠀⠀⠀⣀⡀⠒⢄⠀⢀⠞⠁⠀⠈⣿⣿⣿⣦⠀⠀⠀⠀
⠀⠀⠀⠀⠎⠀⠀⠈⠀⣠⣾⠟⠛⠛⠉⠑⢮⡁⡿⠀⠀⠀⠀⠀⠀⠀⢀⣼⣿⣿⣿⣾⣷⣧⣄⡀⠀⠀⢹⣿⣿⣿⣷⡀⠀⠀
⠀⠀⠀⢀⠆⢀⠀⢀⡴⠋⠀⣠⡄⢠⡀⠀⠀⠙⡇⠀⠀⠀⠀⠀⠀⠀⣸⣿⣿⣿⣿⣿⣿⣿⣿⣿⣶⣄⠀⢿⣿⣿⣿⣷⡀⠀
⠀⠀⠀⡸⠀⡸⠀⡼⠀⠀⠀⣻⡏⠀⣾⡇⠀⢀⠇⠀⢤⣶⣤⡈⢦⡀⠼⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⣿⡇⠈⣿⣿⣿⣿⣇⠀
⠀⠀⢰⣇⢠⠇⠀⡇⠀⠀⠀⡿⡧⡽⡟⡆⢠⠞⠀⣼⣿⣿⣿⣿⡄⠹⣄⣈⠛⣿⣿⣿⣿⣿⣿⣿⣿⣿⣧⡀⣿⣿⣿⣿⣿⠀
⠀⠀⣼⣿⠏⠀⢠⣇⣀⠀⣘⣤⢤⣧⣴⠖⠋⠀⢀⣿⣿⣿⣿⣿⣿⠀⣿⡏⢀⠈⠻⢿⣿⣿⣿⣿⣿⣿⣿⡇⢸⣿⣿⣿⣿
⠀ ⢿⣿⠀⠀⠖⣛⣹⠛⠛⠛⠋⠀  ⢀⡢⠀⢸⣿⣿⣿⣿⣿⣿⣷⠘⣇⠀⠁⠠⠤⢅⡀⠉⣉⣛⣋⡉⢀⣿⣿⣿⣿⣿
⠀ ⢿⡏ ⠀⠀⠈⠀⠀⠀⠀⠐⠒⠋⠉⠀⠀⠀⠀⢿⡿⠻⣿⣿⣿⠇⡈⣄⠀⠀    ⠀⠀⠈⠑⠾⠿⣿⣿⣿⣿⡟⣿⣿
⠀  ⣿⠃  ⠀⠀⠀⠀⠱⡀⠀⠀⠀⠀⠀⠉⠀⠀⠀⠀⠚⠁⠀⡈⠛⡅⠀⡇⢸⣟⠂⠀⠀⠀⠀⠀⠀⠀⠋⠛⢋⣼⣿⣿⣿
⠀ ⡼⠃⠀⠀⠀⠀⠀⠔⠁⠀⠀⠀  ⠀⠐⡏⠀⠀⠀⠀⡇⠀⠀⣧⠀⢢⠀⢱⠸⣿⣯⣠⠀⠀⠀ ⠀⠀⣀⣴⣠⣺⣿⣿⣿⠀
⢠⠃⢀⣀⠤⠐⢉⣩⣉⠁⠀⠀⠀⠀⡜⢀⣄⣀⠦⡘⠛⢂⠜⠛⢧⠞⠳⢘⡀⢹⣿⣷⠀⠀⢀⡀⣊⡁⠈⠙⣿⣿⣿⣿⣿⠀
⣸⠐⢁⣴⢶⣶⣿⣿⣿⣿⣄⠉⢆⠀⣑⡜⠉⣟⣀⣤⣀⣤⠦⠤⢼⣅⣨⢸⢸⣿⣿⣿⣇⣠⣤⣿⣥⣾⣷⣶⣌⠉⠙⢻⠀
⠙⠷⣾⠣⣿⣿⡿⢿⣿⢻⣿⣷⡜⠀⡛⢿⣾⡟⠁⠀⠀⠀⠀⠀⠀⠀⠉⠑⠙⣶⠙⣿⣿⣏⣿⠟⣿⣿⣿⣿⣿⣧⠀⢸⡇⠀
⠀⠀⠀⢳⣿⣿⡆⠘⣿⢨⣿⣿⡗⢰⠿⠶⡿⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣹⢉⣹⣿⣿⡿⢰⣿⡇⣼⣿⣿⡿⠀⢴⠅⠀
⠀⠀⠀⠀⢳⡀⠀⠘⣿⠘⣿⣿⣿⠸⡀⣠⠃⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣿⠖⢊⡝⡿⠃⢸⣿⠀⣿⣿⣿⣷⡆⡇⠀⠀
⠀⠀⠀⠀⠈⣧⠀⢸⣿⠀⣿⣷⢻⣻⣾⡷⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠙⠒⠚⠋⠁⠀⣿⡇⢠⣿⣿⣿⡿⠀⣇⠀⠀
⠀⠀⠀⠀⠀⣸⠀⢨⣿⡇⣽⣿⠟⣷⣿⡏⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢠⣿⠁⢸⣿⣿⣿⠇⢀⡎⠀⠀
⠀⠀⠀⠀⡀⢸⠀⠀⣿⡏⣿⡿⠷⠻⣽⡇⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢸⣿⠀⣾⣿⣿⠟⠀⣿⠀⠀⠀
⠀⠀⠀⠀⢼⣼⡆⢀⡙⢷⣿⣷⡞⣾⣻⣧⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣾⡏⠐⣿⡟⠁⠀⣼⡿⠀⠀⠀
⠀⠀⠀⠀⠸⣿⡇⠀⠘⢾⣿⣯⠗⢿⣻⡿⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣼⣿⠃⠀⣿⣷⣾⣿⡿⠃⠀⠀⠀
⠀⠀⠀⠀⠀⠈⣏⠂⠀⠀⠹⢷⣿⠿⣿⣧⡤⢶⢲⣦⣤⠤⢤⡠⢄⣀⣀⣤⢤⡦⡴⡆⠀⣿⡃⠄⢀⣻⣿⣿⠁⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠸⣖⠀⠀⠀⢀⠉⡀⢈⠀⢻⡉⢹⠁⡷⠀⠸⠀⠘⡀⢻⡄⢸⣇⣿⡅⢀⣿⠋⠀⠸⣿⣿⠇⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⣦⣆⠀⠀⠈⠐⠄⠘⠉⠉⢻⠞⠒⣾⠲⡴⠒⠾⠓⢺⠙⠉⡿⣿⣶⣾⡿⠂⠀⠐⣿⡿⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠈⠙⢆⠀⠀⠀⠀⡀⠀⠀⠘⠀⠀⠈⠀⠇⠀⢘⠀⠚⠀⠀⠇⢻⣿⣿⡧⠀⠀⠀⣿⡇⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⣷⡄⠀⠀⠁⠐⠶⠆⠐⠀⠀⠀⠒⣀⣠⣆⣀⠀⢤⣠⣾⡿⠉⠀⠀⣀⣠⡟⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣷⢆⡀⠀⠀⠀⠀⠀⠀⠀⠀⠊⠙⢿⣿⣿⡿⠿⡿⣯⣶⠆⢠⠌⠉⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠉⠻⢷⡄⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣀⡠⠖⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠙⠓⠛⠒⠒⠖⠛⠛⠛⠛⠛⠛⠛⠛⠋⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
""".splitlines()


def takeover_lines(w, h, elapsed, frame):
    """The every-5-minutes gag: the whole screen 'corrupts', then a red skull bobs over flames."""
    if elapsed < 1.0:  # full corruption
        return [[("".join(random.choice(GLITCH) for _ in range(max(0, w))),
                  random.choice(("crit", "warn", "good", "title")))] for _ in range(h)]
    aw, ah = max(map(len, SKULL)), len(SKULL)
    fh = max(3, min(h // 3, h - ah - 1))  # flame rows at the bottom
    left = max(0, (w - aw) // 2)
    top = max(0, (h - fh - ah) // 2) + frame // 4 % 2  # bobbing up and down
    lines = [[] for _ in range(top)]
    for y, row in enumerate(SKULL[:max(0, h - fh - top)]):
        cells = []
        for x, ch in enumerate(row):
            r = math.hypot((x - aw / 2) / (aw / 2), (y - ah / 2) / (ah / 2))  # red glow from the center out
            cells.append((ch, "glow" if r < 0.45 else "ember" if r > 0.85 else "crit"))
        lines.append([(" " * left, "")] + runs(cells))
    lines += [[] for _ in range(h - fh - len(lines))]
    return lines + FIRE(w, fh + 1, None)


def real_jtop(w, h, ctx):
    """The real jtop, live, inside its little pane: Tab switches, arrows scroll, a toggles all in Processes."""
    tabbar = []
    for i, name in enumerate(TABS):
        tabbar += [(f" {i + 1} {name} ", "tab_on" if i == ctx["tab"] else "tab_off"), (" ", "")]
    if ctx["tab"] == 0:
        content = component_lines(ctx["comps"], w)
    elif ctx["tab"] == 1:
        content = usage_lines(w, ctx["prev"], ctx["cur"])
    else:
        content = process_lines(w, ctx["prev"], ctx["cur"], ctx["show_all"])
    ctx["scroll"] = max(0, min(ctx["scroll"], len(content) - (h - 1)))
    return [tabbar] + content[ctx["scroll"]:ctx["scroll"] + h - 1]


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


def feed(make, per_frame=2):
    buf = collections.deque(maxlen=200)

    def step(w, h, ctx):
        for _ in range(per_frame):
            buf.append(make(w, ctx))
        return list(buf)[-h:]
    return step


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


# Names for the "loading" pane.
LOADING = (
    'abuseACL', 'aclpwn', 'AD-miner', 'adidnsdump', 'adwsdomaindump', 'aircrack-ng', 'aliasr', 'alterx',
    'amass', 'amber', 'androguard', 'android-tools-adb', 'anew', 'angr', 'apksigner', 'apktool', 'arjun',
    'asciinema', 'asdf', 'asrepcatcher', 'assetfinder', 'autobloody', 'autoconf', 'autorecon', 'avrdude',
    'awscli', 'azure-cli', 'badsecrets', 'BBOT', 'bettercap', 'binaryninja', 'binwalk', 'Blackbird',
    'bloodbash', 'bloodhound', 'BloodHound-CE', 'bloodhound-ce.py', 'bloodhound-import',
    'bloodhound-quickwin', 'bloodhound.py', 'bloodyAD', 'bolt', 'bqm', 'brakeman', 'bruteforce-luks', 'bully',
    'burpsuite', 'byp4xx', 'caido', 'carbon14', 'Censys', 'certipy', 'certsync', 'cewl', 'cewler', 'chainsaw',
    'chaos', 'checksec-py', 'chisel', 'cloudfail', 'cloudmapper', 'cloudsplaining', 'cloudsploit', 'clusterd',
    'cmloot', 'cmsmap', 'coercer', 'conpass', 'constellation', 'corscanner', 'cowpatty', 'crackhound',
    'creds', 'crunch', 'cupp', 'curlie', 'CyberChef', 'cyperoth', 'daclsearch', 'darkarmour', 'dex2jar',
    'dfscoerce', 'dirb', 'dirsearch', 'divideandscan', 'dns2tcp', 'dnschef', 'dnsenum', 'dnsx', 'donpapi',
    'dploot', 'droopescan', 'drupwn', 'dtrx', 'eaphammer', 'empire', 'enum4linux-ng', 'enyx', 'EVENmonitor',
    'evil-winrm-py', 'evilwinrm', 'exegol-history', 'exif', 'exifprobe', 'exiftool', 'exiv2',
    'ExtractBitlockerKeys', 'eyewitness', 'fcrackzip', 'fdisk', 'feroxbuster', 'ffuf', 'fierce', 'finalrecon',
    'findomain', 'firefox', 'firefox_decrypt', 'foremost', 'fping', 'freeipscanner', 'freerdp2-x11', 'frida',
    'fuxploider', 'fzf', 'gau', 'gef', 'genusernames', 'GeoPincer', 'geowordlists', 'gf', 'ghidra', 'GHunt',
    'git-dumper', 'githubemail', 'gitleaks', 'gittools', 'glow', 'gmsadumper', 'gobuster', 'godap', 'GoExec',
    'goldencopy', 'GoMapEnum', 'gopherus', 'gosecretsdump', 'goshs', 'gowitness', 'GPOddity', 'gpoParser',
    'gpp-decrypt', 'gqrx', 'gron', 'h2csmuggler', 'h8mail', 'hackrf', 'haiti', 'hakrawler', 'hakrevdns',
    'hashcat', 'hashonymize', 'Havoc', 'hcxdumptool', 'hcxtools', 'hexedit', 'Hob0Rules rules', 'holehe',
    'hping3', 'httpmethods', 'httprobe', 'httpx', 'hydra', 'ida', 'ignorant', 'imagemagick', 'impacket',
    'impacket', 'Instaloader', 'ipinfo', 'iptables', 'jackit', 'jadx', 'jd-gui', 'jdwp', 'john', 'joomscan',
    'jsluice', 'jwt', 'k9s', 'kadimus', 'katana', 'keepassxc', 'KeePwn', 'kerbrute', 'keytabextract',
    'kiterunner', 'Kraken', 'krbjack', 'krbrelayx', 'kubectl', 'ldapdomaindump', 'ldaprelayscan',
    'ldapsearch', 'ldapsearch-ad', 'LDAPWordlistHarvester', 'ldeep', 'legba', 'libmspack', 'libnfc',
    'libnfc-crypto1-crack', 'libusb-dev', 'ligolo-ng', 'linkedin2username', 'linkfinder', 'lnkup', 'lsassy',
    'ltrace', 'maigret', 'maltego', 'manspider', 'mariadb-client', 'masky', 'masscan', 'massdns', 'mdcat',
    'Metagoofil', 'metasploit', 'mfcuk', 'mfdread', 'mfoc', 'minicom', 'mitm6', 'mitmproxy', 'mobsf',
    'moodlescan', 'mousejack', 'msprobe', 'MurMurHash', 'naabu', 'name-that-hash', 'nasm', 'nbtscan', 'neo4j',
    'neovim', 'netdiscover', 'netexec', 'nfct', 'nfsshell', 'ngrok', 'nmap', 'nmap-parse-ouptut', 'noPac',
    'nosqlmap', 'NSAKEY rules', 'ntlmv1-multi', 'ntlm_theft', 'nuclei', 'oaburl', 'objection', 'objectwalker',
    'oletools', 'oneforall', 'onelistforall', 'OneRuleToRuleThemStill rules', 'onesixtyone', 'OpenVPN',
    'pacu', 'Pantagrule rules', 'pass', 'PassTheCert', 'patator', 'pcredz', 'pcsc', 'pdfcrack', 'peda',
    'peepdf', 'penelope', 'petitpotam', 'phoneinfoga', 'photon', 'PHP filter chain generator', 'phpggc',
    'pkcrack', 'pkinittools', 'polenum', 'postman', 'powershell', 'Powerview.py', 'pp-finder', 'pre2k',
    'pretender', 'prips', 'privexchange', 'prowler', 'proxmark3', 'proxychains', 'pst-utils', 'pth-tools',
    'pwncat-vl', 'pwndb', 'pwndbg', 'pwnedornot', 'pwninit', 'pwntools', 'PXEThief', 'pycdc',
    'pyFindUncommonShares', 'pyftpdlib', 'pygoldengmsa', 'pygpoabuse', 'pykek', 'pylaps', 'pymeta',
    'pypykatz', 'pyrit', 'pysnaffler', 'pywerview', 'pywhisker', 'pywsus', 'radare2', 'rdesktop', 'reaver',
    'recon-ng', 'recondog', 'redis-tools', 'RelayInformer', 'remmina', 'RemoteMonologue', 'responder',
    'rlwrap', 'ROADrecon', 'ROADtx', 'roastinthemiddle', 'robotstester', 'routersploit', 'RsaCracker',
    'rsactftool', 'rsync', 'rtl-433', 'ruler', 'rusthound', 'rusthound-ce', 'rustscan', 's3scanner',
    'samdump2', 'sccmhunter', 'sccmsecrets', 'sccmwtf', 'scout', 'scrcpy', 'searchsploit', 'seclists',
    'semgrep', 'shadowcoerce', 'sharker', 'shellerator', 'Sherlock', 'shuffledns', 'simplyemail',
    'sipvicious', 'sleuthkit', 'sliver', 'smali', 'smartbrute', 'smbclient', 'smbclient-ng', 'smbmap',
    'smtp-user-enum', 'smuggler', 'snaffler-ng', 'SoapUI', 'soapy', 'spiderfoot', 'sprayhound', 'sqlmap',
    'ssh-audit', 'sshuttle', 'sslscan', 'ssrfmap', 'steghide', 'stegolsb', 'stegosuite', 'strace',
    'subfinder', 'sublist3r', 'subzy', 'swaks', 'symfony-exploits', 'tailscale', 'targetedKerberoast',
    'tcpdump', 'tdo_dump', 'TeamsPhisher', 'testdisk', 'testssl', 'theharvester', 'thr', 'tig', 'timing',
    'tls-map', 'token-exploiter', 'tomcatwardeployer', 'tor', 'toutatis', 'traceroute', 'trevorspray', 'trid',
    'TriliumNext', 'trufflehog', 'tshark', 'uberfile', 'udpx', 'uncover', 'updog', 'uploader', 'upx',
    'urldedupe', 'username-anarchy', 'Villain', 'volatility2', 'volatility3', 'vt', 'wabt', 'wafw00f',
    'waybackurls', 'webclientservicescanner', 'weevely', 'wesng', 'wfuzz', 'whatportis', 'whatweb', 'whois',
    'wifite2', 'windapsearch-go', 'wireguard', 'wireshark', 'wpprobe', 'wpscan', 'wuzz', 'XSpear',
    'xsrfprobe', 'xsser', 'xsstrike', 'xtightvncviewer', 'XXEinjector', 'Yalis', 'yarn', 'youtubedl',
    'ysoserial', 'yt-dlp', 'Zehef', 'zerologon', 'zipalign', 'zsteg',
)


def loading_names():
    return random.sample(LOADING, len(LOADING))


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


def hacker_typer():
    """Types out jtop's own source, fast, with a blinking cursor. Real code, like hackertyper.net."""
    try:
        src = open(os.path.join(os.path.dirname(os.path.realpath(__file__)), "jtop.py")).read()
    except OSError:
        src = "print('hack the planet')\n" * 50
    src = src.expandtabs(4)
    pos = [0]

    def step(w, h, ctx):
        pos[0] = (pos[0] + random.randint(4, 12)) % len(src)
        shown = src[:pos[0]]
        rows = shown.splitlines()[-(h):] or [""]
        rows[-1] = rows[-1] + ("█" if ctx["frame"] % 2 else " ")  # blinking cursor
        return [[(r[:w], "good")] for r in rows]
    return step


def donut():
    """The classic spinning 3D ASCII donut (donut.c), by Andy Sloane."""
    a = [0.0]
    b = [0.0]

    def step(w, h, ctx):
        chars = ".,-~:;=!*#$@"
        out = [[" "] * w for _ in range(h)]
        zbuf = [[0.0] * w for _ in range(h)]
        A, B = a[0], b[0]
        for th in [i * 0.07 for i in range(90)]:
            for ph in [i * 0.02 for i in range(314)]:
                ct, st, cp, sp, cA, sA, cB, sB = (math.cos(th), math.sin(th), math.cos(ph), math.sin(ph),
                                                  math.cos(A), math.sin(A), math.cos(B), math.sin(B))
                cw = ct + 2
                d = 1 / (sp * cw * sA + st * cA + 5)
                t = sp * cw * cA - st * sA
                x = int(w / 2 + 0.5 * w * d * (cp * cw * cB - t * sB))
                y = int(h / 2 + h * d * (cp * cw * sB + t * cB))
                lum = cp * ct * sB - cA * ct * sp - sA * st + cB * (cA * st - ct * sA * sp)
                if 0 <= x < w and 0 <= y < h and d > zbuf[y][x]:
                    zbuf[y][x] = d
                    out[y][x] = chars[max(0, int(lum * 8))]
        a[0] += 0.07
        b[0] += 0.03
        return [[("".join(r), "warn")] for r in out]
    return step


CLAUDING = (
    "Clauding...", "Asking nicely for root...", "Downloading more GPUs...",
    "Explaining recursion to the kernel...", "Pondering the orb...", "Reticulating splines...",
    "Summoning the daemon...", "Negotiating with the firewall...", "Compiling good vibes...",
    "Teaching the mainframe to feel...", "Rebooting the matrix...", "Thinking really hard...",
    "Counting to infinity (twice)...", "Aligning the flux capacitor...", "Bribing the garbage collector...",
    "Translating cat to human...", "Rewriting it in Rust...", "Consulting the rubber duck...",
    "Untangling the dependency tree...", "Convincing the GPU to try again...", "Petting the neural net...",
    "Googling the error message...", "Blaming the intern...", "Turning it off and on again...",
)

CLAUDE_LOGO = (
    "   .  *  .   ",
    " *  \\ | /  * ",
    "-- --(*)-- --",
    " *  / | \\  * ",
    "   '  *  '   ",
)


def claude_clauding():
    feed_buf = collections.deque(maxlen=50)

    def step(w, h, ctx):
        if ctx["frame"] % 6 == 0:
            feed_buf.append(random.choice(CLAUDING))
        lines = [[(r.center(w), "title")] for r in CLAUDE_LOGO] + [[]]
        spin = "|/-\\"[ctx["frame"] % 4]
        for i, phrase in enumerate(list(feed_buf)[-(h - len(CLAUDE_LOGO) - 1):]):
            last = i == len(list(feed_buf)[-(h - len(CLAUDE_LOGO) - 1):]) - 1
            lines.append([(f" {spin if last else '+'} ", "title" if last else "good"),
                          (phrase, "bold" if last else "dim")])
        return lines
    return step


def doom_fire():
    """The Doom PSX fire effect, in ASCII, colored per cell so it looks right at any size."""
    grid = [[0]]
    chars = " .:-=+*#%@"

    def cell_style(c):
        return "bold" if c >= 28 else "warn" if c >= 18 else "crit" if c >= 6 else "dim"

    def step(w, h, ctx):
        if len(grid) != h or len(grid[0]) != w:
            grid[:] = [[0] * w for _ in range(h)]
            grid[-1] = [36] * w  # bottom row: the fire source, always max heat
        grid[-1] = [random.randint(26, 36) for _ in range(w)]  # flickering source
        for x in range(w):
            for y in range(1, h):
                decay = random.randint(0, 3)
                dst = max(0, min(w - 1, x - decay + 1))
                grid[y - 1][dst] = max(0, grid[y][x] - decay)  # bigger drop -> flames taper into tongues
        return [runs((chars[min(len(chars) - 1, c * len(chars) // 37)], cell_style(c) if c else "dim") for c in row)
                for row in grid[:-1]]
    return step


# The worst, most common passwords. A gag pane mocking weak passwords.
PASSWORDS = (
    '123456', '12345678', '123456789', 'admin', '1234', 'Aa123456', '12345', 'password', '123', '1234567890',
    'qwerty', 'qwerty123', 'Aa@123456', '1234567', 'Password', 'P@ssw0rd', 'admin123', '111111', 'Pass@123',
    '123123', 'welcome', '1q2w3e4r', 'abc123', 'Admin@123', 'iloveyou', '000000', 'password1', 'qwerty1',
    'Abcd@1234', 'dragon', 'monkey', 'letmein', '1q2w3e4r5t', 'qwertyuiop', '********', 'secret',
    'password123', 'football', 'shadow', 'sunshine', 'princess', 'master', 'michael', 'ashley', 'charlie',
    '1qaz2wsx', 'asdfghjkl', 'zxcvbnm', '654321', '666666', 'superman', 'batman', 'India@123', 'trustno1',
    'hello', 'love', 'whatever', 'donald', 'liverpool', 'arsenal', 'chelsea', 'jordan', 'nicole', 'taylor',
    'access', 'thomas', 'buster', 'hockey', 'hunter', 'soccer', 'ranger', 'andrew', 'harley', 'tigger',
    'joshua', 'starwars', 'matthew', 'george', 'summer', 'friday', 'cheese', 'cookie', 'coffee', 'pepper',
    'guitar', 'chicken', 'ginger', 'maggie', 'jessica', 'jennifer', 'amanda', 'Robert', 'daniel', 'william',
    'maria', 'veronica', 'susana', 'skibidi', 'minecraft', 'Minecraft', 'fortnite', 'roblox', 'warcraft',
    'newmember', 'newuser', 'newpass', 'temppass', 'test', 'test123', 'guest', 'root', 'pass', 'passw0rd',
    'Password1', 'Password123', 'eminem', '50cent', 'metallica', 'slipknot', 'blink182', 'spiderman',
    'hellokitty', 'barbie', 'mario', 'joker', 'thor', 'elsa', '987654321', '147258369', '112233', '121212',
    '131313', '696969', '777777', '888888', '999999', 'aaaaaa', 'qqqqqq', 'london', 'manchester', 'password!',
    'qwerty!', '123456!', 'computer', 'internet', 'louvre', 'diamond', 'killer', 'yankees', 'lakers',
)


FIRE = doom_fire()  # the takeover's flames, kept between frames


def dumb_passwords():
    """A gag: the worst, most common passwords scrolling by. Purely a display, mocks weak passwords."""
    buf = collections.deque(maxlen=60)

    def step(w, h, ctx):
        if ctx["frame"] % 2 == 0:
            buf.append(random.choice(PASSWORDS))
        spin = "|/-\\"[ctx["frame"] % 4]
        lines = []
        shown = list(buf)[-h:]
        for i, pw in enumerate(shown):
            last = i == len(shown) - 1
            lines.append([(f" {spin if last else '>'} ", "dim"), (pw, "bold" if last else "dim")])
        return lines
    return step


def layout(h, w):
    """Grid of panes: our real stats top-left, the banner top-right, effects everywhere else."""
    cols, rows = (3, 3) if w < 180 else (4, 3)
    effects = itertools.cycle([
        ("typer", hacker_typer()), ("net", feed(net_line, 2)), ("donut", donut()),
        ("hexdump", feed(hex_line(), 3)), ("loading", loader()), ("cpu % (live)", cpu_graph),
        ("build", feed(build_line, 1)), ("claude", claude_clauding()), ("fire", doom_fire()),
        ("testing dumb password", dumb_passwords()),
    ])
    panes = []
    for i in range(cols * rows):
        r, c = divmod(i, cols)
        title, step = ("", real_jtop) if i == 0 else ("yes", banner) if i == cols - 1 else next(effects)
        x, y = c * (w // cols), r * (h // rows)
        pw = w // cols if c < cols - 1 else w - x
        ph = h // rows if r < rows - 1 else h - y
        panes.append((y, x, ph, pw, title, step))
    return panes


def fun(scr):
    styles = init_styles()
    styles.update(glow=styles["crit"] | curses.A_BOLD, ember=styles["crit"] | curses.A_DIM)  # skull's red glow
    scr.timeout(60)
    prev = sample()
    time.sleep(0.2)
    cur = sample()
    ctx = {"prev": prev, "cur": cur, "frame": 0, "history": [],
           "tab": 0, "scroll": 0, "show_all": False, "comps": components(),
           "takeover_start": None, "last_slot": int(time.monotonic()) // 300}
    last = cpu_times()["cpu"]
    size = panes = None
    while True:
        h, w = scr.getmaxyx()
        if (h, w) != size:
            size, panes = (h, w), layout(h, w)
        if time.monotonic() - ctx["cur"][0] >= 1:
            ctx["prev"], ctx["cur"] = ctx["cur"], sample()
        now = cpu_times()["cpu"]
        ctx["history"] = ctx["history"][-500:] + [100 * (now[0] - last[0]) / max(now[1] - last[1], 1)]
        last = now
        t = time.monotonic()
        if ctx["takeover_start"] is None and int(t) // 300 != ctx["last_slot"]:
            ctx["last_slot"], ctx["takeover_start"] = int(t) // 300, t  # takeover every 5 minutes
        scr.erase()
        if ctx["takeover_start"] is not None:
            elapsed = t - ctx["takeover_start"]
            if elapsed >= 4.0:
                ctx["takeover_start"] = None
            else:
                for i, line in enumerate(takeover_lines(w - 1, h, elapsed, ctx["frame"])[:h]):
                    try:
                        put_line(scr, i, 0, w - 1, line, styles)
                    except curses.error:
                        pass
                scr.refresh()
                ctx["frame"] += 1
                if scr.getch() == ord("q"):
                    break
                continue
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
        k = scr.getch()
        if k == ord("q"):
            break
        if k == ord("h"):  # trigger the hacked-skull takeover on demand (otherwise it fires every 5 minutes)
            ctx["takeover_start"] = time.monotonic()
        elif k == 9:  # Tab: cycle the real jtop pane
            ctx["tab"], ctx["scroll"] = (ctx["tab"] + 1) % len(TABS), 0
        elif k == ord("a") and ctx["tab"] == 2:
            ctx["show_all"] = not ctx["show_all"]
        elif k == curses.KEY_UP:
            ctx["scroll"] -= 1
        elif k == curses.KEY_DOWN:
            ctx["scroll"] += 1
        elif k == curses.KEY_PPAGE:
            ctx["scroll"] -= h
        elif k == curses.KEY_NPAGE:
            ctx["scroll"] += h


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
    ctx = {"prev": a, "cur": b, "frame": 0, "history": [10.0, 50.0, 100.0],
           "tab": 0, "scroll": 0, "show_all": False, "comps": components()}
    for h, w in ((24, 80), (40, 120), (60, 240)):  # every fun pane renders, a few frames each
        for frame in range(20):
            ctx["frame"] = frame
            ctx["tab"] = frame % len(TABS)  # cycle the real-jtop pane through all tabs
            for _, _, ph, pw, _, step in layout(h, w):
                step(pw - 2, ph - 2, ctx)
    assert any("█" in "".join(t for t, _ in l) for l in banner(38, 11, ctx)), "banner too big for a 3x3 pane"
    for el in (0.5, 2.0):  # corruption phase and skull phase both render for a few frames
        for frame in range(4):
            assert takeover_lines(80, 30, el, frame)
    for h, w in ((24, 80), (40, 160)):  # skull shows (clipped if the terminal is small), screen fully covered
        rows = takeover_lines(w, h, 2.0, 0)
        assert len(rows) == h and any("⣿" in t for l in rows for t, _ in l), "skull missing"
        assert any(t.strip() for t, _ in rows[-1]), "flames missing"
    print("ok")


if __name__ == "__main__":
    check() if "--check" in sys.argv else run()
