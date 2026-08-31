# -*- coding: utf-8 -*-

"""Table, hexdump and footer rendering."""

import os
import sys

import pytest

from picklock.output import (
    LEFT,
    RIGHT,
    wait_for_enter,
    render_definitions,
    format_address,
    format_size,
    render_hexdump,
    render_table,
    render_vertical,
)


def test_table_is_a_closed_box_with_aligned_columns():
    text = render_table(("PID", "NAME"), [(7, "init"), (4242, "a")], (RIGHT, LEFT))
    lines = text.splitlines()
    assert lines[0] == lines[2] == lines[-1]
    assert set(len(line) for line in lines) == {len(lines[0])}
    assert "|    7 | init |" in text


def test_table_cells_never_break_the_box():
    """A value read out of another process can contain anything at all."""
    text = render_table(("V",), [("a\nb\tc",)], (LEFT,))
    assert len(text.splitlines()) == 5
    assert "a.b.c" in text


def test_footer_counts_rows_and_says_when_it_is_showing_fewer(capture):
    printer = capture.printer
    printer.footer(3)
    printer.footer(0)
    printer.footer(3, total=90)
    lines = [line for line in capture.out.splitlines() if line]
    assert lines == ["3 rows in set", "Empty set", "Showing 3 of 90 rows"]


def test_footer_carries_a_marker_before_the_timing(capture):
    """A caveat about the result set travels with the count line."""
    capture.printer.timing = True
    capture.printer.footer(3, total=90, marker="writable regions only")
    assert "Showing 3 of 90 rows — writable regions only" in capture.out


def test_an_empty_result_set_still_carries_its_marker(capture):
    """"Nothing found" and "nothing found *there*" are different answers."""
    capture.printer.footer(0, marker="writable regions only")
    assert "Empty set — writable regions only" in capture.out


def test_footer_reports_one_row_in_the_singular(capture):
    capture.printer.footer(1)
    assert "1 row in set" in capture.out


def test_timing_is_printed_only_when_enabled(capture):
    capture.printer.timing = True
    capture.printer.footer(1, elapsed=0.125)
    assert "(0.12 sec)" in capture.out


def test_errors_go_to_stderr(capture):
    capture.printer.error("boom")
    assert capture.err.strip() == "ERROR: boom"
    assert capture.out == ""


def test_hexdump_layout():
    text = render_hexdump(b"AB\x00\xff", 0x1000, width=4)
    assert text == "0000000000001000  41 42 00 FF  |AB..|"


def test_addresses_are_padded_to_the_pointer_width():
    assert format_address(0x1000, 8) == "0x0000000000001000"
    assert format_address(0x1000, 4) == "0x00001000"


def test_sizes_are_human_readable():
    assert format_size(512) == "512 B"
    assert format_size(2048) == "2.0 KB"


def test_vertical_block_aligns_the_keys():
    text = render_vertical([("PID", 1), ("Name", "init")])
    assert text == " PID: 1\nName: init"


def test_clear_screen_is_a_no_op_without_a_terminal(capture):
    """Escape codes in a pipe or a log file are vandalism, not tidying."""
    assert capture.printer.clear_screen() is False
    assert capture.out == ""


def test_clear_screen_wipes_screen_and_scrollback(capture, monkeypatch):
    capture.printer.stdout.isatty = lambda: True  # type: ignore[method-assign]

    if sys.platform == "win32":
        # Not every Windows console has VT processing enabled, so the printer
        # shells out to `cls` rather than writing escapes nothing may read.
        ran = []
        monkeypatch.setattr(os, "system", lambda command: ran.append(command))
        assert capture.printer.clear_screen() is True
        assert ran == ["cls"]
        assert capture.out == ""
        return

    assert capture.printer.clear_screen() is True
    # 2J the screen, 3J the scrollback, H the cursor — what `clear` itself does.
    assert capture.out == "\033[2J\033[3J\033[H"


def test_progress_is_silent_when_stderr_is_not_a_terminal(capture):
    capture.printer.progress("Scanning", 0.5)
    assert capture.err == ""


def test_dim_is_a_no_op_when_colour_is_off(capture):
    assert capture.printer.dim("[game.exe:42]") == "[game.exe:42]"


def test_dim_uses_an_explicit_shade(capture):
    """Explicit, so it never lands on the terminal's own default foreground."""
    capture.printer.color = True
    assert capture.printer.dim("x") == "\033[38;5;247mx\033[0m"


def test_dim_brackets_its_escapes_for_readline(capture):
    """Unbracketed escapes make readline miscount the prompt and misplace the
    cursor as soon as the line wraps."""
    capture.printer.color = True
    styled = capture.printer.dim("x", in_prompt=True)
    assert styled == "\001\033[38;5;247m\002x\001\033[0m\002"
    # Every escape sits inside a pair of markers.
    assert styled.count("\001") == styled.count("\002") == 2


def test_dim_leaves_empty_text_alone(capture):
    capture.printer.color = True
    assert capture.printer.dim("") == ""


def test_definitions_default_to_a_two_space_gap(capture):
    text = render_definitions([("name", "what it does")])
    assert text == "  name  what it does"


def test_the_gap_widens_both_the_first_line_and_the_wrapping(capture):
    """A wider gap has to move the continuation indent too, or the wrapped
    lines stop lining up under the first."""
    text = render_definitions(
        [("name", "a description long enough that it has to wrap somewhere")],
        gap=4,
        total_width=40,
    )
    first, second = text.splitlines()
    assert first.startswith("  name    a description")
    # The continuation sits under the description, not under the label.
    assert second.index(second.strip()[0]) == first.index("a description")


def test_waiting_for_enter_just_sleeps_without_a_terminal():
    """A pipe is at end-of-file the moment it is polled; that is not a keypress."""
    import io
    import time

    stream = io.StringIO()
    started = time.monotonic()
    assert wait_for_enter(stream, 0.05) is False
    assert time.monotonic() - started >= 0.04, "it waited rather than returning at once"


@pytest.mark.skipif(
    sys.platform == "win32",
    reason=(
        "on Windows wait_for_enter polls the console through msvcrt, which a "
        "pipe cannot stand in for — there is no file descriptor to write to"
    ),
)
def test_waiting_for_enter_sees_a_keypress():
    """A real file descriptor, pretending to be a terminal."""

    read_fd, write_fd = os.pipe()
    reader = os.fdopen(read_fd)
    try:
        reader.isatty = lambda: True  # type: ignore[method-assign]
        os.write(write_fd, b"\n")
        assert wait_for_enter(reader, 1.0) is True
    finally:
        reader.close()
        os.close(write_fd)


def test_waiting_for_enter_times_out_with_no_keypress():
    import os

    read_fd, write_fd = os.pipe()
    reader = os.fdopen(read_fd)
    try:
        reader.isatty = lambda: True  # type: ignore[method-assign]
        assert wait_for_enter(reader, 0.05) is False
    finally:
        reader.close()
        os.close(write_fd)
