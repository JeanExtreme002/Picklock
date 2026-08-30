# -*- coding: utf-8 -*-

"""
The read-eval-print loop.

The shell is deliberately thin: it turns a line of text into a command word
plus arguments, hands them to the registry, and makes sure nothing a command
raises can end the session by accident. Everything else — what the commands
are, what they print — lives elsewhere.

Line syntax is one command per line, arguments split with shell quoting rules,
and a trailing ``;`` politely ignored, since fingers used to a database prompt
will type one. Blank lines and lines starting with ``#`` or ``--`` are
comments, which is what makes a file of commands runnable with ``source``.
"""

import os
import re
import shlex
import sys
from typing import Iterable, List, Optional, Sequence, TextIO, Tuple

from PyMemoryEditor import PyMemoryEditorError

from . import __version__, valuetypes
from .commands import (
    all_commands,
    command_words,
    lookup,
    namespaces,
    option_words,
)
from .errors import CommandError, ExitShell
from .output import Printer
from .session import SETTINGS, Session

#: Where the interactive shell remembers what you typed.
HISTORY_FILE = os.path.join(os.path.expanduser("~"), ".picklock_history")
HISTORY_LENGTH = 1000

_LEADING_WORD = re.compile(r"\s*(\S+)\s*(.*)", re.DOTALL)

#: Asking a command for its own help is a reflex worth honouring — nobody
#: should have to learn that this shell spells it 'help <command>'.
_HELP_FLAGS = frozenset(("-h", "--help", "-?"))


class _Handled(Exception):
    """Internal: the line was dealt with and needs no further dispatch."""


class Shell:
    """Dispatches command lines against a :class:`~picklock.session.Session`."""

    def __init__(
        self,
        session: Optional[Session] = None,
        *,
        printer: Optional[Printer] = None,
        stdin: Optional[TextIO] = None,
    ):
        self.printer = printer if printer is not None else Printer()
        self.session = session if session is not None else Session(self.printer)
        self.session.printer = self.printer
        self.session.shell = self
        self.stdin = stdin if stdin is not None else sys.stdin
        self._history_loaded = False
        # True once readline is driving input(), which decides whether the
        # prompt's escapes need its width-ignoring brackets.
        self._readline = False

    # -- parsing and dispatch ---------------------------------------------

    @staticmethod
    def split(line: str) -> Optional[Tuple[str, List[str]]]:
        """Split a line into ``(command, args)``, or ``None`` when it is blank.

        The command word is taken verbatim rather than through ``shlex`` so
        the backslash aliases (``\\h``, ``\\.``) survive: POSIX
        quoting would eat the backslash and leave a command nobody registered.

        The arguments are lexed with escaping switched off, for the same
        reason one level down. In a shell whose arguments are mostly paths, a
        backslash is a separator far more often than an escape, and POSIX
        rules would turn ``source C:\\tools\\setup.txt`` into
        ``C:toolssetup.txt`` — silently, and then blame the file for not
        existing. Quotes still group, so a path with spaces is written
        ``"C:\\Program Files\\game\\setup.txt"`` on every platform.
        """
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("--"):
            return None

        # A trailing ';' is habit, not syntax. Accept it and move on.
        while stripped.endswith(";"):
            stripped = stripped[:-1].rstrip()
        if not stripped:
            return None

        match = _LEADING_WORD.match(stripped)
        if match is None:  # pragma: no cover - a non-blank line always matches
            return None

        word, remainder = match.group(1), match.group(2)
        try:
            lexer = shlex.shlex(remainder, posix=True)
            lexer.whitespace_split = True
            # '#' starts a scan-result row, not a comment. (A whole line that
            # begins with '#' is still a comment; that is handled above, before
            # the line is lexed.)
            lexer.commenters = ""
            lexer.escape = ""
            args = list(lexer)
        except ValueError as error:
            raise CommandError(f"Cannot parse the arguments: {error}.")
        return word, args

    def run_line(self, line: str, *, raise_errors: bool = False) -> bool:
        """Run one line. Returns True when it succeeded.

        :param raise_errors: re-raise :class:`CommandError` instead of printing
            it — used by ``source`` so a script stops at the failing line, and
            by ``--execute`` so the process can exit non-zero.
        """
        try:
            parsed = self.split(line)
            if parsed is None:
                return True
            word, args = parsed

            # An alias stands for the first word, so it is substituted before
            # anything else looks at the line: what follows sees only real
            # commands, and '--help' on an alias describes what it stands for.
            word, args = self.session.expand_alias(word, args)

            entry = self._resolve(word, args)

            if any(argument in _HELP_FLAGS for argument in args):
                lookup("help").handler(self.session, [entry.name])
                return True

            entry.handler(self.session, args)
            return True

        except ExitShell:
            raise
        except _Handled:
            return True
        except CommandError as error:
            if raise_errors:
                raise
            self.printer.error(str(error))
            return False
        except KeyboardInterrupt:
            # A command that does not handle Ctrl+C itself: abandon it, keep
            # the session.
            self.printer.clear_progress()
            self.printer.write("^C")
            return False
        except (PyMemoryEditorError, OSError, ValueError) as error:
            # The target died, a page went away, a value did not fit. All of
            # these are the day-to-day weather of poking at another process,
            # and none of them should end the session.
            if raise_errors:
                raise CommandError(str(error))
            self.printer.error(str(error))
            return False

    def _resolve(self, word: str, args: Sequence[str]):
        """Resolve a command word, answering ``:help`` for anything at all.

        Every command answers ``<command>:help`` — ``memory:help`` lists what
        ``memory`` takes, ``memory:read:help`` describes that one, ``clear:help``
        describes ``clear``. One rule, no exceptions to learn, and no need for
        the reader to know that some of those words are prefixes rather than
        actions.

        A word that only takes a subcommand prints its listing when typed alone
        (``memory``, ``memory --help``) and never runs anything. With other
        arguments it is a mistake worth naming precisely: the colon was meant.
        """
        head = word.strip().lower()
        wants_help = bool(args) and all(item in _HELP_FLAGS for item in args)

        if head.endswith(":help"):
            subject = head[: -len(":help")]

            if subject in namespaces():
                # 'memory:help read' describes one of them, as the listing says.
                if args and not wants_help:
                    self._show_help(lookup(f"{subject}:{args[0]}"))
                    raise _Handled()
                self._show_listing(subject)
                raise _Handled()

            try:
                target = lookup(subject)
            except CommandError:
                pass
            else:
                self._show_help(target)
                raise _Handled()

        if head.rstrip(":") in namespaces():
            parent = head.rstrip(":")
            if not args or wants_help:
                self._show_listing(parent)
                raise _Handled()

            candidate = f"{parent}:{args[0]}"
            try:
                lookup(candidate)
            except CommandError:
                raise CommandError(
                    f"{parent!r} takes a subcommand. "
                    f"Type '{parent}:help' to see them."
                )
            raise CommandError(
                f"{parent!r} takes a subcommand: the command is spelled "
                f"{candidate!r}, with a colon."
            )

        return lookup(word)

    def _show_help(self, entry) -> None:
        """Print one command's help page."""
        lookup("help").handler(self.session, [entry.name])

    def _show_listing(self, prefix: str) -> None:
        """Print the commands a prefix takes."""
        from .commands.session_commands import print_namespace

        print_namespace(self.session, prefix)

    def run_lines(self, lines: Iterable[str], *, raise_errors: bool = False) -> int:
        """Run a sequence of lines, returning a process exit status."""
        for line in lines:
            try:
                if not self.run_line(line, raise_errors=raise_errors):
                    return 1
            except ExitShell as exit_request:
                return exit_request.status
            except CommandError as error:
                self.printer.error(str(error))
                return 1
        return 0

    # -- the interactive loop ---------------------------------------------

    def prompt(self) -> str:
        """The prompt, naming the target so you cannot write to the wrong one.

        The target is dimmed rather than coloured: it is there to be noticed
        out of the corner of your eye — a reminder that writes are going
        somewhere — not to compete with the output above it.
        """
        if self.session.process is None:
            return "picklock> "
        name = self.session.process_name or "?"
        target = f"[{name}:{self.session.process.pid}]"
        return f"picklock {self.printer.dim(target, in_prompt=self._readline)}> "

    def banner(self) -> str:
        return (
            f"Welcome to Picklock {__version__}, a terminal client for "
            "PyMemoryEditor.\n"
            "Type 'help' for the command list, or 'help scanning' for a "
            "walkthrough.\n"
        )

    def interact(self, *, banner: bool = True) -> int:
        """Run the shell until ``exit``, Ctrl+C, Ctrl+D, or the input runs out.

        Ctrl+C returns 130 — the conventional "terminated by SIGINT" status —
        while ``exit`` and Ctrl+D return 0. All three are ordinary ways to
        leave; only the status distinguishes them.
        """
        if banner:
            self.printer.write(self.banner())

        self._setup_readline()
        status = 0

        try:
            while True:
                try:
                    line = input(self.prompt())
                except KeyboardInterrupt:
                    # Ctrl+C at the prompt quits. During a *command* it
                    # means something else —
                    # abandon that command and come back here (see run_line) —
                    # so interrupting a long scan still costs one keystroke
                    # and leaving costs two.
                    self.printer.write("^C")
                    status = 130
                    break
                except EOFError:
                    self.printer.write()
                    break

                try:
                    self.run_line(line)
                except ExitShell as exit_request:
                    status = exit_request.status
                    break
        finally:
            self._save_history()
            self.session.close()

        return status

    # -- readline ----------------------------------------------------------

    def _setup_readline(self) -> None:
        """Wire up history and tab completion when readline is available.

        readline is in the standard library on Linux and macOS but not on
        Windows, where its absence simply means no history and no completion —
        never a failure to start.
        """
        try:
            import readline
        except ImportError:  # pragma: no cover - Windows without pyreadline3
            return

        self._readline = True

        try:
            readline.read_history_file(HISTORY_FILE)
        except (OSError, ValueError):
            pass  # No history yet, or an unreadable one. Neither is fatal.
        readline.set_history_length(HISTORY_LENGTH)
        self._history_loaded = True

        readline.set_completer(self._complete)
        readline.set_completer_delims(" \t\n")
        # libedit (the readline stand-in shipped on macOS) spells the binding
        # differently, and binding the wrong one is a silent no-op.
        if "libedit" in (getattr(readline, "__doc__", "") or ""):
            readline.parse_and_bind("bind ^I rl_complete")
        else:
            readline.parse_and_bind("tab: complete")

    def _save_history(self) -> None:
        if not self._history_loaded:
            return
        try:
            import readline

            readline.write_history_file(HISTORY_FILE)
        except (ImportError, OSError):  # pragma: no cover - read-only home
            pass

    def _complete(self, text: str, state: int) -> Optional[str]:
        """Tab completion over command words, type names and setting names."""
        try:
            import readline

            buffer = readline.get_line_buffer()[: readline.get_endidx()]
        except (ImportError, AttributeError):  # pragma: no cover
            buffer = text

        first_word = not buffer[: len(buffer) - len(text)].strip()

        if first_word:
            # Namespaces complete too, so tabbing from nothing shows the five
            # groups before it shows forty commands.
            candidates: Sequence[str] = (
                command_words()
                + [name + ":" for name in namespaces()]
                + list(self.session.aliases)
            )
        else:
            head = buffer.strip().split()[0].lower()
            if head in ("config:set", "config:list"):
                candidates = [setting.name for setting in SETTINGS]
            elif head == "help":
                candidates = command_words() + ["types", "address", "scanning"]
            elif text.startswith("-"):
                # Completing a flag: offer exactly the ones this command
                # declares, which is the same list 'help <command>' prints.
                candidates = option_words(head)
            else:
                candidates = valuetypes.type_names()

        matches = [item for item in candidates if item.startswith(text)]
        return matches[state] if state < len(matches) else None


def command_summaries() -> List[Tuple[str, str]]:
    """``(name, summary)`` for every command — used by the ``--help`` output."""
    return [(entry.name, entry.summary) for entry in all_commands()]


__all__ = ("HISTORY_FILE", "Shell", "command_summaries")
