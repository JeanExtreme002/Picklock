# -*- coding: utf-8 -*-

"""User-defined aliases: creating them, using them, and refusing bad ones."""

import pytest

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


def test_aliases_belong_to_the_session(capture):
    """They die with the shell, like the settings — there is no config file."""
    assert Session(capture.printer).aliases == {}


def test_aliases_complete(shell):
    shell.run_line("alias:add find-text scan:value string")
    assert "find-text" in shell.session.aliases
