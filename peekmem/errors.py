# -*- coding: utf-8 -*-

"""
Exception hierarchy for Peekmem.

Every error a *command* can raise against the user's input derives from
:class:`CommandError`. The shell catches that one class, prints it as a single
``ERROR: ...`` line and returns to the prompt — an interactive session must
never die because an address was mistyped. Anything that is *not* a
``CommandError`` (a bug in Peekmem itself) propagates with its traceback, which
is what you want when reporting an issue.
"""


class PeekmemError(Exception):
    """Base class for every Peekmem exception."""


class CommandError(PeekmemError):
    """A command was given input it cannot act on.

    Raised for unknown commands, malformed arguments, unreadable addresses and
    any other condition that is the user's to fix. The shell prints the message
    verbatim, so write it as a complete sentence that says what to do next.
    """


class NoProcessError(CommandError):
    """A command needing an attached process was run without one."""

    def __init__(self, command: str = ""):
        detail = f" Command {command!r} needs a target." if command else ""
        super().__init__(
            "No process attached." + detail + ' Use "ps:open <pid|name>" first.'
        )


class ExitShell(PeekmemError):
    """Raised by ``exit`` / ``quit`` to unwind the shell loop cleanly.

    Not an error in the user-facing sense — the shell catches it before the
    ``CommandError`` handler and returns the carried status code.
    """

    def __init__(self, status: int = 0):
        super().__init__("exit")
        self.status = status


__all__ = ("CommandError", "ExitShell", "NoProcessError", "PeekmemError")
