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

#: Namespaces in the order ``help`` prints them, with the heading each one
#: gets. A command's namespace is the part of its name before the first colon,
#: so the grouping cannot drift from the naming — there is nothing to keep in
#: step.
NAMESPACES: Tuple[Tuple[str, str], ...] = (
    ("process", "Process"),
    ("memory", "Memory"),
    ("scan", "Scanning"),
    ("pointer", "Pointers"),
    ("session", "Session"),
)

_NAMESPACE_TITLES: Dict[str, str] = dict(NAMESPACES)
_NAMESPACE_ORDER: Dict[str, int] = {
    name: index for index, (name, _) in enumerate(NAMESPACES)
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
        """The first segment of the name — the group this command belongs to."""
        return self.name.split(":", 1)[0]

    @property
    def group(self) -> str:
        """The heading ``help`` files this command under."""
        return _NAMESPACE_TITLES.get(self.namespace, self.namespace.capitalize())

    @property
    def short(self) -> str:
        """The alias worth advertising — the first plain-word one.

        First, not shortest: the alias list is written most-natural-first, and
        the shortest is often the cryptic one (``x`` for ``memory:dump``,
        ``ptr`` for ``pointer:read``). Backslash aliases like ``\\q`` are
        skipped; they are shortcuts, not names.
        """
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
        if name.split(":", 1)[0] not in _NAMESPACE_TITLES:
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
    """Every registered command, in namespace order then alphabetically."""
    return sorted(
        _COMMANDS.values(),
        key=lambda entry: (_NAMESPACE_ORDER.get(entry.namespace, 99), entry.name),
    )


def children(prefix: str) -> List[Command]:
    """Commands sitting under ``prefix`` in the hierarchy.

    Works for a namespace (``memory`` yields every ``memory:*``) and for a
    command that has commands beneath it (``scan:results`` yields
    ``scan:results:keep`` and its siblings), which is the same question in both
    cases: what can follow this word?
    """
    head = prefix.strip().lower().rstrip(":")
    if not head:
        return []
    return [entry for entry in all_commands() if entry.name.startswith(head + ":")]


def namespaces() -> List[str]:
    """Every namespace that has at least one command registered in it."""
    known = {entry.namespace for entry in _COMMANDS.values()}
    return [name for name, _ in NAMESPACES if name in known]


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
    "all_commands",
    "children",
    "command",
    "command_words",
    "describe_action",
    "lookup",
    "namespaces",
    "option_words",
)
