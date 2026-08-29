# -*- coding: utf-8 -*-

"""The PyMemoryEditor version floor."""

import pytest

from peekmem import dependencies


@pytest.mark.parametrize(
    "text,expected",
    [
        ("2.2.0", (2, 2, 0)),
        ("2.10.3", (2, 10, 3)),
        ("2.2.0rc1", (2, 2, 0)),
        ("2.3.0.dev0", (2, 3, 0)),
        ("2.2", (2, 2)),
        ("", ()),
        ("unknown", ()),
    ],
)
def test_parse_version(text, expected):
    assert dependencies.parse_version(text) == expected


def test_a_new_enough_version_passes(monkeypatch):
    monkeypatch.setattr(dependencies.PyMemoryEditor, "__version__", "2.2.0")
    assert dependencies.check() is None
    monkeypatch.setattr(dependencies.PyMemoryEditor, "__version__", "3.0.0")
    assert dependencies.check() is None


def test_an_old_version_is_reported_with_the_fix(monkeypatch):
    monkeypatch.setattr(dependencies.PyMemoryEditor, "__version__", "2.1.0")
    message = dependencies.check()
    assert message is not None
    assert "2.1.0 is installed" in message
    assert 'pip install -U "PyMemoryEditor>=2.2.0"' in message


def test_an_unparseable_version_is_not_blocked(monkeypatch):
    """A fork or a locally patched build should not be refused over a string."""
    monkeypatch.setattr(dependencies.PyMemoryEditor, "__version__", "custom-build")
    assert dependencies.check() is None
