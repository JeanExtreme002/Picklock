# -*- coding: utf-8 -*-

"""Line parsing and dispatch."""

import pytest

from peekmem.errors import CommandError, ExitShell
from peekmem.shell import Shell


@pytest.mark.parametrize(
    "line,expected",
    [
        ("ps", ("ps", [])),
        ("  ps  chrome ", ("ps", ["chrome"])),
        ("ps chrome;", ("ps", ["chrome"])),
        ("ps chrome ;;", ("ps", ["chrome"])),
        ("write 0x10 bytes 'DE AD'", ("write", ["0x10", "bytes", "DE AD"])),
        ("\\q", ("\\q", [])),
        ("source \\.", ("source", ["."])),
    ],
)
def test_split(line, expected):
    assert Shell.split(line) == expected


@pytest.mark.parametrize("line", ["", "   ", "# a comment", "-- also a comment"])
def test_blank_and_comment_lines_are_skipped(line):
    assert Shell.split(line) is None


def test_unbalanced_quotes_are_reported():
    with pytest.raises(CommandError):
        Shell.split("scan string 'unclosed")


def test_unknown_command_suggests_a_near_miss(shell, capture):
    assert shell.run_line("scna int32 1") is False
    assert "Did you mean 'scan'" in capture.err


def test_a_failing_command_does_not_end_the_session(shell, capture):
    assert shell.run_line("read 0x10") is False
    assert shell.run_line("version") is True
    assert "Peekmem" in capture.out


def test_errors_can_be_raised_instead_of_printed(shell):
    with pytest.raises(CommandError):
        shell.run_line("read 0x10", raise_errors=True)


def test_exit_unwinds_the_loop(shell):
    with pytest.raises(ExitShell):
        shell.run_line("exit")


def test_run_lines_stops_at_the_first_failure(shell, capture):
    status = shell.run_lines(["version", "nosuchcommand", "version"], raise_errors=True)
    assert status == 1
    assert capture.out.count("Peekmem") == 1


def test_run_lines_returns_the_exit_status(shell):
    assert shell.run_lines(["version", "exit"]) == 0


def test_prompt_names_the_target(shell):
    assert shell.prompt() == "peekmem> "


def test_help_lists_every_group(shell, capture):
    shell.run_line("help")
    for group in ("Process", "Memory", "Scanning", "Pointers", "Session"):
        assert group in capture.out


def test_help_topics_are_reachable(shell, capture):
    shell.run_line("help address")
    assert "module+offset" in capture.out
    capture.reset()
    shell.run_line("help scanning")
    assert "next changed" in capture.out


def test_source_runs_a_file(shell, capture, tmp_path):
    script = tmp_path / "setup.peek"
    script.write_text("# a comment\nset limit 7\n\nset hex on\n")
    shell.run_line(f"source {script}")
    assert shell.session.option("limit") == 7
    assert shell.session.option("hex") is True


def test_source_stops_at_the_failing_line(shell, capture, tmp_path):
    script = tmp_path / "bad.peek"
    script.write_text("set limit 7\nnosuchcommand\nset limit 9\n")
    shell.run_line(f"source {script}")
    assert "bad.peek:2" in capture.err
    assert shell.session.option("limit") == 7


def test_interactive_loop_reads_until_eof(shell, capture, monkeypatch):
    lines = iter(["version", "exit"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(lines))
    assert shell.interact(banner=False) == 0
    assert "Bye" in capture.out


def test_ctrl_c_at_the_prompt_does_not_quit(shell, capture, monkeypatch):
    answers = iter([KeyboardInterrupt, "exit"])

    def fake_input(prompt=""):
        value = next(answers)
        if value is KeyboardInterrupt:
            raise KeyboardInterrupt
        return value

    monkeypatch.setattr("builtins.input", fake_input)
    assert shell.interact(banner=False) == 0
    assert "^C" in capture.out
