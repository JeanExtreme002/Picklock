# -*- coding: utf-8 -*-

"""Running the shell itself: ``help``, ``set``, ``source``, ``exit``."""

import os
import platform
from typing import List

import PyMemoryEditor

from .. import __version__, valuetypes
from ..errors import CommandError, ExitShell
from ..output import LEFT, RIGHT, render_table, render_vertical
from ..session import SETTINGS, Session
from . import GROUPS, CommandParser, all_commands, command, lookup

_ADDRESS_TOPIC = """\
Every command that takes an address takes an expression.

  0x7ffee3a01000        a literal; decimal works too
  game.exe+0x1234       a module's base plus a static offset
  "libfoo-1.so"+0x20    quote a module name containing '-' or spaces
  [game.exe+0x1234]     the pointer stored there, dereferenced
  [[base+0x8]+0x20]+0x4 nested as deeply as you like
  #3                    the address on row 3 of the last scan

Module names are matched case-insensitively, and an unambiguous prefix is
enough: 'game' finds 'game.exe'. Run 'modules' to list them, and to refresh
the table after the target loads a library.

'module+offset' is the form worth writing down: a module's base moves on every
launch under ASLR, but the offset inside it does not, so the expression keeps
working across restarts where a bare address does not.\
"""

_SCANNING_TOPIC = """\
The scan / refine cycle, when you do not know the address:

  1. scan int32 100        every address holding 100 right now
  2. (make the value change in the target)
  3. next 95               of those, the ones now holding 95

Repeat step 3 until a handful of rows remain. When you cannot see the value —
a health bar with no number — compare against the previous reading instead:

  next changed / next unchanged / next increased / next decreased

Then read, write or watch a surviving row by number:

  read #1 int32
  write #1 int32 999
  watch #1 int32

An address found this way is good for this run only. To keep it, find the
pointer path that reaches it: 'ptrscan #1', then 'ptrsave', restart the
target, and 'ptrrescan' against the value's new address. See 'help ptrscan'.\
"""

_TOPICS = {
    "address": ("Writing an address", _ADDRESS_TOPIC),
    "addresses": ("Writing an address", _ADDRESS_TOPIC),
    "scanning": ("The scan / refine cycle", _SCANNING_TOPIC),
}


def _format_setting(value: object) -> str:
    """Print a setting the way it is typed: booleans as on/off, not True/False."""
    if isinstance(value, bool):
        return "on" if value else "off"
    return str(value)


def _print_types(session: Session) -> None:
    rows = [
        (
            value_type.name,
            "varies" if value_type.is_variable_width else f"{value_type.size}",
            ", ".join(value_type.aliases) or "",
            value_type.summary,
        )
        for value_type in valuetypes.VALUE_TYPES
    ]
    session.printer.write(
        render_table(
            ("TYPE", "BYTES", "ALIASES", "DESCRIPTION"),
            rows,
            (LEFT, RIGHT, LEFT, LEFT),
        )
    )
    session.printer.write()
    session.printer.write(
        "'string' and 'bytes' need a length: 'read <address> string 32'.\n"
        "Byte-array values are written as hex: 'DE AD BE EF'."
    )
    session.printer.write()


def _print_overview(session: Session) -> None:
    printer = session.printer
    printer.write(f"Peekmem {__version__} — a terminal client for PyMemoryEditor.")
    printer.write()

    commands = all_commands()
    width = max(len(entry.name) for entry in commands)

    for group in GROUPS:
        in_group = [entry for entry in commands if entry.group == group]
        if not in_group:
            continue
        printer.write(f"{group}")
        for entry in in_group:
            printer.write(f"  {entry.name.ljust(width)}  {entry.summary}")
        printer.write()

    printer.write("Type 'help <command>' for the full description of one command.")
    printer.write("Topics: 'help types', 'help address', 'help scanning'.")
    printer.write("End the session with 'exit', Ctrl+D, or \\q.")
    printer.write()


def _print_command_help(session: Session, name: str) -> None:
    entry = lookup(name)
    printer = session.printer

    printer.write(f"{entry.name} — {entry.summary}")
    printer.write()
    printer.write(f"Usage: {entry.usage}")
    if entry.aliases:
        printer.write(f"Aliases: {', '.join(entry.aliases)}")
    printer.write()
    if entry.details:
        printer.write(entry.details)
        printer.write()
    if entry.examples:
        printer.write("Examples:")
        for example in entry.examples:
            printer.write(f"  {example}")
        printer.write()


@command(
    "help",
    summary="List the commands, or describe one.",
    usage="help [command|types|address|scanning]",
    group="Session",
    aliases=("?", "\\h"),
    details=(
        "With no argument, prints every command grouped by what it acts on. "
        "With a command name, prints that command's usage, options and "
        "examples. The topics 'types', 'address' and 'scanning' cover the "
        "parts that several commands share."
    ),
    examples=("help", "help scan", "help address"),
)
def cmd_help(session: Session, args: List[str]) -> None:
    if not args:
        _print_overview(session)
        return
    if len(args) > 1:
        raise CommandError("help takes one command or topic at a time.")

    topic = args[0].strip().lower()

    if topic in ("types", "type"):
        _print_types(session)
        return

    if topic in _TOPICS:
        title, body = _TOPICS[topic]
        session.printer.write(title)
        session.printer.write()
        session.printer.write(body)
        session.printer.write()
        return

    _print_command_help(session, topic)


@command(
    "set",
    summary="Show or change a session setting.",
    usage="set [name [value]]",
    group="Session",
    details=(
        "With no argument, prints every setting and its current value. "
        "'set name value' and 'set name=value' both assign.\n\n"
        "Settings live for the session only — Peekmem writes no config file, "
        "so a fresh shell always starts from the documented defaults. Put the "
        "'set' lines in a script and run it with 'source' to reuse a setup."
    ),
    examples=("set", "set limit 50", "set hex on", "set writable_only=true"),
)
def cmd_set(session: Session, args: List[str]) -> None:
    if not args:
        rows = [
            (setting.name, _format_setting(session.option(setting.name)), setting.summary)
            for setting in SETTINGS
        ]
        session.printer.table(
            ("SETTING", "VALUE", "DESCRIPTION"), rows, (LEFT, RIGHT, LEFT)
        )
        return

    if len(args) == 1 and "=" in args[0]:
        name, _, value = args[0].partition("=")
    elif len(args) == 1:
        name, value = args[0], None
    elif len(args) == 2:
        name, value = args[0], args[1]
    else:
        raise CommandError("Usage: set [name [value]]")

    if value is None:
        setting = {item.name: item for item in SETTINGS}.get(name.lower())
        if setting is None:
            raise CommandError(f"Unknown setting {name!r}.")
        session.printer.write(
            render_vertical([(setting.name, _format_setting(session.option(setting.name)))])
        )
        session.printer.write()
        return

    applied = session.set_option(name, value)
    session.printer.ok(f"{name.strip().lower()} = {_format_setting(applied)}")
    session.printer.write()


@command(
    "source",
    summary="Run the commands in a file.",
    usage="source <file>",
    group="Session",
    aliases=("\\.",),
    details=(
        "Reads the file and runs each line as if it had been typed. Blank "
        "lines are skipped, and a line starting with '#' or '--' is a comment.\n\n"
        "A failing line stops the script — a setup that half-ran is worse than "
        "one that says where it stopped."
    ),
    examples=("source setup.peek",),
)
def cmd_source(session: Session, args: List[str]) -> None:
    parser = CommandParser("source")
    parser.add_argument("file")
    options = parser.parse_args(args)

    if session.shell is None:
        raise CommandError("'source' needs a shell to run the commands in.")
    if not os.path.exists(options.file):
        raise CommandError(f"No such file: {options.file}")

    try:
        with open(options.file, "r", encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except OSError as error:
        raise CommandError(f"Cannot read {options.file!r}: {error}")

    for number, line in enumerate(lines, start=1):
        try:
            session.shell.run_line(line, raise_errors=True)
        except CommandError as error:
            raise CommandError(f"{options.file}:{number}: {error}")


@command(
    "version",
    summary="Print the Peekmem and PyMemoryEditor versions.",
    usage="version",
    group="Session",
    details="The two lines to quote in a bug report, plus the platform.",
)
def cmd_version(session: Session, args: List[str]) -> None:
    CommandParser("version").parse_args(args)
    session.printer.write(
        f"Peekmem {__version__} / PyMemoryEditor {PyMemoryEditor.__version__} "
        f"/ Python {platform.python_version()} on {platform.system()} "
        f"({platform.machine()})"
    )
    session.printer.write()


@command(
    "exit",
    summary="Leave the shell.",
    usage="exit",
    group="Session",
    aliases=("quit", "\\q"),
    details="Detaches from the target first. Ctrl+D does the same thing.",
)
def cmd_exit(session: Session, args: List[str]) -> None:
    CommandParser("exit").parse_args(args)
    raise ExitShell(0)


__all__ = ()
