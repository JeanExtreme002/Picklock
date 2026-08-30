# -*- coding: utf-8 -*-

"""The type vocabulary: parsing, widths and the unsigned bridge."""

import pytest

from picklock import valuetypes
from picklock.errors import CommandError


def test_aliases_resolve_to_the_same_type():
    assert valuetypes.resolve("int32") is valuetypes.resolve("i32")
    assert valuetypes.resolve("INT") is valuetypes.resolve("int32")
    assert valuetypes.resolve("dword") is valuetypes.resolve("uint32")


def test_unknown_type_lists_the_known_ones():
    with pytest.raises(CommandError) as error:
        valuetypes.resolve("int37")
    assert "int32" in str(error.value)


@pytest.mark.parametrize(
    "text,expected",
    [("10", 10), ("0x10", 16), ("0b1010", 10), ("0o17", 15), ("-5", -5), ("1_000", 1000)],
)
def test_integer_literals(text, expected):
    assert valuetypes.resolve("int32").parse(text) == expected


def test_integer_range_is_checked_per_width():
    with pytest.raises(CommandError):
        valuetypes.resolve("int8").parse("200")
    assert valuetypes.resolve("uint8").parse("200") == 200
    with pytest.raises(CommandError):
        valuetypes.resolve("uint8").parse("-1")


def test_unsigned_values_travel_as_the_same_bits():
    """An unsigned value must scan for the byte pattern the user expects."""
    uint32 = valuetypes.resolve("uint32")
    assert uint32.encode(4294967295) == -1
    assert uint32.decode(-1) == 4294967295
    # Values below the signed ceiling are untouched in both directions.
    assert uint32.encode(7) == 7
    assert uint32.decode(7) == 7


def test_signed_types_are_left_alone():
    int32 = valuetypes.resolve("int32")
    assert int32.encode(-1) == -1
    assert int32.decode(-1) == -1


@pytest.mark.parametrize("text,expected", [("true", True), ("off", False), ("1", True)])
def test_boolean_words(text, expected):
    assert valuetypes.resolve("bool").parse(text) is expected


def test_byte_arrays_accept_the_usual_separators():
    parse = valuetypes.resolve("bytes").parse
    assert parse("DE AD BE EF") == b"\xde\xad\xbe\xef"
    assert parse("de:ad-be:ef") == b"\xde\xad\xbe\xef"
    with pytest.raises(CommandError):
        parse("DEA")


def test_string_width_counts_encoded_bytes():
    """Counting characters would silently truncate accented text."""
    string = valuetypes.resolve("string")
    assert string.width_for("abc") == 3
    assert string.width_for("ábc") == 4
    assert string.width_for("abc", 16) == 16


def test_variable_width_types_demand_a_length_at_a_bare_address():
    with pytest.raises(CommandError) as error:
        valuetypes.resolve("string").read_width(None)
    assert "length" in str(error.value)
    assert valuetypes.resolve("int32").read_width(None) == 4


def test_printable_cuts_at_nul_and_dots_control_characters():
    assert valuetypes.printable("name\x00garbage") == "name"
    assert valuetypes.printable("a\nb\tc") == "a.b.c"


def test_format_renders_each_type_readably():
    assert valuetypes.resolve("bool").format(True) == "true"
    assert valuetypes.resolve("bytes").format(b"\xde\xad") == "DE AD"
    assert valuetypes.resolve("int32").format(255, hex_output=True) == "0xFF"
    assert valuetypes.resolve("float").format(1.5) == "1.5"
    assert valuetypes.resolve("int32").format(None) == "?"
