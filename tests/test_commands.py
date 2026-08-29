# -*- coding: utf-8 -*-

"""Properties every command must hold, and the ones that need no target."""

import pytest

from peekmem.commands import GROUPS, all_commands, command_words, lookup
from peekmem.errors import CommandError, NoProcessError


COMMANDS = all_commands()


@pytest.mark.parametrize("entry", COMMANDS, ids=lambda entry: entry.name)
def test_every_command_is_documented(entry):
    assert entry.summary and entry.summary[0].isupper() and entry.summary.endswith(".")
    assert entry.usage.startswith(entry.name)
    assert entry.group in GROUPS


@pytest.mark.parametrize("entry", COMMANDS, ids=lambda entry: entry.name)
def test_every_command_has_help(entry, shell, capture):
    """'help <name>' must work for every command, alias included."""
    shell.run_line(f"help {entry.name}")
    assert entry.summary in capture.out
    for alias in entry.aliases:
        assert lookup(alias).name == entry.name


def test_command_words_are_unique():
    words = command_words()
    assert len(words) == len(set(words))


@pytest.mark.parametrize("entry", COMMANDS, ids=lambda entry: entry.name)
def test_examples_parse_as_commands(entry, shell):
    """A documented example that cannot even be split is a broken example."""
    for example in entry.examples:
        parsed = shell.split(example)
        assert parsed is not None
        assert lookup(parsed[0]).name == entry.name


@pytest.mark.parametrize(
    "line",
    [
        "read 0x10",
        "write 0x10 int32 1",
        "dump 0x10",
        "regions",
        "modules",
        "threads",
        "scan int32 1",
        "aob 'DE AD'",
        "regex abc",
        "deref 0x10",
        "pointer 0x10",
        "ptrscan 0x10",
        "alloc 16",
        "free 0x10",
        "watch 0x10",
        "info",
    ],
)
def test_commands_needing_a_target_refuse_without_one(shell, line):
    with pytest.raises(NoProcessError):
        shell.run_line(line, raise_errors=True)


@pytest.mark.parametrize(
    "line",
    ["next 1", "results", "keep 1", "drop 1", "paths", "ptrsave out.json"],
)
def test_commands_needing_results_refuse_without_them(shell, line):
    with pytest.raises(CommandError):
        shell.run_line(line, raise_errors=True)


def test_close_without_a_target_is_an_error(shell):
    with pytest.raises(CommandError):
        shell.run_line("close", raise_errors=True)


def test_status_works_with_no_target(shell, capture):
    shell.run_line("status")
    assert "(none attached)" in capture.out


def test_ps_lists_this_process(shell, capture):
    """The one command that talks to the OS without attaching to anything."""
    import os

    shell.run_line("set limit 0")
    shell.run_line("ps")
    assert str(os.getpid()) in capture.out


def test_set_prints_booleans_the_way_they_are_typed(shell, capture):
    shell.run_line("set")
    assert "| off" in capture.out or "off " in capture.out
    capture.reset()
    shell.run_line("set hex on")
    assert "hex = on" in capture.out


def test_set_accepts_the_equals_form(shell):
    shell.run_line("set limit=42")
    assert shell.session.option("limit") == 42


def test_unknown_option_is_reported_not_swallowed(shell):
    with pytest.raises(CommandError):
        shell.run_line("ps --nosuchflag", raise_errors=True)


def test_reset_reports_what_it_discarded(shell, capture):
    from peekmem import valuetypes

    shell.session.store_scan(valuetypes.resolve("int32"), 4, [1, 2], [0, 0], "t")
    shell.run_line("reset")
    assert "Discarded 2 result(s)." in capture.out
    assert shell.session.scan is None
