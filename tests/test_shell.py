# -*- coding: utf-8 -*-

"""Line parsing and dispatch."""

import pytest

from picklock.errors import CommandError, ExitShell
from picklock.shell import Shell


@pytest.mark.parametrize(
    "line,expected",
    [
        ("ps:list", ("ps:list", [])),
        ("  ps:list  chrome ", ("ps:list", ["chrome"])),
        ("ps:list chrome;", ("ps:list", ["chrome"])),
        ("ps:list chrome ;;", ("ps:list", ["chrome"])),
        (
            "memory:write 0x10 bytes 'DE AD'",
            ("memory:write", ["0x10", "bytes", "DE AD"]),
        ),
        ("\\h", ("\\h", [])),
        # '#' introduces a scan-result row and must not read as a comment.
        ("memory:read #3 int32", ("memory:read", ["#3", "int32"])),
        # A backslash in an argument is a path separator, not an escape. This
        # is the whole reason a Windows path can be typed at the prompt.
        (
            "source C:\\tools\\setup.txt",
            ("source", ["C:\\tools\\setup.txt"]),
        ),
        # Quotes are still how a path with spaces is written, on every platform.
        (
            'source "C:\\Program Files\\setup.txt"',
            ("source", ["C:\\Program Files\\setup.txt"]),
        ),
    ],
)
def test_split(line, expected):
    assert Shell.split(line) == expected


@pytest.mark.parametrize("line", ["", "   ", "# a comment", "-- also a comment"])
def test_blank_and_comment_lines_are_skipped(line):
    assert Shell.split(line) is None


def test_unbalanced_quotes_are_reported():
    with pytest.raises(CommandError):
        Shell.split("scan:value string 'unclosed")


def test_unknown_command_suggests_a_near_miss(shell, capture):
    assert shell.run_line("memory:raed 0x10") is False
    assert "Did you mean 'memory:read'" in capture.err


def test_a_failing_command_does_not_end_the_session(shell, capture):
    assert shell.run_line("memory:read 0x10") is False
    assert shell.run_line("version") is True
    assert "Picklock" in capture.out


def test_errors_can_be_raised_instead_of_printed(shell):
    with pytest.raises(CommandError):
        shell.run_line("memory:read 0x10", raise_errors=True)


def test_exit_unwinds_the_loop(shell):
    with pytest.raises(ExitShell):
        shell.run_line("exit")


def test_run_lines_stops_at_the_first_failure(shell, capture):
    status = shell.run_lines(["version", "nosuchcommand", "version"], raise_errors=True)
    assert status == 1
    assert capture.out.count("Picklock") == 1


def test_run_lines_returns_the_exit_status(shell):
    assert shell.run_lines(["version", "exit"]) == 0


class _FakeProcess:
    pid = 4242


def _attach(shell):
    shell.session.process = _FakeProcess()  # type: ignore[assignment]
    shell.session.process_name = "game.exe"


def test_prompt_names_the_target(shell):
    assert shell.prompt() == "picklock> "
    _attach(shell)
    assert shell.prompt() == "picklock [game.exe:4242]> "


def test_the_target_is_dimmed_when_colour_is_on(shell, capture):
    """A reminder that writes are going somewhere, not a thing to look at."""
    capture.printer.color = True
    _attach(shell)
    assert shell.prompt() == "picklock \033[38;5;247m[game.exe:4242]\033[0m> "


def test_an_empty_prompt_is_never_styled(shell, capture):
    """Nothing is attached, so there is nothing to point at."""
    capture.printer.color = True
    assert shell.prompt() == "picklock> "
    assert "\033" not in shell.prompt()


def test_the_prompt_brackets_its_escapes_only_under_readline(shell, capture):
    capture.printer.color = True
    _attach(shell)
    assert "\001" not in shell.prompt()

    shell._readline = True
    assert "\001" in shell.prompt()
    assert shell.prompt().count("\001") == shell.prompt().count("\002")


def test_help_lists_every_namespace(shell, capture):
    shell.run_line("help")
    for namespace in ("process", "memory", "scan", "pointer"):
        assert namespace in capture.out


def test_help_topics_are_reachable(shell, capture):
    shell.run_line("help address")
    assert "module+offset" in capture.out
    capture.reset()
    shell.run_line("help scanning")
    assert "scan:next --changed" in capture.out


def test_source_runs_a_file(shell, capture, tmp_path):
    script = tmp_path / "setup.txt"
    script.write_text("# a comment\nconfig:set limit 7\n\nconfig:set hex on\n")
    shell.run_line(f"source {script}")
    assert shell.session.option("limit") == 7
    assert shell.session.option("hex") is True


def test_source_stops_at_the_failing_line(shell, capture, tmp_path):
    script = tmp_path / "bad.txt"
    script.write_text("config:set limit 7\nnosuchcommand\nconfig:set limit 9\n")
    shell.run_line(f"source {script}")
    assert "bad.txt:2" in capture.err
    assert shell.session.option("limit") == 7


def test_interactive_loop_reads_until_eof(shell, capture, monkeypatch):
    lines = iter(["version", "exit"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(lines))
    assert shell.interact(banner=False) == 0
    assert capture.err == ""


def test_a_bug_in_a_command_does_not_end_the_session(shell, capture, monkeypatch):
    """An unexpected exception costs the command, not the scan behind it."""
    lines = iter(["boom", "exit"])

    def fake_input(prompt=""):
        return next(lines)

    def explode(session, args):
        raise AttributeError("something the author did not think of")

    real_resolve = shell._resolve

    def resolve(word, args):
        if word == "boom":
            return type("E", (), {"name": "boom", "handler": staticmethod(explode)})
        return real_resolve(word, args)

    monkeypatch.setattr("builtins.input", fake_input)
    monkeypatch.setattr(shell, "_setup_readline", lambda: None)
    monkeypatch.setattr(shell, "_save_history", lambda: None)
    monkeypatch.setattr(shell, "_resolve", resolve)

    assert shell.interact(banner=False) == 0, "the session survived to reach 'exit'"
    assert "AttributeError" in capture.err
    assert "bug in Picklock" in capture.err


def test_ctrl_c_at_the_prompt_quits(shell, capture, monkeypatch):
    """An interrupt at an empty prompt ends the session."""

    def fake_input(prompt=""):
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", fake_input)
    assert shell.interact(banner=False) == 130
    assert "^C" in capture.out
    assert capture.err == ""


def test_ctrl_d_quits_with_a_zero_status(shell, capture, monkeypatch):
    def fake_input(prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", fake_input)
    assert shell.interact(banner=False) == 0
    assert capture.err == ""


def test_ctrl_c_during_a_command_returns_to_the_prompt(shell, capture, monkeypatch):
    """Interrupting a long scan must not also end the session.

    One keystroke abandons the command; a second one, now at the prompt, is
    what leaves. Losing the shell — and the scan results in it — on the
    keystroke that stops a scan would make the results unreachable.
    """
    from picklock.commands import Command, lookup

    def interrupted(session, args):
        raise KeyboardInterrupt

    real_lookup = lookup

    def fake_lookup(name):
        entry = real_lookup(name)
        if entry.name == "version":
            return Command(
                name=entry.name,
                handler=interrupted,
                summary=entry.summary,
            )
        return entry

    monkeypatch.setattr("picklock.shell.lookup", fake_lookup)

    lines = iter(["version", "exit"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(lines))

    assert shell.interact(banner=False) == 0
    assert "^C" in capture.out
