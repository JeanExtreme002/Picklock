#!/usr/bin/env python3
"""
Regenerate the terminal capture shown in the README.

This is a maintainer-only helper — it is intentionally kept out of the
published package (see the sdist excludes in ``pyproject.toml``).

Nothing in the image is typed by hand. The script drives the *real* shell
against a real process — this one, the same trick the end-to-end suite uses,
which is what lets it run anywhere without privileges and without a second
program to launch — and records exactly what a user would have seen, escape
codes included. The addresses, the row counts and the timings in the picture
are whatever that run produced.

The scan story it stages is real too: a value is planted in this process's
memory, scanned for, then *changed* between the two scans, so the
``--decreased`` refinement narrows a few hundred candidates to the one
address that actually moved. That is the loop the README describes, executed rather than
illustrated.

The transcript is then rendered as HTML and screenshotted with headless
Chrome, the same way ``build_preview.py`` does it in PyMemoryEditor.

Usage:
    pip install -e .
    python scripts/generate_terminal_image.py
    python scripts/generate_terminal_image.py --scale 1   # 1x instead of retina
    BROWSER=/path/to/chrome python scripts/generate_terminal_image.py
"""

import argparse
import ctypes
import html
import io
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT = REPO_ROOT / "assets" / "screenshots" / "terminal.png"

# Run against a throwaway configuration directory. Picklock persists aliases
# and settings, and a maintainer's own would otherwise leak into the picture —
# or worse, be written to by it. Set before the import so `store` never looks
# anywhere else.
_CONFIG_DIR = tempfile.TemporaryDirectory(prefix="picklock-screenshot-")
os.environ["PICKLOCK_CONFIG_DIR"] = _CONFIG_DIR.name

sys.path.insert(0, str(REPO_ROOT))

from picklock.shell import Shell  # noqa: E402  (must follow the env var above)

#: The value planted in this process, and what it drops to before the refine.
#: Both are arbitrary; what matters is that the second is smaller.
HEALTH = 1337
DAMAGED = 1200


# -- the staged process ---------------------------------------------------


class Target:
    """Live memory in this process, with contents the demo can rely on.

    Held for the length of the run: a ctypes buffer that goes out of scope is
    freed, and the scan would then be hunting a page that no longer exists.
    """

    def __init__(self) -> None:
        self.health = (ctypes.c_int32 * 4)(HEALTH, HEALTH, 0, 0)
        self.name = ctypes.create_string_buffer(b"PicklockDemo\x00")

    def take_damage(self) -> None:
        self.health[0] = DAMAGED


# -- recording ------------------------------------------------------------


def record() -> List[str]:
    """Run the demo and return the transcript, one line per element.

    Lines keep their escape codes: the renderer below turns those into colour,
    so what lands in the image is what the terminal would have drawn.
    """
    target = Target()
    buffer = io.StringIO()

    shell = Shell()
    shell.printer.stdout = buffer
    shell.printer.stderr = buffer
    shell.printer.color = True

    pid = os.getpid()

    #: (line, hook) — the hook runs *before* the line, so the process really
    #: has changed by the time the command that notices it runs. The display
    #: limit is turned down so the first scan's table stays a sample rather
    #: than twenty rows of the same number; the footer still reports the true
    #: total, and turning it down is itself a command worth showing.
    script: List[Tuple[str, object]] = [
        (f"ps:open {pid}", None),
        ("config:set limit 3", None),
        (f"scan:value int32 {HEALTH} --writable", None),
        ("scan:next --decreased", target.take_damage),
        ("memory:write #1 int32 9999", None),
        ("memory:hex #1 16", None),
    ]

    lines = shell.banner().rstrip("\n").split("\n")

    for line, hook in script:
        if hook is not None:
            hook()

        prompt = shell.prompt()
        buffer.seek(0)
        buffer.truncate()

        if not shell.run_line(line):
            sys.exit(f"the demo line {line!r} failed:\n{buffer.getvalue()}")

        lines.append("")
        lines.append(f"{prompt}{line}")
        lines.extend(buffer.getvalue().rstrip("\n").split("\n"))

    shell.run_line("ps:close")
    return lines


# -- rendering ------------------------------------------------------------

#: Only what Picklock actually emits: its one red, its one grey, and reset.
_CLASSES = {"31": "err", "38;5;247": "dim"}

_ANSI = re.compile(r"\033\[([0-9;]*)m")

#: readline's width-ignoring brackets. They never reach a screen; the prompt
#: only carries them when readline is driving input, which it is not here, but
#: strip them so a future change cannot put control characters in the picture.
_READLINE_MARKS = re.compile(r"[\001\002]")


def flatten(line: str) -> str:
    """Resolve a carriage return the way a terminal would: last write wins.

    The scan's progress line is drawn over itself with ``\r`` and then erased
    with blanks. On a screen only the final state is ever seen, and the image
    should show the same thing rather than every frame end to end.
    """
    return _READLINE_MARKS.sub("", line).split("\r")[-1]


def to_html(line: str) -> str:
    """Turn one recorded line into HTML, honouring its escape codes."""
    out: List[str] = []
    depth = 0
    position = 0

    for match in _ANSI.finditer(line):
        out.append(html.escape(line[position:match.start()]))
        position = match.end()

        code = match.group(1)
        if code in ("", "0"):
            out.append("</span>" * depth)
            depth = 0
        elif code in _CLASSES:
            out.append(f'<span class="{_CLASSES[code]}">')
            depth += 1

    out.append(html.escape(line[position:]))
    out.append("</span>" * depth)
    return "".join(out)


#: Menlo, SF Mono, Consolas, DejaVu Sans Mono and Liberation Mono all advance
#: very close to 0.602 em, so the window can be sized without asking the
#: browser to measure anything. Two columns of slack absorb the difference.
ADVANCE = 0.602
FONT_SIZE = 13.5
LINE_HEIGHT = 20
PAD_X, PAD_Y = 22, 18
TITLEBAR = 38
MARGIN = 26

#: How much wider than tall the finished picture should be. A capture that is
#: taller than it is wide swallows a README page, and a terminal is free to be
#: wider than its longest line — the width comes from the window, not from the
#: text — so the empty columns on the right are what a real one looks like.
#: Trim the demo rather than raising this if the transcript outgrows it.
ASPECT = 1.06

TEMPLATE = """<!doctype html>
<meta charset="utf-8">
<style>
  html, body {{ margin: 0; background: transparent; }}
  .window {{
    margin: {margin}px;
    width: {card_w}px;
    border-radius: 10px;
    overflow: hidden;
    background: #12141a;
    border: 1px solid rgba(255, 255, 255, 0.09);
    box-shadow: 0 18px 40px rgba(0, 0, 0, 0.45);
  }}
  .titlebar {{
    height: {titlebar}px;
    display: flex;
    align-items: center;
    padding: 0 14px;
    background: #1b1e26;
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  }}
  .dot {{
    width: 11px; height: 11px;
    border-radius: 50%;
    margin-right: 8px;
  }}
  .title {{
    flex: 1;
    text-align: center;
    margin-right: 57px;      /* balances the three dots */
    color: #838a95;
    font: 12px/1 -apple-system, "Segoe UI", system-ui, sans-serif;
  }}
  pre {{
    margin: 0;
    padding: {pad_y}px {pad_x}px;
    color: #dfe3e8;
    font: {font_size}px/{line_height}px "SF Mono", SFMono-Regular, ui-monospace,
          Menlo, Consolas, "DejaVu Sans Mono", "Liberation Mono", monospace;
    white-space: pre;
    overflow: hidden;
  }}
  .dim {{ color: #949aa4; }}
  .err {{ color: #ff6b6b; }}
</style>
<div class="window">
  <div class="titlebar">
    <div class="dot" style="background:#ff5f57"></div>
    <div class="dot" style="background:#febc2e"></div>
    <div class="dot" style="background:#28c840"></div>
    <div class="title">picklock</div>
  </div>
  <pre>{body}</pre>
</div>
"""


def build_page(lines: List[str]) -> Tuple[str, int, int]:
    """Return the HTML and the window size that fits it exactly."""
    lines = [flatten(line) for line in lines]
    widths = [len(_ANSI.sub("", line)) for line in lines]

    card_h = TITLEBAR + PAD_Y * 2 + len(lines) * LINE_HEIGHT
    character = FONT_SIZE * ADVANCE

    # Wide enough for the longest line, and for the aspect — whichever asks
    # for more.
    columns = max(
        max(widths) + 2,
        math.ceil((card_h * ASPECT - PAD_X * 2) / character),
    )
    card_w = round(columns * character) + PAD_X * 2

    page = TEMPLATE.format(
        margin=MARGIN,
        card_w=card_w,
        titlebar=TITLEBAR,
        pad_x=PAD_X,
        pad_y=PAD_Y,
        font_size=FONT_SIZE,
        line_height=LINE_HEIGHT,
        body="\n".join(to_html(line) for line in lines),
    )
    # +2 for the card's own border, which sits outside the declared width.
    return page, card_w + MARGIN * 2 + 2, card_h + MARGIN * 2 + 2


# -- the browser ----------------------------------------------------------

CANDIDATES = {
    "darwin": [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    ],
    "linux": [
        "google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
        "microsoft-edge", "microsoft-edge-stable",
    ],
    "win32": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ],
}


def find_browser() -> str:
    override = os.environ.get("BROWSER")
    if override:
        if Path(override).exists() or shutil.which(override):
            return override
        sys.exit(f"BROWSER={override!r} not found.")

    platform = "win32" if sys.platform.startswith("win") else \
               "darwin" if sys.platform == "darwin" else "linux"

    for candidate in CANDIDATES[platform]:
        if Path(candidate).exists() or shutil.which(candidate):
            return candidate

    for name in ("google-chrome", "chromium", "chrome", "msedge"):
        found = shutil.which(name)
        if found:
            return found

    sys.exit(
        "No Chrome/Chromium/Edge found. Install one, or set the BROWSER "
        "env var to its full path."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scale", type=int, default=2,
        help="device scale factor: 2 = retina (default), 1 = exact CSS pixels",
    )
    parser.add_argument(
        "--keep-html", action="store_true",
        help="leave the intermediate HTML next to the PNG, for tweaking the CSS",
    )
    args = parser.parse_args()

    page, width, height = build_page(record())

    OUT.parent.mkdir(parents=True, exist_ok=True)
    source = OUT.with_suffix(".html")
    source.write_text(page, encoding="utf-8")

    browser = find_browser()
    print(f"Using browser: {browser}")

    command = [
        browser,
        "--headless",
        "--disable-gpu",
        "--hide-scrollbars",
        f"--force-device-scale-factor={args.scale}",
        "--default-background-color=00000000",
        f"--window-size={width},{height}",
        f"--screenshot={OUT}",
        source.as_uri(),
    ]

    result = subprocess.run(command)
    if not args.keep_html:
        source.unlink()

    if result.returncode != 0 or not OUT.exists():
        sys.exit(f"Screenshot failed (exit {result.returncode}).")

    print(f"Wrote {OUT}  ({width * args.scale}x{height * args.scale})")


if __name__ == "__main__":
    main()
