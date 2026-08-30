# -*- coding: utf-8 -*-

"""
Where Picklock keeps what it remembers between runs.

Plain JSON files, one per kind of thing — the aliases you defined, the settings
you changed. This module knows how to find them, read them and replace them
safely; what belongs inside each one is the business of the command that owns
it.

The location follows the usual convention for the platform:
``$XDG_CONFIG_HOME/picklock`` (or ``~/.config/picklock``) on Linux and macOS,
``%APPDATA%\\picklock`` on Windows. The readline history stays a dotfile in the
home directory, where readline's own convention puts it — that is an artefact
of the line editor rather than configuration.

Nothing here validates what it reads: a setting that no longer exists, or a
name that no longer points at a real command, is the caller's problem to report
— not this module's to silently fix.
"""

import json
import os
import sys
import tempfile
from typing import Any, Dict

#: Overridable so a test — or a throwaway session — can use its own files.
ENV_DIR = "PICKLOCK_CONFIG_DIR"


def directory() -> str:
    """The directory Picklock keeps its configuration in."""
    override = os.environ.get(ENV_DIR)
    if override:
        return override

    if sys.platform == "win32":  # pragma: no cover - Windows only
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
            os.path.expanduser("~"), ".config"
        )
    return os.path.join(base, "picklock")


def path(filename: str) -> str:
    """The full path of one of Picklock's files."""
    return os.path.join(directory(), filename)


def load(filename: str) -> Dict[str, Any]:
    """Read one file as a mapping, or return an empty one.

    A missing file is the ordinary case on a first run. An unreadable or
    malformed one returns nothing as well: a shell that refuses to start
    because of a stray character in a convenience file would be a worse bug
    than the one it is reporting.
    """
    try:
        with open(path(filename), "r", encoding="utf-8") as handle:
            stored = json.load(handle)
    except (OSError, ValueError):
        return {}

    return stored if isinstance(stored, dict) else {}


def save(filename: str, data: Dict[str, Any]) -> None:
    """Write one file, replacing whatever was there.

    Written to a temporary file in the same directory and moved into place, so
    an interrupted write cannot leave a half-file behind — the next run would
    read it, find it malformed, and quietly drop every alias at once.

    :raises OSError: when the file cannot be written. The caller decides
        whether that is worth interrupting them over.
    """
    target = path(filename)
    os.makedirs(os.path.dirname(target), exist_ok=True)

    handle = tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=os.path.dirname(target),
        prefix=filename,
        suffix=".tmp",
        delete=False,
    )
    try:
        with handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(handle.name, target)
    except BaseException:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
        raise


__all__ = ("ENV_DIR", "directory", "load", "path", "save")
