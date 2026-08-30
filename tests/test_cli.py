# -*- coding: utf-8 -*-

"""The command-line front end: flags, batch mode and exit statuses."""

import io

import pytest

from picklock.cli import build_parser, main


def run(argv, stdin_text=None, monkeypatch=None):
    """Run main() with stdin replaced, returning (status, stdout, stderr)."""
    import sys

    stdout, stderr = io.StringIO(), io.StringIO()
    stdin = io.StringIO(stdin_text or "")
    # An explicit isatty: a StringIO has none, and _batch_lines asks.
    stdin.isatty = lambda: stdin_text is None  # type: ignore[method-assign]

    old = sys.stdout, sys.stderr, sys.stdin
    sys.stdout, sys.stderr, sys.stdin = stdout, stderr, stdin
    try:
        status = main(argv)
    finally:
        sys.stdout, sys.stderr, sys.stdin = old
    return status, stdout.getvalue(), stderr.getvalue()


def test_execute_runs_a_command_and_exits():
    status, out, _ = run(["-e", "version"])
    assert status == 0
    assert "Picklock" in out


def test_execute_flags_run_in_order():
    status, out, _ = run(["-e", "config:set limit 3", "-e", "config:list"])
    assert status == 0
    assert out.index("limit = 3") < out.index("SETTING")


def test_a_trailing_command_works_like_execute():
    status, out, _ = run(["ps:list", "--limit", "1"])
    assert status == 0
    assert "PID" in out


def test_a_failing_command_exits_non_zero():
    status, _, err = run(["-e", "memory:read 0x10"])
    assert status == 1
    assert "No process attached" in err


def test_commands_after_a_failure_do_not_run():
    status, out, _ = run(["-e", "nosuchcommand", "-e", "version"])
    assert status == 1
    assert "Picklock" not in out


def test_commands_are_read_from_a_pipe():
    status, out, _ = run([], stdin_text="version\n# comment\n")
    assert status == 0
    assert out.count("Picklock") == 1


def test_pid_and_name_together_are_rejected():
    status, _, err = run(["-p", "1", "-n", "init", "-e", "version"])
    assert status == 2
    assert "not both" in err


def test_a_bad_pid_stops_before_the_commands():
    status, out, err = run(["-p", "2147483646", "-e", "version"])
    assert status == 1
    assert "Picklock" not in out
    # Specifically the PID's fault. Asserting only on the status let a real
    # bug hide here once: --pid built a command that no longer existed, so the
    # run failed for the right code and entirely the wrong reason.
    assert "2147483646" in err


def test_the_target_flags_build_a_real_command():
    """--pid and --name are spelled as a command line; it has to be one."""
    from picklock.cli import _startup_lines
    from picklock.commands import lookup

    for argv in (["-p", "42"], ["-n", "game.exe", "-i", "--partial"]):
        options = build_parser().parse_args(argv + ["-e", "version"])
        for line in _startup_lines(options):
            word, _, rest = line.partition(" ")
            entry = lookup(word)  # raises if the command does not exist
            entry.parser().parse_args(rest.split())


def test_limit_flag_reaches_the_session():
    status, out, _ = run(["--limit", "1", "-e", "ps:list"])
    assert status == 0
    assert "Showing 1 of" in out


def test_an_outdated_pymemoryeditor_stops_the_run(monkeypatch):
    """The check must land before any command touches a process."""
    from picklock import dependencies

    monkeypatch.setattr(dependencies.PyMemoryEditor, "__version__", "2.1.0")
    status, out, err = run(["-e", "version"])
    assert status == 2
    assert "PyMemoryEditor 2.2.0 or newer" in err
    assert out == ""


def test_version_flag():
    parser = build_parser()
    with pytest.raises(SystemExit) as exit_info:
        parser.parse_args(["--version"])
    assert exit_info.value.code == 0


def test_help_lists_the_layers_not_every_command(capsys):
    """--help mirrors the shell's own overview: one list of first words."""
    text = build_parser().format_help()
    for name in ("ps", "memory", "scan", "pointer"):
        assert name in text
    for name in ("help", "config", "version", "exit"):
        assert name in text
    assert "picklock help <command>" in text
    assert "memory:read" not in text, "the deeper layer is reached, not dumped"
    assert "namespace" not in text.lower()


def test_version_flag_prints_the_whole_report():
    """'picklock --version' is what goes in a bug report, so it needs all four."""
    text = build_parser().format_usage()  # parser builds without error
    assert text

    with pytest.raises(SystemExit) as exit_info:
        build_parser().parse_args(["--version"])
    assert exit_info.value.code == 0


def test_the_flag_and_the_command_cannot_disagree():
    """Both spellings come from one function, and this pins that down."""
    from picklock.commands.session_commands import version_report

    status, out, _ = run(["-e", "version"])
    assert status == 0
    assert out.strip() == version_report().strip()

    action = next(
        item
        for item in build_parser()._actions
        if "--version" in item.option_strings
    )
    assert action.version == version_report()
