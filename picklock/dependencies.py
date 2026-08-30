# -*- coding: utf-8 -*-

"""
Checking that the PyMemoryEditor underneath is new enough.

``pyproject.toml`` declares the floor, and pip enforces it on a normal
install — but not for anyone running Picklock out of a source tree, or in an
environment where an older PyMemoryEditor was already present. Those setups
used to fail much later and much more cryptically: an older backend aborts a
whole macOS scan on the first file-backed page whose pager declines to read,
so ``scan string utf-8`` came back as
``mach_vm_read_overwrite failed: (os/kern) memory error (kr=10)`` with nothing
pointing at the real cause.

One version comparison at startup turns that into a sentence naming the
problem and the command that fixes it.
"""

from typing import Optional, Tuple

import PyMemoryEditor

#: The oldest PyMemoryEditor Picklock supports. Keep in step with the floor in
#: pyproject.toml — the two say the same thing to different audiences.
REQUIRED_VERSION: Tuple[int, ...] = (2, 2, 0)


def parse_version(text: str) -> Tuple[int, ...]:
    """Parse the leading numeric components of a version string.

    Stops at the first component that is not a plain number, so a development
    or pre-release suffix (``2.2.0rc1``, ``2.3.0.dev0``) compares as the
    release it is heading for rather than crashing the check.
    """
    parts = []
    for piece in text.split("."):
        digits = ""
        for character in piece:
            if not character.isdigit():
                break
            digits += character
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def check() -> Optional[str]:
    """Return an explanation when PyMemoryEditor is too old, else ``None``."""
    installed = getattr(PyMemoryEditor, "__version__", "")
    parsed = parse_version(installed)

    # An unparseable version is not evidence of an old one — a fork or a
    # locally patched build should not be blocked over its version string.
    if not parsed or parsed >= REQUIRED_VERSION:
        return None

    required = ".".join(str(part) for part in REQUIRED_VERSION)
    return (
        f"Picklock needs PyMemoryEditor {required} or newer, but "
        f"{installed} is installed. Older versions abort a whole scan on the "
        "first page they cannot read, among other differences.\n"
        f'Upgrade with:  pip install -U "PyMemoryEditor>={required}"'
    )


__all__ = ("REQUIRED_VERSION", "check", "parse_version")
