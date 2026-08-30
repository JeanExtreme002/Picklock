# -*- coding: utf-8 -*-

"""
Where the aliases are kept between sessions.

This is the only file Peekmem writes. Settings deliberately do not persist —
they tune one session's output and a stale one would be a surprise on the next
run — but an alias is a name you chose, and having to choose it again every
time would make the feature pointless.

The location follows the usual convention for the platform:
``$XDG_CONFIG_HOME/peekmem`` (or ``~/.config/peekmem``) on Linux and macOS,
``%APPDATA%\\peekmem`` on Windows. The readline history stays a dotfile in the
home directory, where readline's own convention puts it — that is an artefact
of the line editor rather than configuration.

Nothing here validates what it reads: a name that no longer points at a real
command is the caller's problem to report, not this module's to silently fix.
"""

import json
import os
import sys
import tempfile
from typing import Dict, List

#: Overridable so a test — or a throwaway session — can use its own file.
ENV_DIR = "PEEKMEM_CONFIG_DIR"

_FILENAME = "aliases.json"

Aliases = Dict[str, List[str]]


def directory() -> str:
    """The directory Peekmem keeps its configuration in."""
    override = os.environ.get(ENV_DIR)
    if override:
        return override

    if sys.platform == "win32":  # pragma: no cover - Windows only
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
            os.path.expanduser("~"), ".config"
        )
    return os.path.join(base, "peekmem")


def path() -> str:
    """The alias file itself."""
    return os.path.join(directory(), _FILENAME)


def load() -> Aliases:
    """Read the stored aliases, or return none.

    A missing file is the ordinary case on a first run. An unreadable or
    malformed one returns nothing as well: a shell that refuses to start
    because of a stray character in a convenience file would be a worse bug
    than the one it is reporting.
    """
    try:
        with open(path(), "r", encoding="utf-8") as handle:
            stored = json.load(handle)
    except (OSError, ValueError):
        return {}

    if not isinstance(stored, dict):
        return {}

    aliases: Aliases = {}
    for name, words in stored.items():
        if not isinstance(name, str):
            continue
        if isinstance(words, str):  # Tolerate a hand-edited single string.
            words = words.split()
        if isinstance(words, list) and words and all(isinstance(w, str) for w in words):
            aliases[name] = list(words)
    return aliases


def save(aliases: Aliases) -> None:
    """Write the aliases, replacing whatever was there.

    Written to a temporary file in the same directory and moved into place, so
    an interrupted write cannot leave a half-file behind — the next run would
    read it, find it malformed, and quietly drop every alias at once.

    :raises OSError: when the file cannot be written. The caller decides
        whether that is worth interrupting them over.
    """
    target = path()
    os.makedirs(os.path.dirname(target), exist_ok=True)

    handle = tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=os.path.dirname(target),
        prefix=_FILENAME,
        suffix=".tmp",
        delete=False,
    )
    try:
        with handle:
            json.dump(aliases, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(handle.name, target)
    except BaseException:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
        raise


__all__ = ("ENV_DIR", "Aliases", "directory", "load", "path", "save")
