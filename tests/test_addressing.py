# -*- coding: utf-8 -*-

"""The address expression language."""

import pytest

from picklock.addressing import parse_address, parse_int
from picklock.errors import CommandError


class FakeSession:
    """Stands in for a Session, answering the three hooks the parser uses."""

    def __init__(self):
        self.pointers = {0x1000: 0x2000, 0x2010: 0x3000}
        self.reads = []

    def module_base(self, name):
        bases = {"game.exe": 0x400000, "libfoo-1.so": 0x500000}
        try:
            return bases[name.lower()]
        except KeyError:
            raise CommandError(f"No loaded module matches {name!r}.")

    def read_pointer(self, address):
        self.reads.append(address)
        if address not in self.pointers:
            raise CommandError(f"Cannot read the pointer at 0x{address:X}.")
        return self.pointers[address]

    def result_address(self, index):
        if index != 3:
            raise CommandError(f"#{index} is out of range.")
        return 0xDEAD0000


@pytest.fixture
def fake():
    return FakeSession()


@pytest.mark.parametrize(
    "text,expected",
    [
        ("0x1000", 0x1000),
        ("4096", 4096),
        ("0x1000+0x10", 0x1010),
        ("0x1000 - 0x10", 0xFF0),
        ("game.exe+0x1234", 0x401234),
        ("'libfoo-1.so'+0x20", 0x500020),
        ("#3", 0xDEAD0000),
        ("#3+8", 0xDEAD0008),
    ],
)
def test_expressions(fake, text, expected):
    assert parse_address(text, fake) == expected


def test_dereference_reads_through_the_pointer(fake):
    assert parse_address("[0x1000]", fake) == 0x2000
    assert parse_address("[0x1000]+0x10", fake) == 0x2010


def test_nested_dereference(fake):
    assert parse_address("[[0x1000]+0x10]", fake) == 0x3000
    assert fake.reads == [0x1000, 0x2010]


def test_unknown_module_is_a_command_error(fake):
    with pytest.raises(CommandError):
        parse_address("nosuch.dll+0x10", fake)


@pytest.mark.parametrize("text", ["", "[0x1000", "0x1000+", "0x1000 0x10", "@", "#"])
def test_malformed_expressions_are_reported(fake, text):
    with pytest.raises(CommandError):
        parse_address(text, fake)


def test_negative_result_is_rejected(fake):
    with pytest.raises(CommandError):
        parse_address("0x10-0x20", fake)


def test_parse_int_accepts_hex_and_decimal():
    assert parse_int("0x10") == 16
    assert parse_int("16") == 16
    with pytest.raises(CommandError):
        parse_int("sixteen")
