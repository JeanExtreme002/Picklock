# -*- coding: utf-8 -*-

"""Settings survive a restart, and can be put back."""

import pytest

from picklock import store
from picklock.commands.session_commands import restore
from picklock.errors import CommandError
from picklock.session import SETTINGS, Session

_FILE = "settings.json"


def test_changing_one_writes_it(shell):
    shell.run_line("config:set limit 3")
    assert store.load(_FILE) == {"limit": "3"}


def test_a_new_session_comes_back_the_same_way(shell, capture):
    shell.run_line("config:set limit 3")
    shell.run_line("config:set hex on")

    fresh = Session(capture.printer)
    assert restore(fresh) == []
    assert fresh.option("limit") == 3
    assert fresh.option("hex") is True


def test_only_the_changes_are_stored(shell):
    """A default that moves in a later release should still reach the user.

    Writing every setting out would pin all of them to today's values forever,
    including the ones nobody ever chose.
    """
    shell.run_line("config:set hex on")
    stored = store.load(_FILE)
    assert stored == {"hex": "on"}
    assert len(stored) < len(SETTINGS)


def test_returning_to_the_default_removes_it_from_the_file(shell):
    default = {setting.name: setting.default for setting in SETTINGS}["limit"]
    shell.run_line("config:set limit 3")
    shell.run_line(f"config:set limit {default}")
    assert store.load(_FILE) == {}


@pytest.mark.parametrize(
    "name,value,expected",
    [
        ("limit", "3", 3),
        ("hex", "on", True),
        ("timing", "off", False),
        ("watch_interval", "0.25", 0.25),
    ],
)
def test_every_kind_of_value_round_trips(shell, capture, name, value, expected):
    """Ints, floats and switches all have to survive the trip through JSON."""
    shell.run_line(f"config:set {name} {value}")

    fresh = Session(capture.printer)
    restore(fresh)
    assert fresh.option(name) == expected


def test_reset_puts_one_back(shell, capture):
    shell.run_line("config:set limit 3")
    capture.reset()
    shell.run_line("config:reset limit")

    assert shell.session.option("limit") == 20
    assert "the default" in capture.out
    assert store.load(_FILE) == {}


def test_reset_without_a_name_puts_everything_back(shell):
    shell.run_line("config:set limit 3")
    shell.run_line("config:set hex on")
    shell.run_line("config:reset")

    for setting in SETTINGS:
        assert shell.session.option(setting.name) == setting.default
    assert store.load(_FILE) == {}


def test_reset_rejects_a_name_that_is_not_a_setting(shell):
    with pytest.raises(CommandError, match="Unknown setting"):
        shell.run_line("config:reset nosuch", raise_errors=True)


def test_a_setting_that_no_longer_exists_is_ignored(capture):
    """Renamed between releases: one line of explanation, not a later error."""
    store.save(_FILE, {"limit": "3", "colour_scheme": "solarized"})

    session = Session(capture.printer)
    assert restore(session) == ["colour_scheme"]
    assert session.option("limit") == 3


def test_a_stored_value_that_no_longer_parses_is_ignored(capture):
    store.save(_FILE, {"limit": "as many as fit"})

    session = Session(capture.printer)
    assert restore(session) == ["limit"]
    assert session.option("limit") == 20


def test_a_missing_file_leaves_the_defaults(capture):
    session = Session(capture.printer)
    assert restore(session) == []
    assert session.option("limit") == 20


def test_a_write_failure_is_reported_but_not_fatal(shell, capture, monkeypatch):
    def refuse(_filename, _data):
        raise OSError("read-only file system")

    monkeypatch.setattr(store, "save", refuse)
    shell.run_line("config:set limit 3")

    assert shell.session.option("limit") == 3
    assert "Could not save" in capture.out
    assert "this session only" in capture.out


def test_settings_and_aliases_are_separate_files(shell):
    shell.run_line("config:set limit 3")
    shell.run_line("alias:add r memory:read")
    assert store.load("settings.json") == {"limit": "3"}
    assert store.load("aliases.json") == {"r": ["memory:read"]}
