#!/usr/bin/env python3
"""
Regenerate the terminal capture shown in the README.

This is a maintainer-only helper — it is intentionally kept out of the
published package (see the sdist excludes in ``pyproject.toml``).

Nothing in the image is typed by hand. The script drives the *real* shell
against a real process — itself, the same trick the end-to-end suite uses,
which is what lets it run anywhere without privileges and without a second
program to launch — and records exactly what a user would have seen, escape
codes included. The addresses, the row counts and the timings in the picture
are whatever that run produced.

So that the picture is not a screenshot of Picklock reading Python, the
recording runs under a hard link to this interpreter named ``game``: the
process really is called that, which is the name the kernel hands back and
the name the shell prints. It is staging, not faking — the same staging as
pointing a demo at a toy program written for the occasion, minus the program.
Where the link cannot be made or cannot run, the recording happens in this
process and the picture says ``python`` instead.

The scan it stages is real too: a value is planted in this process's memory,
scanned for across the writable regions, and the first address that comes
back is written to. Nothing is arranged so that the numbers agree — they
agree because the commands ran.

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
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

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

#: The name the recording runs under — the shape of thing people actually
#: point a memory scanner at, and the one the README's walkthrough uses. The
#: suffix is only a file name: the link is made and run wherever this script
#: runs, and the kernel reports the name it was given.
DEMO_NAME = "game.exe"

#: Passed to the renamed child to tell it where to leave the transcript.
RECORD_FLAG = "--record-to"

#: The value planted in this process for the scan to find. Arbitrary, and
#: ordinary enough in a live interpreter that the scan comes back with a few
#: hundred candidates — which is the honest picture: a first scan narrows the
#: field, it does not identify anything.
HEALTH = 1337


# -- the staged process ---------------------------------------------------


class Target:
    """Live memory in this process, with contents the demo can rely on.

    Held for the length of the run: a ctypes buffer that goes out of scope is
    freed, and the scan would then be hunting a page that no longer exists.
    """

    def __init__(self) -> None:
        self.health = (ctypes.c_int32 * 4)(HEALTH, HEALTH, 0, 0)
        self.name = ctypes.create_string_buffer(b"PicklockDemo\x00")

    @property
    def value(self) -> int:
        """What the demo scans for — read back from the memory it planted."""
        return int(self.health[0])


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

    # Attaching by name reads better than a bare PID, but only once the name
    # is worth reading; unrenamed, several interpreters may share it and the
    # match would be ambiguous.
    renamed = Path(sys.executable).name == DEMO_NAME
    open_by = f"ps:open {DEMO_NAME}" if renamed else f"ps:open {os.getpid()}"

    # Show a sample of the hits rather than a screenful. `limit` is one of the
    # settings Picklock persists, so a session inherits it rather than being
    # told it every time — which is why this is set here and not typed as a
    # `config:set` line in the demo. The scan is unaffected: the footer still
    # reports how many rows there really are.
    shell.session.set_option("limit", "3")

    #: (line, hook) — a hook runs *before* its line, for a step that needs the
    #: process to have changed by the time the command looks.
    script: List[Tuple[str, object]] = [
        (open_by, None),
        (f"scan:value int32 {target.value} --writable", None),
        ("memory:write #1 int32 9999", None),
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


def link_interpreter(directory: str) -> Optional[str]:
    """Return a path to this interpreter under :data:`DEMO_NAME`, or None.

    A hard link, so the bytes — and therefore the code signature macOS checks
    — are the ones already on disk; a copy only if the link cannot be made.
    """
    linked = os.path.join(directory, DEMO_NAME)
    try:
        os.link(sys.executable, linked)
    except OSError:
        try:
            shutil.copy2(sys.executable, linked)
        except OSError:
            return None
    return linked


def transcript() -> List[str]:
    """Record the demo, under the demo name where the platform allows it.

    The renamed interpreter is run as a child rather than exec'd into, so
    that a name that cannot be made to work — an interpreter that will not
    start from outside its own directory, most likely on Windows, where the
    runtime DLL sits next to the executable — costs a fallback rather than
    the whole run.
    """
    with tempfile.TemporaryDirectory(prefix="picklock-demo-") as directory:
        linked = link_interpreter(directory)
        if linked is None:
            print(f"Could not create an interpreter named {DEMO_NAME!r}.")
            return record()

        output = os.path.join(directory, "transcript.json")

        # The link has no directory of its own to find a standard library in,
        # and no site-packages; hand it this interpreter's.
        environment = dict(os.environ)
        environment["PYTHONHOME"] = sys.base_prefix
        environment["PYTHONPATH"] = os.pathsep.join(p for p in sys.path if p)

        result = subprocess.run(
            [linked, os.path.abspath(__file__), RECORD_FLAG, output],
            env=environment,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and os.path.exists(output):
            print(f"Recorded in a process named {DEMO_NAME!r}.")
            with open(output, encoding="utf-8") as handle:
                return json.load(handle)

        detail = (result.stderr or result.stdout).strip().splitlines()
        print(
            f"Could not record under the name {DEMO_NAME!r} "
            f"({detail[-1] if detail else f'exit {result.returncode}'}); "
            "recording in this process instead."
        )

    return record()


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

#: And never narrower than this, however short the lines get. A window that
#: hugs its longest line stops looking like a terminal and starts looking like
#: a quotation, and it also keeps the image from shrinking every time a
#: command is dropped from the demo.
MIN_COLUMNS = 84

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
        MIN_COLUMNS,
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
    parser.add_argument(
        RECORD_FLAG, metavar="FILE",
        help=argparse.SUPPRESS,  # internal: how the renamed child reports back
    )
    args = parser.parse_args()

    # The renamed child's whole job: run the demo and hand the lines back.
    if args.record_to:
        with open(args.record_to, "w", encoding="utf-8") as handle:
            json.dump(record(), handle)
        return

    page, width, height = build_page(transcript())

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
