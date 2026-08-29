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
        "config",
        "exit",
        "help",
        "source",
        "version",
    ]


@pytest.mark.parametrize("namespace", [item.name for item in NAMESPACES])
def test_a_bare_namespace_lists_it(shell, capture, namespace):
    """Including 'scan' and 'pointer', which are command aliases as well."""
    shell.run_line(namespace)
    assert f"usage: {namespace}[:COMMAND]" in capture.out
    assert f"{namespace} commands:" in capture.out
    assert capture.err == ""


@pytest.mark.parametrize("line", ["scan int32 100", "pointer 0x10"])
def test_a_parent_command_never_runs_anything(shell, line):
    """A word that takes a subcommand is not itself an action."""
    with pytest.raises(CommandError) as error:
        shell.run_line(line, raise_errors=True)
    assert "takes a subcommand" in str(error.value)


def test_clear_leaves_the_session_alone(shell, capture):
    """It wipes the screen, not the work: a cleared terminal is not a reset."""
    from peekmem import valuetypes

    shell.session.store_scan(valuetypes.resolve("int32"), 4, [0x10], [1], "t")
    shell.run_line("clear")
    assert shell.session.scan is not None
    assert capture.err == ""


@pytest.mark.parametrize("entry", COMMANDS, ids=lambda entry: entry.name)
def test_a_namespaced_command_has_no_plain_word_alias(entry):
    """One namespace's 'read' must not claim the word from another's.

    Only the shell's own top-level commands keep short spellings, and those are
    shortcuts (\\q, cls) rather than second names for a namespaced command.
    """
    if entry.is_top_level:
        return
    assert entry.aliases == (), f"{entry.name} still answers to {entry.aliases}"


@pytest.mark.parametrize("entry", COMMANDS, ids=lambda entry: entry.name)
def test_names_go_at_most_one_level_deep(entry):
    """Two levels is the ceiling: 'scan:keep', never 'scan:results:keep'.

    A third level buys a tidier name at the cost of a listing that has to be
    walked twice to be read once.
    """
    assert entry.name.count(":") <= 1


def test_the_registry_refuses_a_third_level():
    from peekmem.commands import CommandParser, command

    with pytest.raises(RuntimeError, match="one level deep"):
        command(
            "scan:results:keep",
            parser=lambda: CommandParser("scan:results:keep"),
            summary="Never registered.",
        )(lambda session, args: None)


def test_namespaces_are_listed_in_the_declared_order():
    order = [item.name for item in NAMESPACES]
    seen = [entry.namespace for entry in COMMANDS if not entry.is_top_level]
    positions = [order.index(name) for name in seen]
    assert positions == sorted(positions)


def test_top_level_commands_sort_last():
    """help prints the subjects first, then the words that drive the shell."""
    names = [entry.is_top_level for entry in all_commands()]
    assert names == sorted(names), "a namespaced command came after a top-level one"


def test_children_are_the_commands_of_a_namespace():
    names = [entry.name for entry in children("scan")]
    assert names == [
        "scan:aob",
        "scan:drop",
        "scan:keep",
        "scan:next",
        "scan:regex",
        "scan:reset",
        "scan:results",
        "scan:value",
    ]
    assert children("scan:results") == [], "a command has no commands under it"


def test_the_overview_shows_layers_not_every_command(shell, capture):
    shell.run_line("help")
    out = capture.out
    for namespace in namespaces():
        assert namespace in out
    for entry in top_level():
        assert entry.name in out
    # The point of the layering: the deeper commands are pointed at, not
    # listed. A couple of them appear in the worked example, which is why this
    # names ones that do not.
    for hidden in ("memory:regions", "scan:keep", "pointer:save"):
        assert hidden not in out
    assert "<command>:help" in out
    # Parents and leaves sit in one list, spelled the same way.
    for word in ("memory", "pointer", "ps", "scan", "clear", "version"):
        assert word in out


@pytest.mark.parametrize("namespace", [item.name for item in NAMESPACES])
def test_namespace_help_lists_that_layer(shell, capture, namespace):
    shell.run_line(f"{namespace}:help")
    assert f"{namespace} commands:" in capture.out
    for entry in children(namespace):
        assert entry.name in capture.out
    assert capture.err == ""


def test_a_namespace_listing_is_the_whole_namespace(shell, capture):
    """With two levels there is nowhere deeper to point at."""
    shell.run_line("scan:help")
    for entry in children("scan"):
        assert entry.name in capture.out


@pytest.mark.parametrize("namespace", [item.name for item in NAMESPACES])
def test_every_namespace_has_commands(namespace):
    assert children(namespace), f"namespace {namespace!r} is empty"


def test_typing_a_namespace_lists_it(shell, capture):
    shell.run_line("memory")
    assert "usage: memory[:COMMAND]" in capture.out
    assert "memory commands:" in capture.out
    assert "memory:read" in capture.out
    assert capture.err == ""


def test_a_namespace_with_arguments_points_at_the_colon(shell, capture):
    """'memory read 0x10' is the likely typo; name the fix precisely."""
    assert shell.run_line("memory read 0x10") is False
    assert "'memory:read'" in capture.err


def test_a_parent_with_nonsense_arguments_is_still_explained(shell, capture):
    assert shell.run_line("memory nonsense") is False
    assert "takes a subcommand" in capture.err
    assert "memory:help" in capture.err


def test_help_on_a_namespace_lists_it(shell, capture):
    shell.run_line("help memory")
    assert "memory commands:" in capture.out
    assert "memory:read" in capture.out


def test_a_namespace_listing_shows_argument_signatures(shell, capture):
    """The dokku shape: what it is called and what it takes, in one line."""
    shell.run_line("memory:help")
    assert "memory:dump <address> [length]" in capture.out
    assert "memory:read <address> [type] [length]" in capture.out


def test_a_namespace_listing_carries_a_worked_example(shell, capture):
    shell.run_line("ps:help")
    assert "Example:" in capture.out
    assert "peekmem> ps:list chrome" in capture.out


def test_a_long_signature_is_cut_at_a_token_boundary(shell, capture):
    shell.run_line("pointer:help")
    # The listing row, not the worked example above it.
    line = next(
        line
        for line in capture.out.splitlines()
        if line.strip().startswith("pointer:scan")
    )
    signature = line.strip().split("  ")[0]
    assert signature.endswith("...")
    assert len(signature) <= 44
    assert "  " not in signature.strip(), "cut mid-token"


def test_namespace_help_can_describe_one_subcommand(shell, capture):
    """'scan:help aob' — exactly what the listing header advertises."""
    shell.run_line("scan:help aob")
    assert "scan:aob — Scan for a byte pattern" in capture.out
    assert "Usage: scan:aob" in capture.out


def test_namespace_help_with_a_bad_subcommand_is_reported(shell, capture):
    assert shell.run_line("scan:help nosuch") is False
    assert "Unknown command" in capture.err


@pytest.mark.parametrize(
    "line", ["scan", "scan --help", "scan -h", "scan:help", "help scan"]
)
def test_every_way_of_asking_about_a_namespace_agrees(shell, capture, line):
    """Five spellings, one page — whichever a reader reaches for."""
    shell.run_line(line)
    assert capture.out.startswith("usage: scan[:COMMAND]")
    assert "scan commands:" in capture.out
    assert capture.err == ""


@pytest.mark.parametrize("topic", ["pointer:", "scan:", "memory:"])
def test_a_trailing_colon_asks_for_the_namespace(shell, capture, topic):
    shell.run_line(f"help {topic}")
    assert f"{topic.rstrip(':')} commands:" in capture.out


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
def test_usage_line_names_every_flag(entry):
    """A flag the command accepts is a flag its usage line shows.

    Three commands had grown options their hand-written usage never mentioned,
    which is why the line is generated from the parser now. This pins the
    property down in both directions at once: what is listed is what exists.
    """
    declared = {
        flag
        for action in entry.arguments()
        for flag in action.option_strings
        if flag.startswith("--")
    }
    shown = {
        word.strip("[]")
        for word in entry.usage.replace("[", " [").split()
        if word.strip("[]").startswith("--")
    }
    assert declared == shown, f"{entry.name}: usage and parser disagree"


@pytest.mark.parametrize("entry", COMMANDS, ids=lambda entry: entry.name)
def test_usage_line_starts_with_the_command(entry):
    assert entry.usage == entry.name or entry.usage.startswith(entry.name + " ")


@pytest.mark.parametrize("flag", ["--help", "-h"])
def test_a_command_can_be_asked_for_its_own_help(shell, capture, flag):
    shell.run_line(f"scan:value {flag}")
    assert "Search the whole address space" in capture.out
    assert "--between A B" in capture.out


def test_help_flag_wins_over_a_bad_argument(shell, capture):
    """'scan:value --help' must explain, not complain about the missing value."""
    assert shell.run_line("scan:value --help") is True
    assert capture.err == ""


def test_option_words_come_from_the_parser():
    from peekmem.commands import option_words

    assert "--writable" in option_words("scan:value")
    assert "--between" in option_words("scan:value")
    assert option_words("nosuchcommand") == []
    assert option_words("scan") == [], "a namespace has no options of its own"


@pytest.mark.parametrize("word", ["status", "\\q", "\\s", "set", "process:list"])
def test_retired_spellings_stay_retired(word):
    """Names that were removed must not quietly come back as an alias."""
    with pytest.raises(CommandError):
        lookup(word)


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
        "memory:read 0x10",
        "memory:write 0x10 int32 1",
        "memory:dump 0x10",
        "memory:regions",
        "memory:modules",
        "memory:threads",
        "scan:value int32 1",
        "scan:aob 'DE AD'",
        "scan:regex abc",
        "pointer:deref 0x10",
        "pointer:read 0x10",
        "pointer:scan 0x10",
        "memory:alloc 16",
        "memory:free 0x10",
        "memory:watch 0x10",
        "ps:info",
    ],
)
def test_commands_needing_a_target_refuse_without_one(shell, line):
    with pytest.raises(NoProcessError):
        shell.run_line(line, raise_errors=True)


@pytest.mark.parametrize(
    "line",
    [
        "scan:next 1",
        "scan:results",
        "scan:keep 1",
        "scan:drop 1",
        "pointer:paths",
        "pointer:save out.json",
    ],
)
def test_commands_needing_results_refuse_without_them(shell, line):
    with pytest.raises(CommandError):
        shell.run_line(line, raise_errors=True)


def test_close_without_a_target_is_an_error(shell):
    with pytest.raises(CommandError):
        shell.run_line("ps:close", raise_errors=True)


def test_version_reports_both_halves(shell, capture):
    """Peekmem is a client: which PyMemoryEditor is underneath is half the answer."""
    shell.run_line("version")
    for label in ("Peekmem", "PyMemoryEditor", "Python", "Platform"):
        assert f"{label}:" in capture.out


def test_ps_lists_this_process(shell, capture):
    """The one command that talks to the OS without attaching to anything."""
    import os

    shell.run_line("config limit 0")
    shell.run_line("ps:list")
    assert str(os.getpid()) in capture.out


def test_config_prints_booleans_the_way_they_are_typed(shell, capture):
    shell.run_line("config")
    assert "| off" in capture.out or "off " in capture.out
    capture.reset()
    shell.run_line("config hex on")
    assert "hex = on" in capture.out


def test_config_accepts_the_equals_form(shell):
    shell.run_line("config limit=42")
    assert shell.session.option("limit") == 42


def test_unknown_option_is_reported_not_swallowed(shell):
    with pytest.raises(CommandError):
        shell.run_line("ps:list --nosuchflag", raise_errors=True)


def test_reset_reports_what_it_discarded(shell, capture):
    from peekmem import valuetypes

    shell.session.store_scan(valuetypes.resolve("int32"), 4, [1, 2], [0, 0], "t")
    shell.run_line("scan:reset")
    assert "Discarded 2 result(s)." in capture.out
    assert shell.session.scan is None


#: Every command that reports "Showing n of m rows" must offer a way to see
#: the rest. Kept as a list so a new listing command has to join it.
PAGED = [
    "ps:list",
    "memory:regions",
    "memory:modules",
    "memory:threads",
    "scan:results",
    "pointer:paths",
]


@pytest.mark.parametrize("name", PAGED)
def test_every_listing_command_pages_the_same_way(name):
    """One set of flags, one wording — a listing you learn once."""
    flags = {
        flag for action in lookup(name).arguments() for flag in action.option_strings
    }
    assert {"--limit", "--offset", "--all"} <= flags


@pytest.mark.parametrize("name", PAGED)
def test_paging_flags_are_documented_identically(name):
    """The shared helper is the point: the help text must not drift per command."""
    reference = {
        action.dest: action.help
        for action in lookup("scan:results").arguments()
        if action.dest in ("limit", "offset", "all")
    }
    actual = {
        action.dest: action.help
        for action in lookup(name).arguments()
        if action.dest in ("limit", "offset", "all")
    }
    assert actual == reference


def test_a_truncated_listing_names_the_next_page(shell, capture):
    shell.run_line("ps:list --limit 2")
    assert "Showing 2 of" in capture.out
    assert "Next page: ps:list --offset 2 --limit 2" in capture.out


def test_the_last_page_offers_no_next(shell, capture):
    shell.run_line("ps:list --all")
    assert "Next page:" not in capture.out


def test_offset_cannot_be_negative(shell):
    with pytest.raises(CommandError, match="offset"):
        shell.run_line("ps:list --offset -1", raise_errors=True)


def test_a_scan_preview_pages_through_scan_results(session, capture):
    """Re-running a scan to see page two would be absurd; scan:results is the pager."""
    from peekmem import valuetypes
    from peekmem.commands.scan_commands import _print_results

    session.set_option("limit", "2")
    state = session.store_scan(
        valuetypes.resolve("int32"), 4, [0x10, 0x20, 0x30], [1, 2, 3], "test"
    )

    class FakeProcess:
        pointer_size = 8

    session.process = FakeProcess()  # type: ignore[assignment]
    _print_results(session, state)

    assert "Showing 2 of 3 rows" in capture.out
    assert "Next page: scan:results --offset 2" in capture.out


def test_the_word_namespace_never_reaches_the_reader(shell, capture):
    """It is an implementation detail, not something to teach.

    Everything the shell prints — the overview, the topics, every command's
    page, the errors — talks about commands and subcommands only. Swept over
    all of it rather than a sample, because the word leaks back one string at
    a time.
    """
    lines = ["help", "help types", "help address", "help scanning"]
    lines += [f"{name}:help" for name in namespaces()]
    lines += [f"{entry.name}:help" for entry in COMMANDS]
    lines += ["memory nonsense", "memory read 0x10"]

    for line in lines:
        capture.reset()
        shell.run_line(line)
        combined = (capture.out + capture.err).lower()
        assert "namespace" not in combined, f"{line!r} says 'namespace'"


@pytest.mark.parametrize(
    "line,expected",
    [
        ("memory:help", "usage: memory[:COMMAND]"),
        ("memory:read:help", "memory:read — Read a typed value"),
        ("scan:results:help", "scan:results — Show the current result set"),
        ("clear:help", "clear — Clear the terminal"),
        ("version:help", "version — Print the Peekmem"),
        ("help:help", "help — List the commands"),
    ],
)
def test_every_command_answers_colon_help(shell, capture, line, expected):
    """One rule for asking about anything, with no exceptions to learn."""
    shell.run_line(line)
    assert capture.out.startswith(expected)
    assert capture.err == ""


@pytest.mark.parametrize("entry", COMMANDS, ids=lambda entry: entry.name)
def test_colon_help_works_for_every_registered_command(entry, shell, capture):
    shell.run_line(f"{entry.name}:help")
    assert entry.summary in capture.out
    assert capture.err == ""
