# -*- coding: utf-8 -*-

"""
Everything Peekmem prints.

The house style is the ``mysql`` client's: results in an ASCII box table,
a footer line counting rows and timing the command, and nothing else. Colour
is limited to a single highlight on ``ERROR`` and is dropped entirely when the
stream is not a terminal, when ``NO_COLOR`` is set, or when ``--no-color`` was
passed — so piping Peekmem into ``grep`` or a log file yields plain text.

Keeping every byte of output behind this module is what makes the shell
testable: a test builds a :class:`Printer` over a ``StringIO`` and asserts on
the exact text a user would have seen.
"""

import os
import sys
import textwrap
import time
from typing import Any, Iterable, List, Optional, Sequence, TextIO, Tuple

#: Columns whose values are numbers are right-aligned, as in the mysql client.
RIGHT = "right"
LEFT = "left"

_RED = "\033[31m"
_RESET = "\033[0m"


def supports_color(stream: TextIO) -> bool:
    """True when it is polite to emit ANSI escapes on ``stream``."""
    if os.environ.get("NO_COLOR") is not None:
        return False
    if os.environ.get("TERM") == "dumb":
        return False
    return bool(getattr(stream, "isatty", lambda: False)())


def format_address(address: int, pointer_size: int = 8) -> str:
    """Render an address as fixed-width hex, e.g. ``0x00007FFEE3A01000``."""
    return "0x{:0{}X}".format(address, pointer_size * 2)


def format_size(size: int) -> str:
    """Render a byte count as a short human-readable string."""
    if size < 1024:
        return f"{size} B"
    value = float(size)
    for unit in ("KB", "MB", "GB", "TB"):
        value /= 1024.0
        if value < 1024.0:
            return f"{value:.1f} {unit}"
    return f"{value:.1f} PB"


def format_duration(seconds: float) -> str:
    """Render an elapsed time the way the mysql client does: ``0.01 sec``."""
    return f"{seconds:.2f} sec"


def _one_line(text: str) -> str:
    """Collapse a cell's text to a single line of printable characters."""
    return "".join(
        char if char == " " or char.isprintable() else "." for char in text
    )


def render_table(
    headers: Sequence[str],
    rows: Sequence[Sequence[Any]],
    aligns: Optional[Sequence[str]] = None,
) -> str:
    """Build a mysql-style box table.

    ``rows`` cells are stringified with ``str`` and truncated by nothing —
    a long path is printed in full and the terminal wraps it, which beats
    silently hiding the part that mattered.
    """
    # A cell carrying a newline or a tab would break the box open, and cells
    # can hold text read straight out of another process's memory. Flatten
    # them here so no caller has to remember to.
    text_rows: List[List[str]] = [
        ["" if cell is None else _one_line(str(cell)) for cell in row] for row in rows
    ]
    widths = [len(str(header)) for header in headers]
    for row in text_rows:
        for index, cell in enumerate(row):
            if index < len(widths):
                widths[index] = max(widths[index], len(cell))

    if aligns is None:
        aligns = [LEFT] * len(headers)

    rule = "+" + "+".join("-" * (width + 2) for width in widths) + "+"

    def line(cells: Sequence[str], pad_align: Sequence[str]) -> str:
        parts = []
        for index, cell in enumerate(cells):
            width = widths[index]
            if pad_align[index] == RIGHT:
                parts.append(" " + cell.rjust(width) + " ")
            else:
                parts.append(" " + cell.ljust(width) + " ")
        return "|" + "|".join(parts) + "|"

    out = [rule, line([str(header) for header in headers], [LEFT] * len(headers)), rule]
    out.extend(line(row, aligns) for row in text_rows)
    out.append(rule)
    return "\n".join(out)


def render_vertical(pairs: Iterable[Tuple[str, Any]]) -> str:
    """Render key/value pairs as an aligned two-column block (``\\G`` style)."""
    items = [(str(key), "" if value is None else str(value)) for key, value in pairs]
    if not items:
        return ""
    width = max(len(key) for key, _ in items)
    return "\n".join(f"{key.rjust(width)}: {value}" for key, value in items)


def render_paragraphs(text: str, width: int = 78) -> str:
    """Wrap prose to ``width``, leaving hand-laid-out blocks alone.

    A command's long description is written as ordinary paragraphs, which
    should reflow; but some of them contain small aligned tables (the list of
    'next' comparisons, say) whose whole value is the alignment. A paragraph
    with an indented line is taken to be one of those and is printed verbatim.
    """
    blocks = []
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        if any(line.startswith(("  ", "\t")) for line in block.splitlines()):
            blocks.append(block)
        else:
            blocks.append(textwrap.fill(" ".join(block.split()), width))
    return "\n\n".join(blocks)


def render_definitions(
    items: Sequence[Tuple[str, str]],
    *,
    indent: int = 2,
    label_width: int = 22,
    total_width: int = 78,
) -> str:
    """Render label/description pairs as an aligned, wrapped block.

    This is the shape ``help`` uses for a command's arguments — the layout
    every command-line tool's ``--help`` has, so it needs no explaining. A
    label longer than ``label_width`` takes a line of its own rather than
    pushing every description out of alignment.
    """
    if not items:
        return ""

    width = min(max(len(label) for label, _ in items), label_width)
    pad = " " * indent
    continuation = pad + " " * (width + 2)
    text_width = max(24, total_width - len(continuation))
    lines: List[str] = []

    for label, description in items:
        wrapped = textwrap.wrap(description, text_width) if description else []
        if not wrapped:
            lines.append(pad + label)
            continue
        if len(label) <= width:
            lines.append(f"{pad}{label.ljust(width)}  {wrapped[0]}")
        else:
            lines.append(pad + label)
            lines.append(continuation + wrapped[0])
        lines.extend(continuation + extra for extra in wrapped[1:])

    return "\n".join(lines)


def render_hexdump(data: bytes, base_address: int = 0, width: int = 16) -> str:
    """Classic ``hexdump -C`` layout: address, hex bytes, printable ASCII."""
    lines = []
    for offset in range(0, len(data), width):
        chunk = data[offset : offset + width]
        hex_part = " ".join(f"{byte:02X}" for byte in chunk)
        hex_part = hex_part.ljust(width * 3 - 1)
        ascii_part = "".join(
            chr(byte) if 32 <= byte < 127 else "." for byte in chunk
        )
        lines.append(
            f"{base_address + offset:016X}  {hex_part}  |{ascii_part}|"
        )
    return "\n".join(lines)


class Printer:
    """The single writer every command prints through.

    :param stdout: stream for results.
    :param stderr: stream for errors and for the transient progress line.
    :param color: ``None`` auto-detects from ``stdout``; ``True``/``False``
        force it.
    :param timing: print the mysql-style ``N rows in set (0.01 sec)`` footer.
    """

    def __init__(
        self,
        stdout: Optional[TextIO] = None,
        stderr: Optional[TextIO] = None,
        *,
        color: Optional[bool] = None,
        timing: bool = True,
    ):
        self.stdout = stdout if stdout is not None else sys.stdout
        self.stderr = stderr if stderr is not None else sys.stderr
        self.color = supports_color(self.stdout) if color is None else color
        self.timing = timing
        self._progress_active = False

    # -- primitives ------------------------------------------------------

    def write(self, text: str = "") -> None:
        self.clear_progress()
        self.stdout.write(text + "\n")
        self.stdout.flush()

    def error(self, message: str) -> None:
        """Print a failed command's message. Goes to stderr, like mysql's."""
        self.clear_progress()
        prefix = f"{_RED}ERROR{_RESET}" if self.color else "ERROR"
        self.stderr.write(f"{prefix}: {message}\n")
        self.stderr.flush()

    def clear_screen(self) -> bool:
        """Wipe the terminal. False when there is no terminal to wipe.

        A no-op when stdout is redirected: clearing is a courtesy to a human
        looking at a screen, and emitting escape codes into a pipe or a log
        file would be vandalism rather than tidying.
        """
        self.clear_progress()
        if not getattr(self.stdout, "isatty", lambda: False)():
            return False

        if sys.platform == "win32":  # pragma: no cover - Windows only
            # Not every Windows console has VT processing enabled, so the
            # escape sequence below cannot be relied on. `cls` always works.
            os.system("cls")
        else:
            # 2J wipes the screen, 3J the scrollback (so the shell matches what
            # `clear` does), H parks the cursor at the top.
            self.stdout.write("\033[2J\033[3J\033[H")
            self.stdout.flush()
        return True

    def note(self, message: str) -> None:
        """Print an aside — a warning that did not stop the command."""
        self.clear_progress()
        self.stdout.write(f"Note: {message}\n")
        self.stdout.flush()

    # -- results ---------------------------------------------------------

    def table(
        self,
        headers: Sequence[str],
        rows: Sequence[Sequence[Any]],
        aligns: Optional[Sequence[str]] = None,
        *,
        elapsed: Optional[float] = None,
        total: Optional[int] = None,
    ) -> None:
        """Print a result table plus its footer.

        ``total`` names the number of rows that *matched* when ``rows`` only
        carries the ones that fit the display limit, so the footer can say
        ``20 rows in set (of 1043)`` instead of pretending the rest do not
        exist.
        """
        self.clear_progress()
        if rows:
            self.write(render_table(headers, rows, aligns))
        self.footer(len(rows), elapsed=elapsed, total=total)

    def footer(
        self,
        count: int,
        *,
        elapsed: Optional[float] = None,
        total: Optional[int] = None,
    ) -> None:
        """Print the ``N rows in set (0.01 sec)`` line."""
        if count == 0 and not total:
            text = "Empty set"
        elif total is not None and total != count:
            # The table was cut to the display limit; say so plainly rather
            # than reporting a row count that is not the answer to the query.
            text = f"Showing {count} of {total} rows"
        else:
            text = f"{count} row{'' if count == 1 else 's'} in set"
        if self.timing and elapsed is not None:
            text += f" ({format_duration(elapsed)})"
        self.write(text)
        self.write()

    def ok(self, message: str, *, elapsed: Optional[float] = None) -> None:
        """Print the acknowledgement of a command that changed something."""
        if self.timing and elapsed is not None:
            message = f"{message} ({format_duration(elapsed)})"
        self.write(message)

    # -- progress --------------------------------------------------------

    def progress(self, label: str, fraction: float) -> None:
        """Update the in-place progress line on stderr.

        Scans walk gigabytes and a silent terminal looks like a hang. The line
        is written to stderr so a piped ``peekmem -e "scan ..."`` still yields
        clean, parseable stdout, and is skipped entirely when stderr is not a
        terminal so a log file does not fill with carriage returns.
        """
        if not getattr(self.stderr, "isatty", lambda: False)():
            return
        percent = max(0.0, min(1.0, fraction)) * 100.0
        self.stderr.write(f"\r{label} {percent:5.1f}%")
        self.stderr.flush()
        self._progress_active = True

    def clear_progress(self) -> None:
        """Erase the progress line, if one is showing."""
        if not self._progress_active:
            return
        self.stderr.write("\r\033[K" if self.color else "\r" + " " * 40 + "\r")
        self.stderr.flush()
        self._progress_active = False


class Timer:
    """Context manager measuring a command, for the mysql-style footer."""

    def __init__(self) -> None:
        self.elapsed = 0.0
        self._start = 0.0

    def __enter__(self) -> "Timer":
        self._start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.elapsed = time.perf_counter() - self._start


__all__ = (
    "LEFT",
    "Printer",
    "RIGHT",
    "Timer",
    "format_address",
    "format_duration",
    "format_size",
    "render_definitions",
    "render_hexdump",
    "render_paragraphs",
    "render_table",
    "render_vertical",
    "supports_color",
)
