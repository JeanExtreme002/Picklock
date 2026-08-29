# -*- coding: utf-8 -*-

"""
The command registry.

Every Peekmem command is a plain function registered with :func:`command`.
The registry owns the name, the aliases, the one-line summary and the usage
string, which means ``help`` is generated from the same data the dispatcher
uses — a command cannot be added without also being documented.

Importing this package imports every command module for its side effect of
registering; nothing else needs to know they exist.
"""

import argparse
import difflib
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from ..errors import CommandError

#: Groups in the order ``help`` prints them.
GROUPS: Tuple[str, ...] = ("Process", "Memory", "Scanning", "Pointers", "Session")

Handler = Callable[..., None]


@dataclass(frozen=True)
class Command:
    """One registered command."""

    name: str
    handler: Handler
    summary: str
    usage: str
    group: str
    aliases: Tuple[str, ...] = ()
    details: str = ""
    examples: Tuple[str, ...] = field(default=())


_COMMANDS: Dict[str, Command] = {}
_ALIASES: Dict[str, str] = {}


def command(
    name: str,
    *,
    summary: str,
    usage: str,
    group: str,
    aliases: Sequence[str] = (),
    details: str = "",
    examples: Sequence[str] = (),
) -> Callable[[Handler], Handler]:
    """Register a command handler.

    The handler is called as ``handler(session, args)`` where ``args`` is the
    already-split argument list (the command word removed).
    """

    def decorator(handler: Handler) -> Handler:
        if name in _COMMANDS or name in _ALIASES:
            raise RuntimeError(f"Duplicate command name: {name}")
        if group not in GROUPS:
            raise RuntimeError(f"Unknown command group: {group}")

        entry = Command(
            name=name,
            handler=handler,
            summary=summary,
            usage=usage,
            group=group,
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
    """Every registered command, sorted by group then name."""
    return sorted(
        _COMMANDS.values(), key=lambda entry: (GROUPS.index(entry.group), entry.name)
    )


def command_words() -> List[str]:
    """Every accepted command word, for tab completion."""
    return sorted(list(_COMMANDS) + list(_ALIASES))


class CommandParser(argparse.ArgumentParser):
    """An ``ArgumentParser`` that raises instead of killing the shell.

    ``argparse`` calls ``sys.exit`` on a usage error, which is right for a
    program and fatal for a REPL. Every failure becomes a
    :class:`~peekmem.errors.CommandError`, printed as one ``ERROR:`` line.
    """

    def __init__(self, prog: str, usage: Optional[str] = None):
        super().__init__(prog=prog, usage=usage, add_help=False)

    def error(self, message: str) -> None:  # type: ignore[override]
        raise CommandError(f"{self.prog}: {message} (try 'help {self.prog}')")

    def exit(self, status: int = 0, message: Optional[str] = None) -> None:  # type: ignore[override]
        if message:
            raise CommandError(message.strip())
        raise CommandError(f"{self.prog}: invalid arguments (try 'help {self.prog}')")


from . import memory_commands  # noqa: E402,F401  (registration side effect)
from . import pointer_commands  # noqa: E402,F401
from . import process_commands  # noqa: E402,F401
from . import scan_commands  # noqa: E402,F401
from . import session_commands  # noqa: E402,F401

__all__ = (
    "Command",
    "CommandParser",
    "GROUPS",
    "all_commands",
    "command",
    "command_words",
    "lookup",
)
