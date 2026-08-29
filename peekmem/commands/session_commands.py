# -*- coding: utf-8 -*-

"""Running the shell itself: ``help``, ``set``, ``source``, ``exit``."""

import os
import platform
from typing import List, Tuple

import PyMemoryEditor

from .. import __version__, valuetypes
from ..errors import CommandError, ExitShell
from ..output import (
    LEFT,
    RIGHT,
    render_definitions,
    render_paragraphs,
    render_table,
    render_vertical,
)
from ..session import SETTINGS, Session
from . import (
    Command,
    CommandParser,
    children,
    command,
    describe_action,
    lookup,
    namespace_summary,
    namespaces,
    top_level,
)

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


#: Width of the canonical-name column in a listing, so the alias column lines
#: up across every section rather than jumping about per namespace.
_NAME_WIDTH = 18

#: Width of the alias column, padded so every section of the overview lines up
#: as one grid instead of re-aligning per namespace.
_ALIAS_WIDTH = 9


def _command_rows(commands) -> List[Tuple[str, str]]:
    """Label/summary pairs for a command listing.

    The label carries both spellings in two aligned columns — the full name
    says where the command lives, the alias is what anybody actually types.
    """
    return [
        (
            f"{entry.name.ljust(_NAME_WIDTH)}  {entry.short.ljust(_ALIAS_WIDTH)}",
            entry.summary,
        )
        for entry in commands
    ]


def _print_overview(session: Session) -> None:
    """The top layer: the four subjects, and the words that drive the shell.

    Deliberately not a list of every command. Thirty-four lines is a wall to
    read past, not an answer; four namespaces and six commands is something you
    can take in, with one obvious move to get deeper.
    """
    printer = session.printer
    printer.write(f"Peekmem {__version__} — a terminal client for PyMemoryEditor.")
    printer.write()

    printer.write("Namespaces — type '<name>:help' to list what is in one:")
    printer.write(
        render_definitions(
            [(name, namespace_summary(name)) for name in namespaces()],
            label_width=10,
        )
    )
    printer.write()

    printer.write("Commands:")
    printer.write(
        render_definitions(
            [(entry.name, entry.summary) for entry in top_level()], label_width=10
        )
    )
    printer.write()

    printer.write(
        "Every command in a namespace also has a short alias: 'memory:read' "
        "and 'read'\nare the same command."
    )
    printer.write(
        "Type 'help <command>' — or '<command> --help' — for a command's "
        "arguments."
    )
    printer.write("Topics: 'help types', 'help address', 'help scanning'.")
    printer.write("End the session with 'exit', Ctrl+C, Ctrl+D, or \\q.")
    printer.write()


def print_namespace(session: Session, prefix: str) -> bool:
    """List the commands under ``prefix``. False when there are none.

    Used both by ``help memory`` and by typing ``memory`` at the prompt: in a
    namespaced shell, naming a group and being shown its contents is the
    obvious thing for that word to do.
    """
    entries = children(prefix)
    if not entries:
        return False

    head = prefix.strip().lower().rstrip(":")
    session.printer.write(f"Commands under '{head}:'")
    session.printer.write()
    session.printer.write(render_definitions(_command_rows(entries), label_width=30))
    session.printer.write()

    # Point at the next layer down rather than printing it here.
    for entry in entries:
        deeper = children(entry.name)
        if deeper:
            session.printer.write(
                f"'{entry.name}' has {len(deeper)} subcommands of its own — "
                f"type '{entry.name}:help'."
            )
            session.printer.write()
    return True


def _argument_sections(entry: Command) -> List[Tuple[str, List[Tuple[str, str]]]]:
    """Split a command's arguments into the sections ``help`` prints.

    Built from the very parser the command parses with, so the two cannot
    disagree: adding a flag adds it to the help, and changing what a flag is
    called changes it in both places at once.
    """
    positionals: List[Tuple[str, str]] = []
    options: List[Tuple[str, str]] = []

    for action in entry.arguments():
        label = describe_action(action)
        text = action.help or ""
        if action.option_strings:
            options.append((label, text))
        else:
            positionals.append((label, text))

    sections = []
    if positionals:
        sections.append(("Arguments", positionals))
    if options:
        sections.append(("Options", options))
    return sections


def _print_command_help(session: Session, name: str) -> None:
    entry = lookup(name)
    printer = session.printer

    printer.write(f"{entry.name} — {entry.summary}")
    printer.write()
    printer.write(f"Usage: {entry.usage}")
    if entry.aliases:
        printer.write(f"Aliases: {', '.join(entry.aliases)}")
    printer.write()

    for title, items in _argument_sections(entry):
        printer.write(f"{title}:")
        printer.write(render_definitions(items))
        printer.write()

    subcommands = children(entry.name)
    if subcommands:
        printer.write("Subcommands:")
        printer.write(render_definitions(_command_rows(subcommands), label_width=30))
        printer.write()

    if entry.details:
        printer.write(render_paragraphs(entry.details))
        printer.write()
    if entry.examples:
        printer.write("Examples:")
        for example in entry.examples:
            printer.write(f"  {example}")
        printer.write()


def _help_parser() -> CommandParser:
    parser = CommandParser("help")
    parser.add_argument(
        "topic",
        nargs="?",
        default=None,
        help="a command name, or one of the topics 'types', 'address' and "
        "'scanning'. Omit it to list every command",
    )
    return parser


@command(
    "help",
    parser=_help_parser,
    summary="List the commands, or describe one.",
    usage="help [command|types|address|scanning]",
    aliases=("?", "\\h"),
    details=(
        "With a command name, prints that command's usage, every argument and "
        "flag it accepts, and examples. Typing '<command> --help' does the "
        "same thing.\n\n"
        "The argument list is generated from the command's own parser, so it "
        "is always what the command actually accepts."
    ),
    examples=("help", "help scan", "help address"),
)
def cmd_help(session: Session, args: List[str]) -> None:
    options = _help_parser().parse_args(args)

    if options.topic is None:
        _print_overview(session)
        return

    topic = options.topic.strip().lower()

    # 'help pointer:' — the trailing colon asks for the namespace explicitly,
    # which matters for the two namespaces that are also command aliases.
    if topic.endswith(":") and print_namespace(session, topic):
        return

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

    # A bare namespace is not a command, so describe what is in it instead of
    # reporting that it does not exist.
    if topic in namespaces() and topic not in command_words_set():
        print_namespace(session, topic)
        return

    _print_command_help(session, topic)

    # 'scan' and 'pointer' are aliases *and* namespaces. The alias wins, so
    # say out loud that there is more under the same word.
    if topic in namespaces():
        count = len(children(topic))
        session.printer.write(
            f"'{topic}' is also a namespace holding {count} commands. "
            f"Type '{topic}:' to list them."
        )
        session.printer.write()


def command_words_set() -> set:
    """Every word that resolves to a command, for the namespace check above."""
    from . import command_words

    return set(command_words())


def _set_parser() -> CommandParser:
    parser = CommandParser("set")
    parser.add_argument(
        "assignment",
        nargs="*",
        default=[],
        help="'name value', 'name=value', or a bare 'name' to read one back. "
        "Omit it to print every setting",
    )
    return parser


@command(
    "set",
    parser=_set_parser,
    summary="Show or change a session setting.",
    usage="set [name [value]]",
    details=(
        "Settings live for the session only — Peekmem writes no config file, "
        "so a fresh shell always starts from the documented defaults. Put the "
        "'set' lines in a script and run it with 'source' to reuse a setup.\n\n"
        "Run 'set' with no argument to see every setting, its current value "
        "and what it does."
    ),
    examples=("set", "set limit 50", "set hex on", "set writable_only=true"),
)
def cmd_set(session: Session, args: List[str]) -> None:
    options = _set_parser().parse_args(args)
    assignment = options.assignment

    if not assignment:
        rows = [
            (setting.name, _format_setting(session.option(setting.name)), setting.summary)
            for setting in SETTINGS
        ]
        session.printer.table(
            ("SETTING", "VALUE", "DESCRIPTION"), rows, (LEFT, RIGHT, LEFT)
        )
        return

    if len(assignment) == 1 and "=" in assignment[0]:
        name, _, value = assignment[0].partition("=")
    elif len(assignment) == 1:
        name, value = assignment[0], None
    elif len(assignment) == 2:
        name, value = assignment[0], assignment[1]
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


def _source_parser() -> CommandParser:
    parser = CommandParser("source")
    parser.add_argument(
        "file",
        help="a text file of commands, one per line; blank lines and lines "
        "starting with '#' or '--' are ignored",
    )
    return parser


@command(
    "source",
    parser=_source_parser,
    summary="Run the commands in a file.",
    usage="source <file>",
    aliases=("\\.",),
    details=(
        "Reads the file and runs each line as if it had been typed.\n\n"
        "A failing line stops the script — a setup that half-ran is worse than "
        "one that says where it stopped."
    ),
    examples=("source setup.peek",),
)
def cmd_source(session: Session, args: List[str]) -> None:
    options = _source_parser().parse_args(args)

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


def _clear_parser() -> CommandParser:
    return CommandParser("clear")


@command(
    "clear",
    parser=_clear_parser,
    summary="Clear the terminal.",
    usage="clear",
    aliases=("cls",),
    details=(
        "Takes no arguments.\n\n"
        "Wipes the screen and the scrollback, the way the shell's own 'clear' "
        "does. Nothing about the session changes: the process stays attached, "
        "the scan results and pointer paths are all still there.\n\n"
        "To discard the scan results instead, that is 'reset' "
        "(scan:results:clear).\n\n"
        "Does nothing when the output is redirected — escape codes in a log "
        "file would be vandalism rather than tidying."
    ),
)
def cmd_clear(session: Session, args: List[str]) -> None:
    _clear_parser().parse_args(args)
    session.printer.clear_screen()


def _version_parser() -> CommandParser:
    return CommandParser("version")


@command(
    "version",
    parser=_version_parser,
    summary="Print the Peekmem and PyMemoryEditor versions.",
    usage="version",
    details=(
        "Takes no arguments.\n\n"
        "The one line to quote in a bug report: it names Peekmem, "
        "PyMemoryEditor, Python and the platform."
    ),
)
def cmd_version(session: Session, args: List[str]) -> None:
    _version_parser().parse_args(args)
    session.printer.write(
        f"Peekmem {__version__} / PyMemoryEditor {PyMemoryEditor.__version__} "
        f"/ Python {platform.python_version()} on {platform.system()} "
        f"({platform.machine()})"
    )
    session.printer.write()


def _exit_parser() -> CommandParser:
    return CommandParser("exit")


@command(
    "exit",
    parser=_exit_parser,
    summary="Leave the shell.",
    usage="exit",
    aliases=("quit", "\\q"),
    details=(
        "Takes no arguments.\n\n"
        "Detaches from the target first. Ctrl+C and Ctrl+D at the prompt do "
        "the same thing, except for the status they exit with: 130 for "
        "Ctrl+C, the conventional 'interrupted' value, and 0 for the other "
        "two.\n\n"
        "Ctrl+C means something different *during* a command — it abandons "
        "that command and returns to the prompt, keeping whatever a scan had "
        "already found. So interrupting a scan costs one keystroke and "
        "leaving costs two."
    ),
)
def cmd_exit(session: Session, args: List[str]) -> None:
    _exit_parser().parse_args(args)
    raise ExitShell(0)


__all__ = ()
