# -*- coding: utf-8 -*-

"""User-defined aliases: creating them, using them, and refusing bad ones."""

import pathlib
import sys

import pytest

from peekmem import aliases as storage
from peekmem.commands.alias_commands import restore
from peekmem.errors import CommandError
from peekmem.session import Session


def test_an_alias_stands_for_a_command(shell, capture):
    shell.run_line("alias:add r memory:read")
    assert shell.session.aliases == {"r": ["memory:read"]}
    assert "r = memory:read" in capture.out


def test_an_alias_can_carry_arguments_of_its_own(shell):
    """'find-text Peekmem' has to run 'scan:value string Peekmem'."""
    shell.run_line("alias:add find-text scan:value string")
    word, args = shell.session.expand_alias("find-text", ["Peekmem"])
    assert (word, args) == ("scan:value", ["string", "Peekmem"])


def test_an_unknown_word_expands_to_itself(shell):
    assert shell.session.expand_alias("memory:read", ["0x10"]) == (
        "memory:read",
        ["0x10"],
    )


def test_using_an_alias_runs_the_command(shell, capture):
    """The whole point: it has to reach the real command, arguments and all."""
    shell.run_line("alias:add r memory:read")
    capture.reset()
    assert shell.run_line("r 0x10") is False  # no target attached
    assert "No process attached" in capture.err
    assert "memory:read" in capture.err, "the error names the real command"


def test_listing_is_empty_until_something_is_added(shell, capture):
    shell.run_line("alias:list")
    assert "No aliases" in capture.out


def test_listing_shows_what_each_stands_for(shell, capture):
    shell.run_line("alias:add r memory:read")
    shell.run_line("alias:add find-text scan:value string")
    capture.reset()
    shell.run_line("alias:list")
    assert "memory:read" in capture.out
    assert "scan:value string" in capture.out


def test_removing_forgets_it(shell, capture):
    shell.run_line("alias:add r memory:read")
    shell.run_line("alias:remove r")
    assert shell.session.aliases == {}
    assert "removed" in capture.out


def test_removing_something_that_is_not_an_alias_lists_the_real_ones(shell, capture):
    shell.run_line("alias:add r memory:read")
    assert shell.run_line("alias:remove nope") is False
    assert "No alias called 'nope'" in capture.err
    assert "r" in capture.err


@pytest.mark.parametrize(
    "name",
    [
        "memory",        # a command that takes subcommands
        "quit",          # a command's own shortcut
        "help",          # a top-level command
        "cls",           # another shortcut
    ],
)
def test_a_taken_name_is_refused(shell, name):
    """An alias must never shadow something that already answers to that word."""
    with pytest.raises(CommandError, match="already a command"):
        shell.run_line(f"alias:add {name} memory:read", raise_errors=True)


def test_an_existing_alias_is_not_silently_replaced(shell):
    shell.run_line("alias:add r memory:read")
    with pytest.raises(CommandError, match="already an alias"):
        shell.run_line("alias:add r memory:write", raise_errors=True)
    assert shell.session.aliases["r"] == ["memory:read"]


@pytest.mark.parametrize("name", ["mem:r", "a:b:c", "memory:read"])
def test_a_name_with_a_colon_is_refused(shell, name):
    """The colon is what the command hierarchy is built on.

    That covers 'memory:read' too: it is both taken and unspellable, and the
    shape of the name is the more useful thing to say about it.
    """
    with pytest.raises(CommandError, match="no ':' or spaces"):
        shell.run_line(f"alias:add {name} memory:read", raise_errors=True)


def test_a_name_that_looks_like_a_flag_is_refused(shell):
    with pytest.raises(CommandError, match="read as a flag"):
        shell.run_line("alias:add -- -x memory:read", raise_errors=True)


def test_the_target_has_to_exist(shell):
    """Caught now, while you still remember what you meant."""
    with pytest.raises(CommandError, match="not a command"):
        shell.run_line("alias:add r nosuch:command", raise_errors=True)


def test_an_alias_may_point_at_a_command_that_takes_subcommands(shell, capture):
    shell.run_line("alias:add m memory")
    capture.reset()
    shell.run_line("m")
    assert "memory subcommands:" in capture.out


def test_aliases_cannot_chain(shell):
    """One expansion always lands on a real command, by construction.

    An alias may only point at something the registry knows, so a second alias
    can never point at the first — which is what makes a single pass safe, with
    no cycle to detect.
    """
    shell.run_line("alias:add r memory:read")
    with pytest.raises(CommandError, match="not a command"):
        shell.run_line("alias:add rr r", raise_errors=True)


def test_help_answers_for_an_alias(shell, capture):
    shell.run_line("alias:add r memory:read")
    capture.reset()
    shell.run_line("help r")
    assert "r is an alias for 'memory:read'." in capture.out
    assert "Read a typed value from an address" in capture.out


def test_the_help_flag_works_through_an_alias(shell, capture):
    shell.run_line("alias:add r memory:read")
    capture.reset()
    shell.run_line("r --help")
    assert "memory:read — Read a typed value" in capture.out


def test_a_bare_session_touches_no_file(capture):
    """Loading is the shell's job, so a Session in a test or a script is inert."""
    assert Session(capture.printer).aliases == {}


def test_aliases_complete(shell):
    shell.run_line("alias:add find-text scan:value string")
    assert "find-text" in shell.session.aliases


# -- persistence ---------------------------------------------------------


def test_adding_writes_the_file(shell):
    shell.run_line("alias:add r memory:read")
    assert storage.load() == {"r": ["memory:read"]}


def test_removing_rewrites_the_file(shell):
    shell.run_line("alias:add r memory:read")
    shell.run_line("alias:add w memory:write")
    shell.run_line("alias:remove r")
    assert storage.load() == {"w": ["memory:write"]}


def test_a_new_session_gets_them_back(shell, capture):
    """The whole point: close the terminal, open it again, the name is there."""
    shell.run_line("alias:add find-text scan:value string")

    fresh = Session(capture.printer)
    assert restore(fresh) == []
    assert fresh.aliases == {"find-text": ["scan:value", "string"]}


def test_restoring_drops_an_alias_whose_command_is_gone(capture):
    """A command can be renamed between releases; the name should not linger."""
    storage.save({"ok": ["memory:read"], "stale": ["memory:teleport"]})

    session = Session(capture.printer)
    assert restore(session) == ["stale"]
    assert session.aliases == {"ok": ["memory:read"]}


def test_a_missing_file_is_the_ordinary_first_run(capture):
    session = Session(capture.printer)
    assert restore(session) == []
    assert session.aliases == {}


@pytest.mark.parametrize("content", ["not json at all", "[]", '{"r": 7}', '{"r": []}'])
def test_a_malformed_file_loses_the_aliases_but_not_the_shell(content, capture):
    """Refusing to start over a stray character would be the worse bug."""
    path = pathlib.Path(storage.path())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")

    session = Session(capture.printer)
    assert restore(session) == []
    assert session.aliases == {}


def test_a_hand_written_string_is_tolerated(capture):
    """Someone will edit this file by hand; accept the obvious spelling."""
    path = pathlib.Path(storage.path())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"f": "scan:value string"}', encoding="utf-8")

    session = Session(capture.printer)
    restore(session)
    assert session.aliases == {"f": ["scan:value", "string"]}


def test_a_write_failure_is_reported_but_not_fatal(shell, capture, monkeypatch):
    """A read-only home is a reason to say so, not to refuse the alias."""

    def refuse(_aliases):
        raise OSError("read-only file system")

    monkeypatch.setattr(storage, "save", refuse)
    shell.run_line("alias:add r memory:read")

    assert shell.session.aliases == {"r": ["memory:read"]}
    assert "Could not save" in capture.out
    assert "this session only" in capture.out


def test_the_file_is_replaced_atomically(shell):
    """An interrupted write must not leave a half-file for the next run."""
    shell.run_line("alias:add r memory:read")
    directory = pathlib.Path(storage.directory())
    assert [item.name for item in directory.iterdir()] == ["aliases.json"]


def test_the_location_follows_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv(storage.ENV_DIR, str(tmp_path / "explicit"))
    assert storage.directory() == str(tmp_path / "explicit")

    monkeypatch.delenv(storage.ENV_DIR)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    if sys.platform != "win32":
        assert storage.directory() == str(tmp_path / "xdg" / "peekmem")
