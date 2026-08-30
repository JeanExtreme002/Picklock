# -*- coding: utf-8 -*-

"""
Listing the processes on this machine.

PyMemoryEditor implements process enumeration natively per platform — via
``CreateToolhelp32Snapshot`` on Windows, ``/proc`` on Linux and ``libproc`` on
macOS — but only exposes it from the platform backend module, not from the
package root. Importing the backend directly is what keeps Picklock's dependency
list at exactly one entry: the alternative is psutil, a compiled dependency
that would have to build or ship a wheel on every server Picklock is meant to
run on, to answer a question PyMemoryEditor can already answer.

The import is deliberately narrow (one function per platform) and guarded, so
a future rename in PyMemoryEditor surfaces here as a clear error rather than
as a mysterious traceback.
"""

import sys
from typing import Callable, Generator, Iterator, List, Optional, Tuple

from .errors import CommandError, PicklockError

#: ``(pid, name)`` as the platform backends yield it.
ProcessEntry = Tuple[int, str]


def _load_enumerator() -> Callable[[], Generator[ProcessEntry, None, None]]:
    """Return the platform's process-enumeration generator function."""
    try:
        if sys.platform == "win32":
            from PyMemoryEditor.win32.functions import GetProcesses

            return GetProcesses
        if sys.platform.startswith("linux"):
            from PyMemoryEditor.linux.functions import get_processes

            return get_processes
        if sys.platform == "darwin":
            from PyMemoryEditor.macos.functions import get_processes

            return get_processes
    except ImportError as error:  # pragma: no cover - depends on the installed lib
        raise PicklockError(
            "This PyMemoryEditor build does not expose process enumeration "
            f"where Picklock expects it ({error}). Upgrade PyMemoryEditor."
        )

    raise PicklockError(
        f"Unsupported platform {sys.platform!r}. Picklock runs on Windows, "
        "Linux and macOS."
    )


def iter_processes() -> Iterator[ProcessEntry]:
    """Yield ``(pid, name)`` for every process visible to the current user."""
    yield from _load_enumerator()()


def list_processes(
    pattern: Optional[str] = None,
    *,
    case_sensitive: bool = False,
    sort_by: str = "name",
) -> List[ProcessEntry]:
    """Return the visible processes, optionally filtered by a name substring.

    :param pattern: substring to match against the process name; a pattern that
        is all digits also matches a PID exactly, so ``ps 4242`` finds the
        process you meant even though the column is a number.
    :param case_sensitive: match ``pattern`` case-sensitively.
    :param sort_by: ``"name"`` (default) or ``"pid"``.
    """
    entries = list(iter_processes())

    if pattern:
        needle = pattern if case_sensitive else pattern.lower()
        pid_match = int(pattern) if pattern.isdigit() else None

        def matches(entry: ProcessEntry) -> bool:
            pid, name = entry
            if pid_match is not None and pid == pid_match:
                return True
            haystack = name if case_sensitive else name.lower()
            return needle in haystack

        entries = [entry for entry in entries if matches(entry)]

    if sort_by == "pid":
        entries.sort(key=lambda entry: entry[0])
    elif sort_by == "name":
        entries.sort(key=lambda entry: (entry[1].lower(), entry[0]))
    else:
        raise CommandError("Sort key must be 'name' or 'pid'.")

    return entries


def process_name(pid: int) -> Optional[str]:
    """Return the name of ``pid``, or ``None`` when it is not visible."""
    for entry_pid, name in iter_processes():
        if entry_pid == pid:
            return name
    return None


__all__ = ("ProcessEntry", "iter_processes", "list_processes", "process_name")
