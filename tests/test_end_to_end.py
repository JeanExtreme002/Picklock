# -*- coding: utf-8 -*-

"""
Every command, driven from the typed line against a real process.

The target is the test process itself — the same trick PyMemoryEditor's own
suite uses, and the reason these run anywhere without privileges or a second
program to launch.

What is being tested is the *command*, not the library underneath it: that the
line parses, the address expression resolves, the type and width are worked
out, the right library call is made, and the table that comes back says what it
should. A test here fails when Picklock is wrong, not when PyMemoryEditor is.
"""

import ctypes
import os
import re

import pytest

#: A value unlikely to be lying around in a Python process, so a scan for it
#: finds the block below and little else.
MARKER = 0x5C0FFEE1

#: The scans walk a real address space, which takes about a second each. Run
#: the fast suite with `pytest -m "not slow"`.
slow = pytest.mark.slow


class Block:
    """A live chunk of this process's memory, with known contents.

    Held by a fixture for the duration of a test so the addresses stay valid —
    a ctypes buffer that goes out of scope is freed, and the scan would then be
    hunting a page that no longer exists.
    """

    def __init__(self) -> None:
        self.ints = (ctypes.c_int32 * 4)(MARKER, MARKER, 0, 0)
        self.text = ctypes.create_string_buffer(b"PicklockMarker42\x00")
        self.blob = (ctypes.c_ubyte * 8)(0xDE, 0xAD, 0xBE, 0xEF, 0xCA, 0xFE, 0xBA, 0xBE)
        # A pointer to the ints, so a chain has something real to walk.
        self.cell = (ctypes.c_void_p * 1)(ctypes.addressof(self.ints))

    @property
    def ints_at(self) -> int:
        return ctypes.addressof(self.ints)

    @property
    def text_at(self) -> int:
        return ctypes.addressof(self.text)

    @property
    def blob_at(self) -> int:
        return ctypes.addressof(self.blob)

    @property
    def cell_at(self) -> int:
        return ctypes.addressof(self.cell)


@pytest.fixture
def block() -> Block:
    return Block()


@pytest.fixture
def target(shell, capture):
    """A shell attached to this very process."""
    if not shell.run_line(f"ps:open {os.getpid()}"):
        pytest.skip(f"cannot open this process: {capture.err.strip()}")
    capture.reset()
    yield shell
    shell.run_line("ps:close")


def run(shell, capture, line: str) -> str:
    """Type one line and hand back what the user would have seen."""
    capture.reset()
    ok = shell.run_line(line)
    assert ok, f"{line!r} failed: {capture.err.strip()}"
    return capture.out


# -- ps ------------------------------------------------------------------


def test_ps_list_finds_this_process(target, capture):
    out = run(target, capture, f"ps:list {os.getpid()}")
    assert str(os.getpid()) in out


def test_ps_open_reports_what_it_attached_to(shell, capture):
    assert shell.run_line(f"ps:open {os.getpid()}")
    assert f"PID {os.getpid()}" in capture.out
    assert "64-bit" in capture.out or "32-bit" in capture.out
    shell.run_line("ps:close")


def test_ps_info_describes_the_target(target, capture):
    out = run(target, capture, "ps:info")
    assert str(os.getpid()) in out
    assert "Pointer size" in out
    assert "Regions" in out


def test_ps_close_detaches(target, capture):
    out = run(target, capture, "ps:close")
    assert "Detached" in out
    assert target.session.process is None
    target.run_line(f"ps:open {os.getpid()}")  # so the fixture can close it


# -- memory --------------------------------------------------------------


def test_memory_read_returns_what_is_there(target, capture, block):
    out = run(target, capture, f"memory:read 0x{block.ints_at:X} int32")
    assert str(MARKER) in out


def test_memory_read_counts_forward(target, capture, block):
    out = run(target, capture, f"memory:read 0x{block.ints_at:X} int32 --count 4")
    assert out.count(str(MARKER)) == 2, "the first two hold the marker"


def test_memory_read_in_hex(target, capture, block):
    out = run(target, capture, f"memory:read 0x{block.ints_at:X} int32 --hex")
    assert f"0x{MARKER:X}" in out


def test_memory_read_a_string(target, capture, block):
    out = run(target, capture, f"memory:read 0x{block.text_at:X} string 16")
    assert "PicklockMarker42" in out


def test_memory_read_bytes(target, capture, block):
    out = run(target, capture, f"memory:read 0x{block.blob_at:X} bytes 4")
    assert "DE AD BE EF" in out


def test_memory_write_changes_the_process(target, capture, block):
    run(target, capture, f"memory:write 0x{block.ints_at:X} int32 4242")
    assert block.ints[0] == 4242, "the write reached this process's memory"
    assert "4242" in run(target, capture, f"memory:read 0x{block.ints_at:X} int32")


def test_memory_write_a_string(target, capture, block):
    run(target, capture, f"memory:write 0x{block.text_at:X} string Picklock!")
    assert block.text.value.startswith(b"Picklock!")


def test_memory_write_bytes(target, capture, block):
    run(target, capture, f"memory:write 0x{block.blob_at:X} bytes '01 02 03 04'")
    assert list(block.blob[:4]) == [1, 2, 3, 4]


def test_memory_dump_shows_hex_and_ascii(target, capture, block):
    out = run(target, capture, f"memory:dump 0x{block.text_at:X} 16")
    assert "PicklockMarker42" in out, "the ASCII column"
    assert "50 69 63 6B" in out, "the hex column ('Pick')"


def test_memory_watch_samples_the_value(target, capture, block):
    out = run(
        target,
        capture,
        f"memory:watch 0x{block.ints_at:X} int32 --count 2 --interval 0.01 --all",
    )
    assert out.count(str(MARKER)) >= 2
    assert "2 sample(s)" in out


def test_memory_regions_lists_the_map(target, capture):
    out = run(target, capture, "memory:regions --limit 5")
    assert "PERMS" in out and "rw" in out


def test_memory_regions_finds_the_one_holding_an_address(target, capture, block):
    out = run(target, capture, f"memory:regions --at 0x{block.ints_at:X}")
    assert "1 row in set" in out


def test_memory_modules_lists_loaded_modules(target, capture):
    out = run(target, capture, "memory:modules --limit 5")
    assert "BASE" in out
    assert re.search(r"0x[0-9A-F]{8,}", out), "a real base address"


def test_memory_threads_lists_at_least_this_one(target, capture):
    out = run(target, capture, "memory:threads --limit 5")
    assert "TID" in out
    assert "Empty set" not in out


def test_a_module_name_resolves_in_an_address(target, capture):
    """'module+offset' has to reach the real base, not merely parse.

    The module is taken from the target's own list rather than guessed, so the
    test says the same thing on every platform.
    """
    run(target, capture, "memory:modules")  # refreshes the module table
    modules = target.session.modules()
    name, base = next(iter(sorted(modules.items())))

    out = run(target, capture, f"memory:read {name}+0 bytes 4")
    assert f"{base:016X}" in out.replace("0x", ""), "landed on the module base"


@pytest.mark.skipif(
    __import__("sys").platform.startswith("linux"),
    reason="Linux has no cross-process allocation syscall",
)
def test_memory_alloc_and_free_round_trip(target, capture):
    out = run(target, capture, "memory:alloc 4096")
    address = re.search(r"at (0x[0-9A-F]+)", out).group(1)

    run(target, capture, f"memory:write {address} int32 1234")
    assert "1234" in run(target, capture, f"memory:read {address} int32")

    assert "Freed" in run(target, capture, f"memory:free {address}")
    assert target.run_line(f"memory:read {address} int32") is False, "gone"


# -- scan ----------------------------------------------------------------


@slow
def test_scan_finds_the_marker(target, capture, block):
    out = run(target, capture, f"scan:value int32 {MARKER} --writable")
    assert "Empty set" not in out
    assert block.ints_at in target.session.scan.addresses


@slow
def test_scan_then_refine_by_value(target, capture, block):
    run(target, capture, f"scan:value int32 {MARKER} --writable")
    block.ints[0] = MARKER + 1
    block.ints[1] = MARKER + 1

    run(target, capture, f"scan:next {MARKER + 1}")
    assert block.ints_at in target.session.scan.addresses


@slow
def test_scan_then_refine_against_the_previous_reading(target, capture, block):
    """'--increased' with no value at all — the reason the flag exists."""
    run(target, capture, f"scan:value int32 {MARKER} --writable")
    before = len(target.session.scan)
    block.ints[0] = MARKER + 100
    block.ints[1] = MARKER - 100

    run(target, capture, "scan:next --increased")
    kept = target.session.scan.addresses
    assert block.ints_at in kept, "the one that grew survived"
    assert block.ints_at + 4 not in kept, "the one that shrank did not"
    # Not an exact list: this is a live interpreter, and other counters of its
    # own move between the two readings.
    assert len(kept) < before


@slow
def test_scan_a_string(target, capture, block):
    out = run(target, capture, "scan:value string PicklockMarker42 --max 20")
    assert "Empty set" not in out
    assert block.text_at in target.session.scan.addresses


@slow
def test_scan_a_range(target, capture, block):
    run(
        target,
        capture,
        f"scan:value int32 --between {MARKER - 1} {MARKER + 1} --writable --max 50",
    )
    assert block.ints_at in target.session.scan.addresses


@slow
def test_aob_finds_the_signature(target, capture, block):
    out = run(target, capture, 'scan:aob "DE AD BE EF ? ? BA BE" --max 20')
    assert "Empty set" not in out
    assert block.blob_at in target.session.scan.addresses


@slow
def test_regex_finds_the_text(target, capture, block):
    out = run(target, capture, 'scan:regex "PicklockMarker[0-9]+" --length 24 --max 20')
    assert "Empty set" not in out
    assert block.text_at in target.session.scan.addresses


@slow
def test_results_keep_drop_and_reset(target, capture, block):
    run(target, capture, f"scan:value int32 {MARKER} --writable")
    total = len(target.session.scan)
    assert total >= 2

    out = run(target, capture, "scan:results")
    assert "ADDRESS" in out and "PREVIOUS" in out

    row = target.session.scan.addresses.index(block.ints_at) + 1
    run(target, capture, f"scan:keep {row}")
    assert target.session.scan.addresses == [block.ints_at]

    run(target, capture, "scan:drop 1")
    assert target.session.scan.addresses == []

    assert "Discarded" in run(target, capture, "scan:reset")
    assert target.session.scan is None


@slow
def test_a_result_row_can_be_read_and_written_by_number(target, capture, block):
    """'#N' has to reach the address the scan found."""
    run(target, capture, f"scan:value int32 {MARKER} --writable")
    row = target.session.scan.addresses.index(block.ints_at) + 1

    assert str(MARKER) in run(target, capture, f"memory:read #{row} int32")
    run(target, capture, f"memory:write #{row} int32 7")
    assert block.ints[0] == 7


# -- pointer -------------------------------------------------------------


def test_deref_walks_a_chain(target, capture, block):
    out = run(target, capture, f"pointer:deref 0x{block.cell_at:X} 0")
    assert f"{block.ints_at:016X}" in out.replace("0x", "")


def test_pointer_read_and_write_through_a_chain(target, capture, block):
    out = run(target, capture, f"pointer:read 0x{block.cell_at:X} 0 --type int32")
    assert str(MARKER) in out

    run(target, capture, f"pointer:read 0x{block.cell_at:X} 0 --write 999")
    assert block.ints[0] == 999


def test_a_bracket_expression_dereferences(target, capture, block):
    """'[cell]' has to read the pointer and land on the ints."""
    out = run(target, capture, f"memory:read [0x{block.cell_at:X}] int32")
    assert str(MARKER) in out


@slow
def test_the_pointer_path_workflow(target, capture, block, tmp_path):
    """scan, save, load, rescan, diff — the whole file round trip."""
    out = run(target, capture, f"pointer:scan 0x{block.ints_at:X} --depth 2 --max 20")
    if not target.session.pointer_paths:
        pytest.skip("no static path reaches a ctypes buffer in this build")
    assert "BASE" in out

    first = tmp_path / "a.json"
    second = tmp_path / "b.json"
    assert "Saved" in run(target, capture, f"pointer:save {first}")
    run(target, capture, f"pointer:save {second}")

    run(target, capture, "pointer:paths")
    assert "OFFSETS" in capture.out

    assert "Loaded" in run(target, capture, f"pointer:load {first}")
    out = run(target, capture, f"pointer:rescan 0x{block.ints_at:X}")
    assert "still reach" in out

    out = run(target, capture, f"pointer:diff {first} {second}")
    assert "present in all 2 file(s)" in out


# -- the session commands, against a live target -------------------------


def test_an_alias_reaches_a_real_command(target, capture, block):
    run(target, capture, "alias:add r memory:read")
    out = run(target, capture, f"r 0x{block.ints_at:X} int32")
    assert str(MARKER) in out


def test_a_setting_changes_what_a_command_prints(target, capture, block):
    run(target, capture, "config:set hex on")
    out = run(target, capture, f"memory:read 0x{block.ints_at:X} int32")
    assert f"0x{MARKER:X}" in out


def test_a_script_of_commands_runs_against_the_target(target, capture, block, tmp_path):
    script = tmp_path / "setup.picklock"
    script.write_text(
        f"# a comment\nmemory:read 0x{block.ints_at:X} int32\nps:info\n"
    )
    out = run(target, capture, f"source {script}")
    assert str(MARKER) in out
    assert "Pointer size" in out
