# -*- coding: utf-8 -*-

"""Session state: settings, scan results and the '#N' reference."""

import pytest

from picklock import valuetypes
from picklock.errors import CommandError, NoProcessError
from picklock.session import SETTINGS, Session


def test_defaults_match_the_documented_settings(session: Session):
    for setting in SETTINGS:
        assert session.option(setting.name) == setting.default


@pytest.mark.parametrize("text,expected", [("on", True), ("off", False), ("TRUE", True)])
def test_boolean_settings(session: Session, text, expected):
    assert session.set_option("hex", text) is expected


def test_integer_settings_reject_nonsense(session: Session):
    assert session.set_option("limit", "50") == 50
    with pytest.raises(CommandError):
        session.set_option("limit", "many")
    with pytest.raises(CommandError):
        session.set_option("limit", "-1")


def test_float_settings_must_be_positive(session: Session):
    assert session.set_option("watch_interval", "0.25") == 0.25
    with pytest.raises(CommandError):
        session.set_option("watch_interval", "0")


def test_unknown_setting_lists_the_known_ones(session: Session):
    with pytest.raises(CommandError) as error:
        session.set_option("colour", "on")
    assert "limit" in str(error.value)


def test_timing_setting_reaches_the_printer(session: Session):
    session.set_option("timing", "off")
    assert session.printer.timing is False


def test_display_limit_of_zero_means_everything(session: Session):
    session.set_option("limit", "0")
    assert session.display_limit() is None
    assert session.display_limit(5) == 5


def test_commands_needing_a_target_say_so(session: Session):
    with pytest.raises(NoProcessError) as error:
        session.require_process("read")
    assert "open" in str(error.value)


def test_result_reference_needs_a_scan(session: Session):
    with pytest.raises(CommandError):
        session.result_address(1)


def test_result_reference_is_one_based(session: Session):
    session.store_scan(valuetypes.resolve("int32"), 4, [0x10, 0x20], [1, 2], "test")
    assert session.result_address(1) == 0x10
    assert session.result_address(2) == 0x20
    with pytest.raises(CommandError):
        session.result_address(3)
    with pytest.raises(CommandError):
        session.result_address(0)


def test_detaching_without_a_target_is_not_an_error(session: Session):
    assert session.detach() is False


def test_the_prompt_name_comes_from_the_os_not_from_what_was_typed(
    session, monkeypatch
):
    """'ps:open --partial chr' must not leave the prompt reading 'chr'.

    The prompt names the target so a write goes where you think it goes; a
    fragment of the name is not the name.
    """
    class FakeProcess:
        pid = 4242

        def close(self):
            pass

    monkeypatch.setattr("picklock.session.OpenProcess", lambda **kwargs: FakeProcess())
    monkeypatch.setattr(
        "picklock.processes.process_name", lambda pid: "chrome.exe"
    )

    session.attach(name="chr", exact_match=False)
    assert session.process_name == "chrome.exe"


def test_the_typed_name_is_the_fallback_when_the_os_declines(session, monkeypatch):
    class FakeProcess:
        pid = 4242

        def close(self):
            pass

    monkeypatch.setattr("picklock.session.OpenProcess", lambda **kwargs: FakeProcess())
    monkeypatch.setattr("picklock.processes.process_name", lambda pid: None)

    session.attach(name="chrome.exe")
    assert session.process_name == "chrome.exe"
