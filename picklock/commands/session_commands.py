# -*- coding: utf-8 -*-

"""Running the shell itself: ``help``, ``set``, ``source``, ``exit``."""

import os
import platform
import textwrap
from typing import List, Tuple

import PyMemoryEditor

from .. import __version__, store, valuetypes
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
    namespace,
    namespaces,
    top_level_listing,
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
enough: 'game' finds 'game.exe'. Run 'memory:modules' to list them, and to
refresh the table after the target loads a library.

'module+offset' is the form worth writing down: a module's base moves on every
launch under ASLR, but the offset inside it does not, so the expression keeps
working across restarts where a bare address does not.\
"""

_SCANNING_TOPIC = """\
The scan / refine cycle, when you do not know the address:

  1. scan:value int32 100    every address holding 100 right now
  2. (make the value change in the target)
  3. scan:next 95            of those, the ones now holding 95

Repeat step 3 until a handful of rows remain. When you cannot see the value —
a health bar with no number — compare against the previous reading instead:

  scan:next --changed / scan:next --unchanged
  scan:next --increased / scan:next --decreased

Every comparison is a flag, so the value slot only ever holds a value:
'scan:next changed' looks for the word "changed", and '--changed' is the
comparison. The rest take a value of their own:

  scan:next --gt 50 / scan:next --between 10 20
  scan:next --increased-by 5

'scan:results' is how you look at where you are between rounds. It re-reads
every address, so VALUE is what the target holds now rather than what the scan
found, and PREVIOUS shows the reading the comparisons above are measured
against. A scan only previews its first page; this is what reaches the rest:

  scan:results              the first page, re-read
  scan:results --page 2     the next one
  scan:results --all        every row, however many

When you can see which rows are real, say so directly instead of inventing a
comparison that happens to exclude the others:

  scan:keep 1 4 7-9         keep those, drop the rest
  scan:drop 2               the other way round

Then read, write or watch a surviving row by number:

  memory:read #1 int32
  memory:write #1 int32 999
  memory:watch #1 int32

An address found this way is good for this run only. To keep it, find the
pointer path that reaches it: 'pointer:scan #1', then 'pointer:save', restart
the target, and 'pointer:rescan' against the value's new address. See
'help pointer:scan'.\
"""

_TOPICS = {
    "address": ("Writing an address", _ADDRESS_TOPIC),
    "addresses": ("Writing an address", _ADDRESS_TOPIC),
    "scanning": ("The scan / refine cycle", _SCANNING_TOPIC),
}


#: The file the changed settings live in, beside the aliases.
_SETTINGS_FILE = "settings.json"


def restore(session: Session) -> List[str]:
    """Load the stored settings into ``session``; return the ones dropped.

    A name or a value the current release no longer accepts is left out rather
    than allowed to fail later — a setting renamed between versions should cost
    one line of explanation, not a confusing error the first time it is used.
    """
    dropped = []
    for name, value in sorted(store.load(_SETTINGS_FILE).items()):
        try:
            session.set_option(str(name), str(value))
        except CommandError:
            dropped.append(str(name))
    return dropped


def _persist(session: Session) -> None:
    """Write the settings that differ from their defaults.

    Only the differences, so the file stays a record of what *you* changed: a
    default that moves in a later release then reaches you, instead of being
    pinned forever by a value you never chose.
    """
    changed = {
        setting.name: _format_setting(session.option(setting.name))
        for setting in SETTINGS
        if session.option(setting.name) != setting.default
    }
    try:
        store.save(_SETTINGS_FILE, changed)
    except OSError as error:
        session.printer.note(
            f"Could not save to {store.path(_SETTINGS_FILE)}: {error}. "
            "The change holds for this session only."
        )


def _find_setting(name: str):
    """Look up a setting by name, listing the real ones when it is not one."""
    setting = {item.name: item for item in SETTINGS}.get(name.strip().lower())
    if setting is None:
        known = ", ".join(item.name for item in SETTINGS)
        raise CommandError(f"Unknown setting {name!r}. Known settings: {known}.")
    return setting


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


#: Widest an argument signature gets in a listing before it is cut short. The
#: listing exists to show you what a command is *called* and roughly what it
#: takes; the full argument list is one 'help <command>' away, so a signature
#: long enough to push every summary off the screen has stopped helping.
_SIGNATURE_WIDTH = 44

#: Overall width these listings wrap to. Wider than the 78 used elsewhere
#: because a signature plus a summary genuinely needs the room.
_LISTING_WIDTH = 106

#: Spaces between a command and its description. Wider than the two an
#: argument list uses: a listing of commands is scanned down its left edge
#: first, and the gap is what stops the two columns reading as one sentence.
_LISTING_GAP = 4


def _signature(entry: Command, limit: int = _SIGNATURE_WIDTH) -> str:
    """The command's usage line, cut at a token boundary when it runs long."""
    usage = " ".join(entry.usage.split())
    if len(usage) <= limit:
        return usage

    kept: List[str] = []
    length = 0
    for token in usage.split(" "):
        if kept and length + 1 + len(token) > limit - 3:
            break
        length += (1 if kept else 0) + len(token)
        kept.append(token)
    return " ".join(kept) + "..."


def _command_rows(commands) -> List[Tuple[str, str]]:
    """Signature/summary pairs for a command listing.

    The signature rather than the bare name, so the listing answers "what does
    this take?" at the same time as "what is it called" — the shape dokku's
    plugin help uses, and the reason its listings are worth reading straight
    through.
    """
    return [(_signature(entry), entry.summary) for entry in commands]


def _print_example(session: Session, example: str, *, indent: int = 0) -> None:
    """Print an indented ``Example:`` block, verbatim but dimmed.

    The label stays at full strength so the block is findable when skimming;
    its contents take the same shade as the prompt's target, because they mean
    the same thing — context around the output rather than output itself.

    ``indent`` nests the whole block, which is how the top-level help tucks its
    example inside the command listing rather than floating it above.
    """
    if not example:
        return
    printer = session.printer
    pad = " " * indent
    printer.write(f"{pad}Example:")
    printer.write()
    for line in example.splitlines():
        # Styled a line at a time: one escape spanning a whole block survives
        # neither a pager nor a terminal that reflows it.
        printer.write(f"{pad}    {printer.dim(line)}" if line else "")
    printer.write()


def _print_overview(session: Session) -> None:
    """The top layer: every word you can type first, and nothing below it.

    Deliberately not a list of all thirty-odd commands. A wall is not an
    answer; ten lines is something you can take in, with one obvious move to
    get deeper — and a command that takes a subcommand says so in its
    signature rather than in a paragraph about namespaces.
    """
    printer = session.printer

    # What this is, before how to type it: the first line of the first page a
    # new reader sees should say what they are looking at.
    printer.write(f"Picklock {__version__} — a terminal client for PyMemoryEditor.")
    printer.write()
    printer.write("usage: COMMAND[:SUBCOMMAND] [arguments]")
    printer.write()

    printer.write('picklock commands: (get help with "help <command>")')
    printer.write()
    printer.write(
        render_definitions(
            top_level_listing(),
            indent=4,
            label_width=12,
            total_width=_LISTING_WIDTH,
            gap=_LISTING_GAP,
        )
    )
    printer.write()

    # The example sits inside the listing: it is what typing one of these
    # looks like, not a preamble to the page.
    _print_example(
        session,
        "picklock> ps:open 4242\n"
        "Attached to game.exe (PID 4242, 64-bit). (0.00 sec)\n"
        "\n"
        "picklock> scan:value int32 100 --writable\n"
        "Showing 20 of 3184 rows — page 1 of 160 — writable regions only "
        "(1.42 sec)",
        indent=4,
    )

    printer.write("Topics: 'help types', 'help address', 'help scanning'.")
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
    printer = session.printer

    printer.write(f"usage: {head}[:SUBCOMMAND]")
    printer.write()

    declared = namespace(head)
    if declared is not None:
        printer.write(declared.summary)
        printer.write()
        _print_example(session, declared.example)

    printer.write(f'{head} subcommands: (get help with "help {head}:SUBCOMMAND")')
    printer.write()
    printer.write(
        render_definitions(
            _command_rows(entries),
            indent=4,
            label_width=_SIGNATURE_WIDTH,
            total_width=_LISTING_WIDTH,
            gap=_LISTING_GAP,
        )
    )
    printer.write()
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
    # A generated usage line lists every flag, so it can outrun the terminal.
    # Wrap it under a hanging indent rather than letting the terminal fold it
    # at an arbitrary column.
    printer.write(
        textwrap.fill(
            f"Usage: {entry.usage}",
            width=_LISTING_WIDTH,
            subsequent_indent="       ",
            break_long_words=False,
            break_on_hyphens=False,
        )
    )
    if entry.aliases:
        printer.write(f"Aliases: {', '.join(entry.aliases)}")
    printer.write()

    for title, items in _argument_sections(entry):
        printer.write(f"{title}:")
        printer.write(render_definitions(items))
        printer.write()

    if entry.details:
        printer.write(render_paragraphs(entry.details))
        printer.write()
    if entry.examples:
        printer.write("Examples:")
        for example in entry.examples:
            printer.write(f"  {printer.dim(example)}")
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

    # 'help r' where r is an alias: describe what it stands for. Anyone who
    # named a command is entitled to ask about it by the name they gave it.
    if topic in session.aliases:
        stands_for = session.aliases[topic]
        session.printer.write(
            f"{topic} is an alias for '{' '.join(stands_for)}'."
        )
        session.printer.write()
        _print_command_help(session, stands_for[0])
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


def _config_list_parser() -> CommandParser:
    return CommandParser("config:list")


@command(
    "config:list",
    parser=_config_list_parser,
    summary="Show the settings and their current values.",
    details=(
        "Takes no arguments — the whole table, every time. There are eight of "
        "them and they fit on a screen, so picking one out would be a filter "
        "for a list that does not need filtering.\n\n"
        "A change is remembered between runs, so the shell comes back the way "
        "you left it. Only what you changed is stored, so a default that moves "
        "in a later release still reaches you — and 'config:reset' puts one "
        "back, which restarting no longer does.\n\n"
        "The path is printed under the table."
    ),
)
def cmd_config_list(session: Session, args: List[str]) -> None:
    _config_list_parser().parse_args(args)

    rows = [
        (setting.name, _format_setting(session.option(setting.name)), setting.summary)
        for setting in SETTINGS
    ]
    session.printer.table(("SETTING", "VALUE", "DESCRIPTION"), rows, (LEFT, RIGHT, LEFT))
    session.printer.write(f"Stored in {store.path(_SETTINGS_FILE)}")
    session.printer.write()


def _config_set_parser() -> CommandParser:
    parser = CommandParser("config:set")
    parser.add_argument(
        "name", help="the setting to change; 'name=value' in one word also works"
    )
    parser.add_argument(
        "value",
        nargs="?",
        default=None,
        help="its new value — on/off for a switch, a number otherwise",
    )
    return parser


@command(
    "config:set",
    parser=_config_set_parser,
    summary="Change one of the settings.",
    details=(
        "'config:set limit 50' and 'config:set limit=50' do the same thing.\n\n"
        "The change lasts for the session and no longer. Run 'config:list' to "
        "see what can be set, and what each one does."
    ),
    examples=(
        "config:set limit 50",
        "config:set hex on",
        "config:set writable_only=true",
    ),
)
def cmd_config_set(session: Session, args: List[str]) -> None:
    options = _config_set_parser().parse_args(args)

    name, value = options.name, options.value
    if value is None:
        if "=" not in name:
            raise CommandError(
                f"config:set needs a value: 'config:set {name} <value>'. "
                f"To see what {name} is now, use 'config:list'."
            )
        name, _, value = name.partition("=")

    _find_setting(name)  # Reject an unknown name before parsing its value.
    applied = session.set_option(name, value)
    _persist(session)
    session.printer.ok(f"{name.strip().lower()} = {_format_setting(applied)}")
    session.printer.write()


def _config_reset_parser() -> CommandParser:
    parser = CommandParser("config:reset")
    parser.add_argument(
        "name",
        nargs="?",
        default=None,
        help="the setting to put back; omit it to reset every one",
    )
    return parser


@command(
    "config:reset",
    parser=_config_reset_parser,
    summary="Put a setting back to its default.",
    details=(
        "Settings are remembered between runs, so restarting no longer undoes "
        "one. This is what undoes it — for a single setting, or for all of "
        "them at once.\n\n"
        "A setting back at its default is dropped from the stored file rather "
        "than written out as a default, so a default that moves in a later "
        "release reaches you."
    ),
    examples=("config:reset limit", "config:reset"),
)
def cmd_config_reset(session: Session, args: List[str]) -> None:
    options = _config_reset_parser().parse_args(args)

    if options.name is not None:
        setting = _find_setting(options.name)
        session.set_option(setting.name, _format_setting(setting.default))
        _persist(session)
        session.printer.ok(
            f"{setting.name} = {_format_setting(setting.default)} (the default)"
        )
        session.printer.write()
        return

    for setting in SETTINGS:
        session.set_option(setting.name, _format_setting(setting.default))
    _persist(session)
    session.printer.ok(f"All {len(SETTINGS)} settings are back to their defaults.")
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
    aliases=("\\.",),
    details=(
        "Reads the file and runs each line as if it had been typed.\n\n"
        "A failing line stops the script — a setup that half-ran is worse than "
        "one that says where it stopped."
    ),
    examples=("source setup.txt",),
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

    with session.sourcing(options.file):
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
    aliases=("cls",),
    details=(
        "Takes no arguments.\n\n"
        "Wipes the screen and the scrollback, the way the shell's own 'clear' "
        "does. Nothing about the session changes: the process stays attached, "
        "the scan results and pointer paths are all still there.\n\n"
        "To discard the scan results instead, that is 'reset' "
        "(scan:reset).\n\n"
        "Does nothing when the output is redirected — escape codes in a log "
        "file would be vandalism rather than tidying."
    ),
)
def cmd_clear(session: Session, args: List[str]) -> None:
    _clear_parser().parse_args(args)
    session.printer.clear_screen()


def version_report() -> str:
    """The four facts a bug report needs.

    One function for both spellings: the 'version' command inside the shell and
    'picklock --version' outside it should not be able to disagree about what
    is installed.
    """
    return render_vertical(
        [
            ("Picklock", __version__),
            ("PyMemoryEditor", PyMemoryEditor.__version__),
            ("Python", platform.python_version()),
            (
                "Platform",
                f"{platform.system()} {platform.release()} ({platform.machine()})",
            ),
        ]
    )


def _version_parser() -> CommandParser:
    return CommandParser("version")


@command(
    "version",
    parser=_version_parser,
    summary="Print the Picklock, PyMemoryEditor, Python and platform versions.",
    details=(
        "Takes no arguments.\n\n"
        "The four lines to quote in a bug report. Picklock is a client, so which "
        "PyMemoryEditor is underneath matters as much as which Picklock is on "
        "top — the two move independently."
    ),
)
def cmd_version(session: Session, args: List[str]) -> None:
    _version_parser().parse_args(args)
    session.printer.write(version_report())
    session.printer.write()


def _exit_parser() -> CommandParser:
    return CommandParser("exit")


@command(
    "exit",
    parser=_exit_parser,
    summary="Leave the shell.",
    aliases=("quit",),
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
