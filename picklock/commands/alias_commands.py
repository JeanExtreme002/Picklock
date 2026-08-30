# -*- coding: utf-8 -*-

"""
The ``alias:`` namespace — giving a command a shorter name of your own.

An alias stands for the first word of a line and, optionally, some words after
it: ``r`` for ``memory:read``, or ``find-text`` for ``scan:value string``. When
one is used, its words replace the alias and whatever else was typed follows
them, so ``find-text Picklock`` runs ``scan:value string Picklock``.

Aliases persist. They are the one thing Picklock stores between runs — a name
you chose would be pointless if you had to choose it again every session —
and they are written to :mod:`picklock.aliases`'s file the moment they change.
"""

from typing import List

from .. import aliases as storage
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


def restore(session: Session) -> List[str]:
    """Load the stored aliases into ``session``; return the ones dropped.

    An alias whose command no longer exists is left out rather than kept: the
    shell promises that expanding an alias lands on a real command, and a name
    that quietly stopped working is worth one line of explanation the next time
    you start up.
    """
    dropped = []
    for name, words in sorted(storage.load().items()):
        if words[0] in namespaces():
            session.aliases[name] = words
            continue
        try:
            lookup(words[0])
        except CommandError:
            dropped.append(name)
        else:
            session.aliases[name] = words
    return dropped


def _persist(session: Session) -> None:
    """Write the aliases out, reporting a failure without raising.

    A home directory that cannot be written to is a reason to say so, not a
    reason to refuse the alias: it still works for this session.
    """
    try:
        storage.save(session.aliases)
    except OSError as error:
        session.printer.note(
            f"Could not save to {storage.path()}: {error}. "
            "The alias works for this session only."
        )


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
        "'scan:value string', typing 'find-text Picklock' runs "
        "'scan:value string Picklock'.\n\n"
        "A name already taken by a command or another alias is refused rather "
        "than shadowing it, and the command an alias points at has to exist, "
        "so a typo is caught here rather than the next time you use it.\n\n"
        "Aliases are remembered between runs — they are the one thing Picklock "
        "stores on disk. 'alias:list' says where."
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
    _persist(session)
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
        "listed with them, in 'help <command>'.\n\n"
        "They are stored in a file, whose path is printed under the table. "
        "Setting PICKLOCK_CONFIG_DIR moves it — useful for keeping a throwaway "
        "set apart from the one you rely on."
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
    session.printer.write(f"Stored in {storage.path()}")
    session.printer.write()


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
    _persist(session)
    session.printer.write(render_vertical([("removed", f"{name} = {' '.join(words)}")]))
    session.printer.write()


__all__ = ()
