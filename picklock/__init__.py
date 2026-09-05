# -*- coding: utf-8 -*-

"""
Picklock — a plain-text terminal client for PyMemoryEditor.

Picklock exposes PyMemoryEditor's process introspection, memory scanning and
read/write features through an interactive shell: ASCII result tables, a
one-line prompt, no curses, no GUI toolkit, no colour beyond a single
highlight for errors. It runs anywhere Python does — a desktop, a headless
server, an SSH session, a CI job.

The package is a *client*: every memory operation is performed by
PyMemoryEditor, which Picklock depends on but does not vendor.
"""

__author__ = "Jean Loui Bernard Silva de Jesus"
__version__ = "0.2.2"

from .errors import CommandError, NoProcessError, PicklockError
from .session import Session
from .shell import Shell

__all__ = (
    "CommandError",
    "NoProcessError",
    "PicklockError",
    "Session",
    "Shell",
    "__author__",
    "__version__",
)
