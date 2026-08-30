# -*- coding: utf-8 -*-

"""Shared fixtures. Nothing here attaches to a process.

The suite is deliberately target-free: it covers the parts of Picklock that are
its own — parsing, formatting, dispatch, help — and leaves reading another
process's memory to PyMemoryEditor's own tests. That keeps the suite runnable
on any CI machine, where opening a second process is usually not permitted.
"""

import io

import pytest

from picklock import aliases
from picklock.output import Printer
from picklock.session import Session
from picklock.shell import Shell


class Capture:
    """A printer writing to strings, plus helpers to read them back."""

    def __init__(self) -> None:
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()
        self.printer = Printer(self.stdout, self.stderr, color=False, timing=False)

    @property
    def out(self) -> str:
        return self.stdout.getvalue()

    @property
    def err(self) -> str:
        return self.stderr.getvalue()

    def reset(self) -> None:
        self.stdout.seek(0)
        self.stdout.truncate()
        self.stderr.seek(0)
        self.stderr.truncate()


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Point the alias file at a throwaway directory, for every test.

    Autouse and unconditional: the suite must never read or write the config
    of whoever is running it, and remembering to opt in per test is exactly
    the kind of thing that gets forgotten once.
    """
    monkeypatch.setenv(aliases.ENV_DIR, str(tmp_path / "config"))


@pytest.fixture
def capture() -> Capture:
    return Capture()


@pytest.fixture
def session(capture: Capture) -> Session:
    return Session(capture.printer)


@pytest.fixture
def shell(session: Session, capture: Capture) -> Shell:
    return Shell(session, printer=capture.printer)
