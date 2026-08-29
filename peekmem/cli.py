# -*- coding: utf-8 -*-

"""
The ``peekmem`` entry point.

Run bare, it opens the interactive shell. Given commands — with ``-e``, as a
trailing command line, in a file, or on standard input — it runs them and
exits with a status, so the same vocabulary works inside a script, an SSH
session or a CI job:

    peekmem                                  # the shell
    peekmem ps chrome                        # one command, then exit
    peekmem -p 4242 -e "read game.exe+0x10"  # attach, read, exit
    peekmem -f setup.peek                    # a file of commands
    echo "ps" | peekmem                      # a pipe
"""

import argparse
import shlex
import sys
from typing import List, Optional, Sequence

import PyMemoryEditor

from . import __version__
from .commands import GROUPS, all_commands
from .errors import CommandError, PeekmemError
from .output import Printer
from .session import Session
from .shell import Shell

_EPILOG_INTRO = (
    "Commands — run 'peekmem <command> --help' for one command's arguments,\n"
    "or 'peekmem help' for the topics:"
)


def _format_commands() -> str:
    """A compact command list for ``--help``, grouped like ``help`` is."""
    commands = all_commands()
    width = max(len(entry.name) for entry in commands)
    lines: List[str] = [_EPILOG_INTRO, ""]
    for group in GROUPS:
        in_group = [entry for entry in commands if entry.group == group]
        if not in_group:
            continue
        lines.append(f"  {group}")
        for entry in in_group:
            lines.append(f"    {entry.name.ljust(width)}  {entry.summary}")
        lines.append("")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="peekmem",
        description=(
            "A terminal client for PyMemoryEditor: read, write and scan the "
            "memory of a running process from any shell, on Windows, Linux or "
            "macOS."
        ),
        epilog=_format_commands(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    target = parser.add_argument_group("target")
    target.add_argument("-p", "--pid", type=int, help="attach to this PID at startup")
    target.add_argument("-n", "--name", help="attach to this process name at startup")
    target.add_argument(
        "-i",
        "--ignore-case",
        action="store_true",
        help="match --name regardless of case",
    )
    target.add_argument(
        "--partial",
        action="store_true",
        help="match --name as a substring ('chrome' finds 'chrome.exe')",
    )

    running = parser.add_argument_group("commands")
    running.add_argument(
        "-e",
        "--execute",
        action="append",
        default=[],
        metavar="COMMAND",
        help="run a command and exit; repeatable, run in order",
    )
    running.add_argument(
        "-f",
        "--file",
        metavar="FILE",
        help="run the commands in FILE and exit",
    )

    output = parser.add_argument_group("output")
    output.add_argument(
        "--no-color", action="store_true", help="never emit ANSI colour"
    )
    output.add_argument(
        "--no-timing", action="store_true", help="omit the elapsed-time footer"
    )
    output.add_argument(
        "--limit",
        type=int,
        metavar="N",
        help="rows printed per result table (0 for no limit)",
    )
    output.add_argument(
        "-q", "--quiet", action="store_true", help="skip the welcome banner"
    )
    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"peekmem {__version__} (PyMemoryEditor {PyMemoryEditor.__version__})",
    )
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="a single command to run, e.g. 'peekmem ps chrome'",
    )
    return parser


def _startup_lines(options: argparse.Namespace) -> List[str]:
    """The commands implied by the target flags, run before anything else."""
    if options.pid is None and options.name is None:
        return []
    if options.pid is not None and options.name is not None:
        raise CommandError("Give --pid or --name, not both.")

    parts = ["open"]
    if options.pid is not None:
        parts += ["--pid", str(options.pid)]
    else:
        parts += ["--name", shlex.quote(options.name)]
    if options.ignore_case:
        parts.append("-i")
    if options.partial:
        parts.append("--partial")
    return [" ".join(parts)]


def _batch_lines(options: argparse.Namespace, stdin) -> Optional[List[str]]:
    """The commands to run non-interactively, or ``None`` for the shell.

    Standard input counts only when it is *not* a terminal: a pipe or a
    redirect is someone scripting Peekmem, while a terminal is someone who
    typed ``peekmem`` and wants the prompt.
    """
    lines: List[str] = []

    lines.extend(options.execute)

    if options.command:
        lines.append(" ".join(shlex.quote(part) for part in options.command))

    if options.file:
        lines.append(f"source {shlex.quote(options.file)}")

    if lines:
        return lines

    if not getattr(stdin, "isatty", lambda: True)():
        return stdin.read().splitlines()

    return None


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run Peekmem. Returns the process exit status."""
    parser = build_parser()
    options = parser.parse_args(argv)

    printer = Printer(
        color=False if options.no_color else None,
        timing=not options.no_timing,
    )
    session = Session(printer)
    shell = Shell(session, printer=printer)

    if options.limit is not None:
        session.set_option("limit", str(options.limit))

    try:
        startup = _startup_lines(options)
    except CommandError as error:
        printer.error(str(error))
        return 2

    batch = _batch_lines(options, sys.stdin)
    interactive = batch is None

    try:
        # A failed --pid/--name is fatal either way: the commands that follow
        # were written for a target that is not there.
        for line in startup:
            if not shell.run_line(line, raise_errors=False):
                return 1

        if interactive:
            return shell.interact(banner=not options.quiet)

        try:
            return shell.run_lines(batch or [], raise_errors=True)
        finally:
            session.close()

    except PeekmemError as error:
        printer.error(str(error))
        return 1
    except KeyboardInterrupt:
        printer.clear_progress()
        printer.write()
        return 130
    except BrokenPipeError:  # pragma: no cover - depends on the consumer
        # 'peekmem ps | head' closes the pipe early; that is not an error.
        return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
