# -*- coding: utf-8 -*-

"""
The command registry.

Every Peekmem command is a plain function registered with :func:`command`.
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
from typing import Callable, Dict, List, Optional, Sequence, Tuple

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
        "process",
        "Process",
        "Find a target process and attach to it.",
        "peekmem> process:list chrome\n"
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
        "peekmem> memory:read game.exe+0x1234 int32\n"
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
        "peekmem> scan:value int32 100 --writable\n"
        "Showing 20 of 3184 rows (1.42 sec)\n"
        "\n"
        "peekmem> scan:next 95\n"
        "+-----+--------------------+-------+\n"
        "| ROW | ADDRESS            | VALUE |\n"
        "+-----+--------------------+-------+\n"
        "|  #1 | 0x00000201A4C0F118 | 95    |\n"
        "+-----+--------------------+-------+\n"
        "1 row in set (0.02 sec)",
    ),
    Namespace(
        "pointer",
        "Pointers",
        "Follow pointer chains, and find ones that survive a restart.",
        "peekmem> pointer:scan #1 --depth 3\n"
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
    :class:`~peekmem.errors.CommandError`, printed as one ``ERROR:`` line.

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

    def error(self, message: str) -> None:  # type: ignore[override]
        raise CommandError(f"{self.prog}: {message} (try 'help {self.prog}')")

    def exit(self, status: int = 0, message: Optional[str] = None) -> None:  # type: ignore[override]
        if message:
            raise CommandError(message.strip())
        raise CommandError(f"{self.prog}: invalid arguments (try 'help {self.prog}')")


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
    ``scan:results:keep`` — so related commands sort and group together and a
    name says what it acts on. The short spellings people actually type
    (``read``, ``keep``) are registered as aliases, which is why the hierarchy
    costs nothing at the keyboard.
    """

    name: str
    handler: Handler
    summary: str
    usage: str
    parser: Optional[ParserFactory] = None
    aliases: Tuple[str, ...] = ()
    details: str = ""
    examples: Tuple[str, ...] = field(default=())

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

    @property
    def short(self) -> str:
        """The spelling worth advertising — the first plain-word alias.

        First, not shortest: the alias list is written most-natural-first, and
        the shortest is often the cryptic one (``x`` for ``memory:dump``,
        ``ptr`` for ``pointer:read``). Backslash aliases like ``\\q`` are
        skipped; they are shortcuts, not names. A top-level command is already
        the short spelling of itself.
        """
        if self.is_top_level:
            return self.name
        for alias in self.aliases:
            if alias.isalnum():
                return alias
        return ""

    def arguments(self) -> List[argparse.Action]:
        """Every argument this command accepts, in declaration order."""
        return list(self.parser().arguments) if self.parser is not None else []


_COMMANDS: Dict[str, Command] = {}
_ALIASES: Dict[str, str] = {}


def command(
    name: str,
    *,
    summary: str,
    usage: str,
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

        entry = Command(
            name=name,
            handler=handler,
            summary=summary,
            usage=usage,
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


def namespace(name: str) -> Optional[Namespace]:
    """The declared namespace called ``name``, if there is one."""
    return _NAMESPACES_BY_NAME.get(name.strip().lower().rstrip(":"))


def namespace_summary(name: str) -> str:
    """The one line describing a namespace, for the top-level help."""
    entry = namespace(name)
    return entry.summary if entry else ""


def children(prefix: str) -> List[Command]:
    """The commands one level below ``prefix``.

    One level, not all of them: ``children("scan")`` yields ``scan:results``
    but not ``scan:results:keep``. That is what makes the help layered — each
    listing shows a screen you can take in, and points at the next level down
    rather than dumping it.

    Works the same for a namespace (``memory``) and for a command that has
    commands beneath it (``scan:results``), because it is the same question in
    both cases: what can follow this word?
    """
    head = prefix.strip().lower().rstrip(":")
    if not head:
        return []
    depth = head.count(":") + 1
    return [
        entry
        for entry in all_commands()
        if entry.name.startswith(head + ":") and entry.name.count(":") == depth
    ]


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


from . import memory_commands  # noqa: E402,F401  (registration side effect)
from . import pointer_commands  # noqa: E402,F401
from . import process_commands  # noqa: E402,F401
from . import scan_commands  # noqa: E402,F401
from . import session_commands  # noqa: E402,F401

__all__ = (
    "Command",
    "CommandParser",
    "NAMESPACES",
    "Namespace",
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
    "top_level",
)
