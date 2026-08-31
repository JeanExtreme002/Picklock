# -*- coding: utf-8 -*-

"""
The command registry.

Every Picklock command is a plain function registered with :func:`command`.
The registry owns the name, the aliases, the one-line summary, the usage line
and — through :class:`CommandParser` — the full argument list, which means
``help`` is generated from the very definitions the dispatcher runs. A flag
cannot be added without being documented, and documentation cannot drift from
the parser, because there is only one of them.

Importing this package imports every command module for its side effect of
registering; nothing else needs to know they exist.
"""

import argparse
import difflib
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from ..errors import CommandError


@dataclass(frozen=True)
class Namespace:
    """One subject the commands are grouped under."""

    name: str
    title: str
    summary: str
    #: A worked example for the namespace's help — a line someone would type
    #: and what comes back. Indented by the renderer, so write it flush left.
    example: str = ""


#: Namespaces in the order ``help`` prints them, each with the heading it gets
#: and the one line that says what it is for. A command's namespace is the part
#: of its name before the first colon, so the grouping cannot drift from the
#: naming — there is nothing to keep in step.
#:
#: Commands about the shell itself (``help``, ``set``, ``exit`` …) deliberately
#: have no namespace. They are not a subject you go looking through; they are
#: the handful of words you type between doing real work, and burying them one
#: level down would cost more than the tidiness is worth.
NAMESPACES: Tuple[Namespace, ...] = (
    Namespace(
        "ps",
        "Process",
        "Find a target process, attach to it, and see what it is.",
        "picklock> ps:list chrome\n"
        "\n"
        "+-------+------------+\n"
        "| PID   | NAME       |\n"
        "+-------+------------+\n"
        "| 41902 | chrome.exe |\n"
        "+-------+------------+\n"
        "1 row in set (0.01 sec)",
    ),
    Namespace(
        "memory",
        "Memory",
        "Read, write and inspect the target's memory.",
        "picklock> memory:read game.exe+0x1234 int32\n"
        "\n"
        "+--------------------+-------+-------+\n"
        "| ADDRESS            | TYPE  | VALUE |\n"
        "+--------------------+-------+-------+\n"
        "| 0x00007FF6A41B1234 | int32 | 100   |\n"
        "+--------------------+-------+-------+\n"
        "1 row in set (0.00 sec)",
    ),
    Namespace(
        "scan",
        "Scanning",
        "Search memory for a value, then narrow what you found.",
        "picklock> scan:value int32 100 --writable\n"
        "Showing 20 of 3184 rows — writable regions only (1.42 sec)\n"
        "\n"
        "picklock> scan:next 95\n"
        "+-----+--------------------+-------+\n"
        "| ROW | ADDRESS            | VALUE |\n"
        "+-----+--------------------+-------+\n"
        "|  #1 | 0x00000201A4C0F118 | 95    |\n"
        "+-----+--------------------+-------+\n"
        "1 row in set (0.02 sec)",
    ),
    Namespace(
        "alias",
        "Aliases",
        "Give a command a shorter name of your own.",
        "picklock> alias:add r memory:read\n"
        "r = memory:read\n"
        "\n"
        "picklock> alias:add find-text scan:value string\n"
        "find-text = scan:value string\n"
        "\n"
        "picklock> find-text Picklock\n"
        "(runs 'scan:value string Picklock')",
    ),
    Namespace(
        "config",
        "Configuration",
        "Show or change how Picklock behaves.",
        "picklock> config:set writable_only on\n"
        "writable_only = on\n"
        "\n"
        "picklock> config:list\n"
        "\n"
        "+---------+-------+------------------------------------+\n"
        "| SETTING | VALUE | DESCRIPTION                        |\n"
        "+---------+-------+------------------------------------+\n"
        "| limit   |    20 | Rows printed per result table ...  |\n"
        "+---------+-------+------------------------------------+",
    ),
    Namespace(
        "pointer",
        "Pointers",
        "Follow pointer chains, and find ones that survive a restart.",
        "picklock> pointer:scan #1 --depth 3\n"
        "+-----+-------------------+---------+--------------------+\n"
        "| ROW | BASE              | OFFSETS | TARGET             |\n"
        "+-----+-------------------+---------+--------------------+\n"
        "|  #1 | game.exe+0x3BA228 | 0x3E8   | 0x00000201A4C0F118 |\n"
        "+-----+-------------------+---------+--------------------+\n"
        "1 row in set (6.18 sec)",
    ),
)

_NAMESPACES_BY_NAME: Dict[str, Namespace] = {item.name: item for item in NAMESPACES}
_NAMESPACE_TITLES: Dict[str, str] = {item.name: item.title for item in NAMESPACES}
_NAMESPACE_ORDER: Dict[str, int] = {
    item.name: index for index, item in enumerate(NAMESPACES)
}

Handler = Callable[..., None]

#: A zero-argument factory returning the command's configured parser. It is a
#: factory rather than a shared instance because ``help`` and a running command
#: both want one, and an ``ArgumentParser`` accumulates state as it parses.
ParserFactory = Callable[[], "CommandParser"]


class CommandParser(argparse.ArgumentParser):
    """An ``ArgumentParser`` that raises instead of killing the shell.

    ``argparse`` calls ``sys.exit`` on a usage error, which is right for a
    program and fatal for a REPL. Every failure becomes a
    :class:`~picklock.errors.CommandError`, printed as one ``ERROR:`` line.

    It also keeps the actions it was given, in the order they were declared, so
    ``help`` can list a command's arguments without reaching into argparse's
    internals. ``Action.option_strings``, ``.dest``, ``.nargs``, ``.metavar``,
    ``.choices`` and ``.help`` are all documented attributes.
    """

    def __init__(self, prog: str, usage: Optional[str] = None):
        super().__init__(prog=prog, usage=usage, add_help=False)
        self.arguments: List[argparse.Action] = []

    def add_argument(self, *args, **kwargs):
        action = super().add_argument(*args, **kwargs)
        self.arguments.append(action)
        return action

    def add_mutually_exclusive_group(self, **kwargs):
        """A group whose arguments the parser still knows about.

        argparse hands a group its own ``add_argument``, which would bypass the
        list above — and the help is built from that list, so a whole set of
        flags would exist and be documented nowhere. The proxy records them as
        the parser's own, which is what they are.
        """
        return _ExclusiveGroup(self, super().add_mutually_exclusive_group(**kwargs))

    def error(self, message: str) -> None:  # type: ignore[override]
        raise CommandError(f"{self.prog}: {message} (try 'help {self.prog}')")

    def exit(self, status: int = 0, message: Optional[str] = None) -> None:  # type: ignore[override]
        if message:
            raise CommandError(message.strip())
        raise CommandError(f"{self.prog}: invalid arguments (try 'help {self.prog}')")


class _ExclusiveGroup:
    """Records a mutually exclusive group's arguments on the parser."""

    def __init__(self, parser: "CommandParser", group: Any):
        self._parser = parser
        self._group = group

    def add_argument(self, *args, **kwargs) -> argparse.Action:
        action = self._group.add_argument(*args, **kwargs)
        self._parser.arguments.append(action)
        return action


def describe_action(action: argparse.Action) -> str:
    """Render one argument the way it is typed on the command line.

    Positionals come out as ``address``, ``[length]`` or ``[offset ...]``
    depending on how many are accepted; options come out as
    ``-i, --ignore-case`` or ``--between A B``. The point is that the label in
    the help is something the reader can copy.
    """
    value = _value_placeholder(action)

    if not action.option_strings:
        name = value or (action.metavar or action.dest)
        if action.nargs == "?":
            return f"[{name}]"
        if action.nargs == "*":
            return f"[{name} ...]"
        if action.nargs == "+":
            return f"{name} [{name} ...]"
        return str(name)

    flags = ", ".join(action.option_strings)
    return f"{flags} {value}" if value else flags


def usage_token(action: argparse.Action) -> str:
    """Render one argument as it appears in a ``usage:`` line.

    Positionals come out as ``<address>`` or ``[length]``, options as
    ``[--limit N]``. Long flags win over short ones: a usage line is read, not
    typed, and ``--ignore-case`` says what it does where ``-i`` does not.
    """
    value = _value_placeholder(action)

    if not action.option_strings:
        name = action.metavar or action.dest
        if isinstance(name, tuple):
            name = " ".join(name)
        if action.nargs == "?":
            return f"[{name}]"
        if action.nargs == "*":
            return f"[{name} ...]"
        if action.nargs == "+":
            return f"<{name}> [{name} ...]"
        return f"<{name}>"

    flag = next(
        (item for item in action.option_strings if item.startswith("--")),
        action.option_strings[0],
    )
    return f"[{flag} {value}]" if value else f"[{flag}]"


def _value_placeholder(action: argparse.Action) -> str:
    """The ``VALUE`` part of ``--flag VALUE``, or '' for a flag that takes none."""
    if action.nargs == 0:  # store_true / store_false
        return ""

    if action.metavar is not None:
        if isinstance(action.metavar, tuple):
            return " ".join(action.metavar)
        return action.metavar

    if action.choices:
        return "|".join(str(choice) for choice in action.choices)

    name = action.dest if not action.option_strings else action.dest.upper()
    if isinstance(action.nargs, int):
        return " ".join([name] * action.nargs)
    return name


@dataclass(frozen=True)
class Command:
    """One registered command.

    The ``name`` is a colon-separated path — ``memory:read``,
    ``scan:keep`` — so related commands sort and group together and a
    name says what it acts on. The short spellings people actually type
    (``read``, ``keep``) are registered as aliases, which is why the hierarchy
    costs nothing at the keyboard.
    """

    name: str
    handler: Handler
    summary: str
    parser: Optional[ParserFactory] = None
    aliases: Tuple[str, ...] = ()
    details: str = ""
    examples: Tuple[str, ...] = field(default=())

    @property
    def usage(self) -> str:
        """The usage line, built from the parser.

        Generated rather than written by hand, because a hand-written one drifts:
        three commands had grown flags their usage line never mentioned. There is
        now nothing to keep in step — a flag that exists is a flag that shows.
        """
        return " ".join([self.name] + [usage_token(a) for a in self.arguments()])

    @property
    def namespace(self) -> str:
        """The first segment of the name, or ``""`` for a top-level command."""
        return self.name.split(":", 1)[0] if ":" in self.name else ""

    @property
    def is_top_level(self) -> bool:
        """True for the shell's own commands, which live outside any namespace."""
        return ":" not in self.name

    @property
    def group(self) -> str:
        """The heading ``help`` files this command under."""
        if self.is_top_level:
            return "Commands"
        return _NAMESPACE_TITLES.get(self.namespace, self.namespace.capitalize())

    def arguments(self) -> List[argparse.Action]:
        """Every argument this command accepts, in declaration order."""
        return list(self.parser().arguments) if self.parser is not None else []


_COMMANDS: Dict[str, Command] = {}
_ALIASES: Dict[str, str] = {}


def command(
    name: str,
    *,
    summary: str,
    parser: Optional[ParserFactory] = None,
    aliases: Sequence[str] = (),
    details: str = "",
    examples: Sequence[str] = (),
) -> Callable[[Handler], Handler]:
    """Register a command handler.

    The handler is called as ``handler(session, args)`` where ``args`` is the
    already-split argument list (the command word removed).

    ``parser`` is the factory returning the same :class:`CommandParser` the
    handler parses with. Passing it is what puts the command's arguments in
    ``help``, so every command has one — even the few whose parser only
    declares that they take nothing.
    """

    def decorator(handler: Handler) -> Handler:
        if name in _COMMANDS or name in _ALIASES:
            raise RuntimeError(f"Duplicate command name: {name}")
        if ":" in name and name.split(":", 1)[0] not in _NAMESPACE_TITLES:
            raise RuntimeError(f"Unknown namespace in command name: {name}")
        # Two levels, deliberately. A third — 'scan:results:keep' — buys a
        # tidier name at the cost of a listing that has to be walked twice to
        # be read once, which is a bad trade for six commands.
        if name.count(":") > 1:
            raise RuntimeError(
                f"Command names go at most one level deep: {name}"
            )

        entry = Command(
            name=name,
            handler=handler,
            summary=summary,
            parser=parser,
            aliases=tuple(aliases),
            details=details,
            examples=tuple(examples),
        )
        _COMMANDS[name] = entry
        for alias in entry.aliases:
            if alias in _ALIASES or alias in _COMMANDS:
                raise RuntimeError(f"Duplicate command alias: {alias}")
            _ALIASES[alias] = name
        return handler

    return decorator


def lookup(name: str) -> Command:
    """Resolve a command word, suggesting a near miss when there is one."""
    key = name.strip().lower()
    if key in _COMMANDS:
        return _COMMANDS[key]
    if key in _ALIASES:
        return _COMMANDS[_ALIASES[key]]

    candidates = difflib.get_close_matches(key, list(_COMMANDS) + list(_ALIASES), 1)
    hint = f" Did you mean {candidates[0]!r}?" if candidates else ""
    raise CommandError(
        f"Unknown command {name!r}.{hint} Type 'help' for the command list."
    )


def all_commands() -> List[Command]:
    """Every registered command, in namespace order then alphabetically.

    Top-level commands sort last, because that is where ``help`` prints them:
    after the subjects, as the short list of words for driving the shell.
    """
    return sorted(
        _COMMANDS.values(),
        key=lambda entry: (_NAMESPACE_ORDER.get(entry.namespace, 99), entry.name),
    )


def top_level() -> List[Command]:
    """The commands that live outside any namespace."""
    return [entry for entry in all_commands() if entry.is_top_level]


def top_level_listing() -> List[Tuple[str, str]]:
    """Every word you can type first, as ``(name, summary)`` pairs.

    Names only — no arguments, no flags. This listing answers "what is there?",
    and an answer to that question is not improved by also answering "and what
    does each one take?", which is what ``<command>:help`` is for.

    The distinction the code keeps — a namespace is a prefix, a command is a
    thing that runs — is not one the reader has to carry. To them ``ps`` and
    ``clear`` are both commands, listed side by side under one heading; typing
    either one is how you find out that the first has more underneath.
    """
    rows = [(name, namespace_summary(name)) for name in namespaces()]
    rows += [(entry.name, entry.summary) for entry in top_level()]
    return sorted(rows)


def namespace(name: str) -> Optional[Namespace]:
    """The declared namespace called ``name``, if there is one."""
    return _NAMESPACES_BY_NAME.get(name.strip().lower().rstrip(":"))


def namespace_summary(name: str) -> str:
    """The one line describing a namespace, for the top-level help."""
    entry = namespace(name)
    return entry.summary if entry else ""


def children(prefix: str) -> List[Command]:
    """The commands in the namespace ``prefix``.

    Names go two levels deep at most, so this is always "the commands in a
    namespace" — there is no deeper layer to walk.
    """
    head = prefix.strip().lower().rstrip(":")
    if not head:
        return []
    return [entry for entry in all_commands() if entry.namespace == head]


def namespaces() -> List[str]:
    """Every namespace that has at least one command registered in it."""
    known = {entry.namespace for entry in _COMMANDS.values()}
    return [item.name for item in NAMESPACES if item.name in known]


def command_words() -> List[str]:
    """Every accepted command word, for tab completion."""
    return sorted(list(_COMMANDS) + list(_ALIASES))


def option_words(name: str) -> List[str]:
    """Every option flag a command accepts, for tab completion."""
    try:
        entry = lookup(name)
    except CommandError:
        return []
    return sorted(
        flag for action in entry.arguments() for flag in action.option_strings
    )


@dataclass(frozen=True)
class Page:
    """One page of a longer listing, and where it sits in the whole."""

    rows: List[Any]
    #: Rows in the full listing, not just this page.
    total: int
    #: Which page this is, counting from 1.
    number: int = 1
    #: How many pages the listing has in total.
    count: int = 1
    #: Index of the first row on this page, for numbering result rows.
    offset: int = 0
    #: The command line that shows the following page, or ``None`` at the end.
    next_page: Optional[str] = None


def add_paging_arguments(parser: CommandParser) -> CommandParser:
    """Give a listing command the same three paging flags as every other one.

    Declared in one place so the wording, the behaviour and the help text
    cannot drift between commands — a listing that pages differently from its
    neighbour is a listing you have to learn twice.

    Short forms because these three are the most-typed flags in the tool: every
    listing has them, and paging through one means typing the same flag again
    and again.
    """
    parser.add_argument(
        "-l",
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="rows per page, overriding the 'limit' setting",
    )
    parser.add_argument(
        "-p",
        "--page",
        type=int,
        default=1,
        metavar="N",
        help="which page to show, counting from 1",
    )
    parser.add_argument(
        "-a",
        "--all",
        action="store_true",
        help="print every row, ignoring the limit",
    )
    return parser


def paginate(
    session: Any,
    entries: Sequence[Any],
    *,
    command: str,
    limit: Optional[int] = None,
    page: int = 1,
    show_all: bool = False,
) -> Page:
    """Cut ``entries`` down to one page, and say where that page sits.

    Pages rather than offsets, because "page 3 of 12" is a place a reader can
    hold in their head and ``--offset 40`` is arithmetic they have to do.
    ``command`` is what they would type to move on; it is spelled out in the
    footer so the next page is a copy-paste rather than a puzzle.
    """
    # Checked here rather than per command, so every listing agrees — and
    # because a negative limit is not merely odd: it reaches a Python slice as
    # `entries[0:-5]`, which quietly prints all but the last five rows and
    # calls it a page. `config:set limit` has always refused one.
    if limit is not None and limit < 0:
        raise CommandError("--limit cannot be negative (0 means no limit).")

    total = len(entries)
    size = None if show_all else session.display_limit(limit)

    if size is None:
        return Page(list(entries), total, 1, 1, 0)

    pages = max(1, -(-total // size))  # Ceiling division: a part page counts.
    if page < 1:
        raise CommandError("--page counts from 1.")
    if page > pages:
        raise CommandError(
            f"Page {page} does not exist — this listing has "
            f"{pages} page{'' if pages == 1 else 's'}."
        )

    offset = (page - 1) * size
    window = list(entries[offset : offset + size])

    next_page = None
    if page < pages:
        next_page = f"{command} --page {page + 1}"
        if limit is not None:
            next_page += f" --limit {limit}"

    return Page(window, total, page, pages, offset, next_page)


from . import alias_commands  # noqa: E402,F401  (registration side effect)
from . import memory_commands  # noqa: E402,F401
from . import pointer_commands  # noqa: E402,F401
from . import ps_commands  # noqa: E402,F401
from . import scan_commands  # noqa: E402,F401
from . import session_commands  # noqa: E402,F401

__all__ = (
    "Command",
    "CommandParser",
    "NAMESPACES",
    "Namespace",
    "Page",
    "add_paging_arguments",
    "all_commands",
    "children",
    "command",
    "command_words",
    "describe_action",
    "lookup",
    "namespace",
    "namespace_summary",
    "namespaces",
    "option_words",
    "paginate",
    "usage_token",
    "top_level",
    "top_level_listing",
)
