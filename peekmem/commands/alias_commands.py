# -*- coding: utf-8 -*-

"""
The ``alias:`` namespace — giving a command a shorter name of your own.

An alias stands for the first word of a line and, optionally, some words after
it: ``r`` for ``memory:read``, or ``find-text`` for ``scan:value string``. When
one is used, its words replace the alias and whatever else was typed follows
them, so ``find-text Peekmem`` runs ``scan:value string Peekmem``.

Aliases live for the session, like the settings — Peekmem writes no config
file. Put the ``alias:add`` lines in a script and run it with ``source`` to
get the same shell back.
"""

from typing import List

from ..errors import CommandError
from ..output import LEFT, render_vertical
from ..session import Session
from . import CommandParser, command, command_words, lookup, namespaces

#: Characters that would make an alias unusable or ambiguous. A colon is the
#: separator the command hierarchy is built on, and a leading dash would read
#: as a flag at the point the line is split.
_FORBIDDEN = (":", " ", "\t")


def _validate_name(session: Session, name: str) -> str:
    """Check that ``name`` is free to use, or explain why it is not."""
    if not name:
        raise CommandError("An alias needs a name.")
    if any(character in name for character in _FORBIDDEN):
        raise CommandError(
            f"{name!r} cannot be an alias: a name has no ':' or spaces in it."
        )
    if name.startswith("-"):
        raise CommandError(f"{name!r} cannot be an alias: it would read as a flag.")

    if name in command_words() or name in namespaces():
        raise CommandError(
            f"{name!r} is already a command. Pick a name that is not taken — "
            "'alias:list' shows the ones you have."
        )
    if name in session.aliases:
        stands_for = " ".join(session.aliases[name])
        raise CommandError(
            f"{name!r} is already an alias for {stands_for!r}. "
            f"Remove it first with 'alias:remove {name}'."
        )
    return name


def _validate_target(words: List[str]) -> List[str]:
    """Check that the alias points at something that exists.

    Checked here rather than when the alias is used, so a typo is caught while
    you still remember what you meant — and so expansion can be a single pass
    that always lands on a real command, with no chains to follow or cycles to
    guard against.
    """
    if not words:
        raise CommandError("An alias needs a command to stand for.")

    head = words[0]
    if head in namespaces():
        return words
    try:
        lookup(head)
    except CommandError:
        raise CommandError(
            f"{head!r} is not a command, so nothing can be an alias for it. "
            "Type 'help' for the command list."
        )
    return words


def _alias_add_parser() -> CommandParser:
    parser = CommandParser("alias:add")
    parser.add_argument("name", help="the word you want to type")
    parser.add_argument(
        "words",
        nargs="+",
        metavar="command",
        help="the command it stands for, and any arguments that always go "
        "with it",
    )
    return parser


@command(
    "alias:add",
    parser=_alias_add_parser,
    summary="Give a command a shorter name.",
    details=(
        "The alias replaces the first word of a line, and anything else you "
        "type follows what it stands for — so with 'find-text' set to "
        "'scan:value string', typing 'find-text Peekmem' runs "
        "'scan:value string Peekmem'.\n\n"
        "A name already taken by a command or another alias is refused rather "
        "than shadowing it, and the command an alias points at has to exist, "
        "so a typo is caught here rather than the next time you use it.\n\n"
        "Aliases last for the session. Put these lines in a script and run it "
        "with 'source' to get the same shell back."
    ),
    examples=(
        "alias:add r memory:read",
        "alias:add find-text scan:value string",
        "alias:add w memory:write",
    ),
)
def cmd_alias_add(session: Session, args: List[str]) -> None:
    options = _alias_add_parser().parse_args(args)

    name = _validate_name(session, options.name.strip().lower())
    words = _validate_target(list(options.words))

    session.aliases[name] = words
    session.printer.ok(f"{name} = {' '.join(words)}")
    session.printer.write()


def _alias_list_parser() -> CommandParser:
    return CommandParser("alias:list")


@command(
    "alias:list",
    parser=_alias_list_parser,
    summary="Show the aliases defined in this session.",
    details=(
        "Takes no arguments.\n\n"
        "Only the ones you have added. The shell's own shortcuts — 'quit', "
        "'cls', '\\\\h', '\\\\.' — are part of the commands themselves and are "
        "listed with them, in 'help <command>'."
    ),
)
def cmd_alias_list(session: Session, args: List[str]) -> None:
    _alias_list_parser().parse_args(args)

    if not session.aliases:
        session.printer.write(
            "No aliases. Add one with 'alias:add <name> <command>'."
        )
        session.printer.write()
        return

    rows = [
        (name, " ".join(words)) for name, words in sorted(session.aliases.items())
    ]
    session.printer.table(("ALIAS", "STANDS FOR"), rows, (LEFT, LEFT))


def _alias_remove_parser() -> CommandParser:
    parser = CommandParser("alias:remove")
    parser.add_argument("name", help="the alias to forget")
    return parser


@command(
    "alias:remove",
    parser=_alias_remove_parser,
    summary="Forget an alias.",
    details=(
        "Only aliases you added can be removed; the shell's own shortcuts are "
        "part of their commands."
    ),
    examples=("alias:remove r",),
)
def cmd_alias_remove(session: Session, args: List[str]) -> None:
    options = _alias_remove_parser().parse_args(args)

    name = options.name.strip().lower()
    if name not in session.aliases:
        known = ", ".join(sorted(session.aliases)) or "none"
        raise CommandError(f"No alias called {name!r}. Defined: {known}.")

    words = session.aliases.pop(name)
    session.printer.write(render_vertical([("removed", f"{name} = {' '.join(words)}")]))
    session.printer.write()


__all__ = ()
