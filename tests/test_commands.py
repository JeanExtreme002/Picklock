# -*- coding: utf-8 -*-

"""Properties every command must hold, and the ones that need no target."""

import pytest

from peekmem.commands import (
    NAMESPACES,
    all_commands,
    children,
    command_words,
    describe_action,
    lookup,
    namespaces,
    top_level,
)
from peekmem.errors import CommandError, NoProcessError


COMMANDS = all_commands()


@pytest.mark.parametrize("entry", COMMANDS, ids=lambda entry: entry.name)
def test_every_command_is_documented(entry):
    assert entry.summary and entry.summary[0].isupper() and entry.summary.endswith(".")
    assert entry.usage.startswith(entry.name)
    assert entry.is_top_level or entry.namespace in namespaces()


@pytest.mark.parametrize("entry", COMMANDS, ids=lambda entry: entry.name)
def test_every_command_is_placed(entry):
    """Either in a declared namespace, or deliberately top-level."""
    if entry.is_top_level:
        assert ":" not in entry.name
    else:
        assert entry.namespace in namespaces()


def test_only_shell_commands_are_top_level():
    """Anything that touches the target belongs to a subject namespace."""
    assert sorted(entry.name for entry in top_level()) == [
        "clear",
        "exit",
        "help",
        "set",
        "source",
        "status",
        "version",
    ]


@pytest.mark.parametrize("namespace", [name for name, _, _ in NAMESPACES])
def test_a_bare_namespace_lists_it(shell, capture, namespace):
    """Including 'scan' and 'pointer', which are command aliases as well."""
    shell.run_line(namespace)
    assert f"Commands under '{namespace}:'" in capture.out
    assert capture.err == ""


@pytest.mark.parametrize("line", ["scan int32 100", "pointer 0x10"])
def test_an_alias_that_shadows_a_namespace_still_runs_with_arguments(shell, line):
    """The listing rule applies to the bare word only; the command is intact."""
    with pytest.raises(NoProcessError):
        shell.run_line(line, raise_errors=True)


def test_clear_leaves_the_session_alone(shell, capture):
    """It wipes the screen, not the work: a cleared terminal is not a reset."""
    from peekmem import valuetypes

    shell.session.store_scan(valuetypes.resolve("int32"), 4, [0x10], [1], "t")
    shell.run_line("clear")
    assert shell.session.scan is not None
    assert capture.err == ""


@pytest.mark.parametrize("entry", COMMANDS, ids=lambda entry: entry.name)
def test_every_command_keeps_a_short_alias(entry):
    """The hierarchy must cost nothing at the keyboard.

    Every command has to stay reachable by a plain word — 'read', not
    'memory:read' — or the namespacing would have made the shell worse to use.
    """
    assert entry.short, f"{entry.name} has no plain-word alias"
    assert lookup(entry.short).name == entry.name


@pytest.mark.parametrize("entry", COMMANDS, ids=lambda entry: entry.name)
def test_a_parent_name_is_a_prefix_of_its_children(entry):
    for child in children(entry.name):
        assert child.name.startswith(entry.name + ":")
        assert child.namespace == entry.namespace


def test_namespaces_are_listed_in_the_declared_order():
    order = [name for name, _, _ in NAMESPACES]
    seen = [entry.namespace for entry in COMMANDS if not entry.is_top_level]
    positions = [order.index(name) for name in seen]
    assert positions == sorted(positions)


def test_top_level_commands_sort_last():
    """help prints the subjects first, then the words that drive the shell."""
    names = [entry.is_top_level for entry in all_commands()]
    assert names == sorted(names), "a namespaced command came after a top-level one"


def test_children_are_one_level_deep():
    """The layering depends on this: a listing shows a screen, not a tree."""
    names = [entry.name for entry in children("scan")]
    assert "scan:results" in names
    assert "scan:results:keep" not in names
    assert [entry.name for entry in children("scan:results")] == [
        "scan:results:clear",
        "scan:results:drop",
        "scan:results:keep",
    ]


def test_the_overview_shows_layers_not_every_command(shell, capture):
    shell.run_line("help")
    out = capture.out
    for namespace in namespaces():
        assert namespace in out
    for entry in top_level():
        assert entry.name in out
    # The point of the layering: the forty-odd namespaced commands are not
    # listed here, only pointed at. Checked line-first, because the prose does
    # name one of them as an example of the alias rule.
    listed = {line.strip().split()[0] for line in out.splitlines() if line.startswith("  ")}
    assert not any(":" in item for item in listed), f"a namespaced command is listed: {listed}"
    assert "<name>:help" in out


@pytest.mark.parametrize("namespace", [name for name, _, _ in NAMESPACES])
def test_namespace_help_lists_that_layer(shell, capture, namespace):
    shell.run_line(f"{namespace}:help")
    assert f"Commands under '{namespace}:'" in capture.out
    for entry in children(namespace):
        assert entry.name in capture.out
    assert capture.err == ""


def test_a_deeper_help_lists_the_third_layer(shell, capture):
    shell.run_line("scan:results:help")
    assert "Commands under 'scan:results:'" in capture.out
    assert "scan:results:keep" in capture.out


def test_a_listing_points_at_the_layer_below_it(shell, capture):
    shell.run_line("scan:help")
    assert "scan:results" in capture.out
    assert "scan:results:keep" not in capture.out, "that is the next layer down"
    assert "type 'scan:results:help'" in capture.out


@pytest.mark.parametrize("namespace", [name for name, _, _ in NAMESPACES])
def test_every_namespace_has_commands(namespace):
    assert children(namespace), f"namespace {namespace!r} is empty"


def test_typing_a_namespace_lists_it(shell, capture):
    shell.run_line("memory")
    assert "Commands under 'memory:'" in capture.out
    assert "memory:read" in capture.out
    assert capture.err == ""


def test_a_namespace_with_arguments_points_at_the_colon(shell, capture):
    """'memory read 0x10' is the likely typo; name the fix precisely."""
    assert shell.run_line("memory read 0x10") is False
    assert "'memory:read'" in capture.err


def test_a_namespace_with_nonsense_arguments_is_still_explained(shell, capture):
    assert shell.run_line("memory nonsense") is False
    assert "namespace" in capture.err
    assert "help memory" in capture.err


def test_help_on_a_namespace_lists_it(shell, capture):
    shell.run_line("help memory")
    assert "memory:read" in capture.out


def test_a_namespace_shadowed_by_an_alias_still_announces_itself(shell, capture):
    """'pointer' is both an alias and a namespace; the alias wins, loudly."""
    shell.run_line("help pointer")
    assert "pointer:read" in capture.out, "the alias resolves to the command"
    assert "is also a namespace" in capture.out


@pytest.mark.parametrize("topic", ["pointer:", "scan:", "memory:"])
def test_a_trailing_colon_asks_for_the_namespace(shell, capture, topic):
    shell.run_line(f"help {topic}")
    assert f"Commands under '{topic.rstrip(':')}:'" in capture.out


def test_help_on_a_parent_command_lists_its_subcommands(shell, capture):
    shell.run_line("help scan:results")
    assert "Subcommands:" in capture.out
    assert "scan:results:keep" in capture.out


@pytest.mark.parametrize("entry", COMMANDS, ids=lambda entry: entry.name)
def test_every_command_has_help(entry, shell, capture):
    """'help <name>' must work for every command, alias included."""
    shell.run_line(f"help {entry.name}")
    assert entry.summary in capture.out
    for alias in entry.aliases:
        assert lookup(alias).name == entry.name


@pytest.mark.parametrize("entry", COMMANDS, ids=lambda entry: entry.name)
def test_every_command_declares_a_parser(entry):
    """Without one, 'help' cannot list what the command accepts."""
    assert entry.parser is not None
    assert entry.parser().prog == entry.name


@pytest.mark.parametrize("entry", COMMANDS, ids=lambda entry: entry.name)
def test_every_argument_is_documented(entry):
    """An undocumented flag is a flag nobody can discover."""
    for action in entry.arguments():
        label = describe_action(action)
        assert action.help, f"{entry.name}: {label} has no help text"


@pytest.mark.parametrize("entry", COMMANDS, ids=lambda entry: entry.name)
def test_help_lists_every_flag(entry, shell, capture):
    """Each option a command accepts must appear in its help output."""
    shell.run_line(f"help {entry.name}")
    for action in entry.arguments():
        for flag in action.option_strings:
            assert flag in capture.out, f"{entry.name}: {flag} missing from help"


@pytest.mark.parametrize("entry", COMMANDS, ids=lambda entry: entry.name)
def test_usage_line_advertises_only_real_flags(entry):
    """The usage line is hand-written; a flag it names must still exist.

    The other direction is deliberately not checked: a usage line is a summary
    for a human, so it is free to leave a rarely-used flag to the generated
    Options section below it.
    """
    declared = {
        flag for action in entry.arguments() for flag in action.option_strings
    }
    for word in entry.usage.replace("[", " ").replace("]", " ").split():
        if word.startswith("--") and len(word) > 2:
            assert word in declared, (
                f"{entry.name}: usage names {word}, which the parser does not accept"
            )


@pytest.mark.parametrize("flag", ["--help", "-h"])
def test_a_command_can_be_asked_for_its_own_help(shell, capture, flag):
    shell.run_line(f"scan {flag}")
    assert "Search the whole address space" in capture.out
    assert "--between A B" in capture.out


def test_help_flag_wins_over_a_bad_argument(shell, capture):
    """'scan --help' must explain, not complain about the missing value."""
    assert shell.run_line("scan --help") is True
    assert capture.err == ""


def test_option_words_come_from_the_parser():
    from peekmem.commands import option_words

    assert "--writable" in option_words("scan")
    assert "--between" in option_words("find")  # an alias resolves too
    assert option_words("nosuchcommand") == []


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
