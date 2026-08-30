# -*- coding: utf-8 -*-

"""
The ``picklock`` entry point.

Run bare, it opens the interactive shell. Given commands — with ``-e``, as a
trailing command line, in a file, or on standard input — it runs them and
exits with a status, so the same vocabulary works inside a script, an SSH
session or a CI job:

    picklock                                  # the shell
    picklock ps:list chrome                           # one command, then exit
    picklock -p 4242 -e "memory:read game.exe+0x10"   # attach, read, exit
    picklock -f setup.peek                            # a file of commands
    echo "ps:list" | picklock                         # a pipe
"""

import argparse
import shlex
import sys
from typing import List, Optional, Sequence

import PyMemoryEditor

from . import __version__, dependencies
from .commands import top_level_listing
from .commands.alias_commands import restore as restore_aliases
from .commands.session_commands import restore as restore_settings
from .errors import CommandError, PicklockError
from .output import Printer
from .session import Session
from .shell import Shell


def _format_commands() -> str:
    """The same layered summary the shell's own ``help`` prints.

    Every word you can type first, and nothing below it — rather than all
    thirty-odd commands at once, which is a wall rather than an answer.
    """
    rows = top_level_listing()
    width = max(len(signature) for signature, _ in rows)

    lines: List[str] = ["picklock commands:", ""]
    # Four spaces between the columns, as the shell's own listings use.
    lines += [f"  {signature.ljust(width)}    {summary}" for signature, summary in rows]
    lines += [
        "",
        "Run 'picklock help <command>' for what a command takes, or",
        "'picklock help' for the topics ('types', 'address', 'scanning').",
    ]
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="picklock",
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
        version=f"picklock {__version__} (PyMemoryEditor {PyMemoryEditor.__version__})",
    )
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="a single command to run, e.g. 'picklock ps:list chrome'",
    )
    return parser


def _startup_lines(options: argparse.Namespace) -> List[str]:
    """The commands implied by the target flags, run before anything else."""
    if options.pid is None and options.name is None:
        return []
    if options.pid is not None and options.name is not None:
        raise CommandError("Give --pid or --name, not both.")

    parts = ["ps:open"]
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
    redirect is someone scripting Picklock, while a terminal is someone who
    typed ``picklock`` and wants the prompt.
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
    """Run Picklock. Returns the process exit status."""
    parser = build_parser()
    options = parser.parse_args(argv)

    printer = Printer(
        color=False if options.no_color else None,
        timing=not options.no_timing,
    )

    # Before anything touches a process: a PyMemoryEditor below the declared
    # floor fails later, deep inside a scan, with an error that names a Mach
    # call rather than the cause.
    outdated = dependencies.check()
    if outdated is not None:
        printer.error(outdated)
        return 2

    session = Session(printer)
    shell = Shell(session, printer=printer)

    # The aliases the user defined in an earlier run. Loaded here rather than
    # in Session, so a Session built in a test or a script touches no files
    # unless it asks to.
    dropped = restore_aliases(session)
    if dropped:
        printer.note(
            "Dropped %s, whose command no longer exists: %s."
            % (
                "an alias" if len(dropped) == 1 else "some aliases",
                ", ".join(sorted(dropped)),
            )
        )

    # Settings come back too. Restored before --limit is applied, so a flag
    # given on this run still wins over what was stored on the last one.
    forgotten = restore_settings(session)
    if forgotten:
        printer.note(
            "Ignored %s no longer recognised: %s."
            % (
                "a stored setting" if len(forgotten) == 1 else "stored settings",
                ", ".join(sorted(forgotten)),
            )
        )

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

    except PicklockError as error:
        printer.error(str(error))
        return 1
    except KeyboardInterrupt:
        printer.clear_progress()
        printer.write()
        return 130
    except BrokenPipeError:  # pragma: no cover - depends on the consumer
        # 'picklock ps | head' closes the pipe early; that is not an error.
        return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
