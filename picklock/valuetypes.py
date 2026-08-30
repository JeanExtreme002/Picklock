# -*- coding: utf-8 -*-

"""
The value-type vocabulary the shell speaks.

PyMemoryEditor's API takes a bare Python ``type`` (``bool``, ``int``,
``float``, ``str``, ``bytes``) plus an explicit byte width. A terminal user
types ``int32`` or ``float``, so this module owns the translation in both
directions: parsing what was typed into a value the library accepts, and
formatting what the library returns into a table cell.

Unsigned integers deserve a note. The library maps ``int`` to the *signed* C
type of the requested width (``c_int32`` for 4 bytes, and so on), so there is
no unsigned pytype to ask for. The bytes in memory are identical either way —
only the interpretation differs — so an unsigned type here scans and writes the
two's-complement *signed* value with the same bit pattern and reinterprets the
result on the way back. ``uint32 4294967295`` therefore searches for the four
bytes ``FF FF FF FF``, exactly as a user expects, without the library needing
to know unsigned types exist.
"""

import struct
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from .errors import CommandError

# Types the shell will not let you read at a bare address without being told
# how many bytes to take. ``str`` and ``bytes`` have no natural width: the
# width is the question, not the answer.
VARIABLE_WIDTH = 0

_TRUE_WORDS = frozenset(("1", "true", "t", "yes", "y", "on"))
_FALSE_WORDS = frozenset(("0", "false", "f", "no", "n", "off"))


def _parse_int_text(text: str) -> int:
    """Parse an integer literal, honouring 0x / 0o / 0b prefixes and ``_``."""
    cleaned = text.strip().replace("_", "")
    if not cleaned:
        raise CommandError("Empty integer value.")

    negative = cleaned.startswith("-")
    if negative or cleaned.startswith("+"):
        cleaned = cleaned[1:]

    try:
        # int(x, 0) understands every prefix at once but rejects a bare "010",
        # which a user typing a decimal with a leading zero would find absurd.
        prefix = cleaned[:2].lower()
        base = {"0x": 16, "0o": 8, "0b": 2}.get(prefix, 10)
        value = int(cleaned, base)
    except ValueError:
        raise CommandError(f"{text!r} is not an integer.")

    return -value if negative else value


def printable(text: str) -> str:
    """Make a string read from memory safe to put in a table cell.

    Two things happen to it. It is cut at the first NUL, because a fixed-width
    read of a C string returns the string plus whatever bytes follow it, and
    showing that tail helps nobody. Then every remaining control character
    becomes a dot, the way a hex dump renders one — a raw newline or tab in a
    cell would tear the ASCII table apart, which is a worse loss than the
    exact bytes.
    """
    text = text.split("\x00", 1)[0]
    return "".join(char if char == " " or char.isprintable() else "." for char in text)


def _parse_hex_bytes(text: str) -> bytes:
    """Parse ``"DE AD BE EF"`` (or ``de:ad-be:ef``) into raw bytes."""
    cleaned = text.strip()
    for separator in (" ", "\t", ":", "-", ","):
        cleaned = cleaned.replace(separator, "")
    if cleaned.lower().startswith("0x"):
        cleaned = cleaned[2:]

    if not cleaned:
        raise CommandError("Empty byte array.")
    if len(cleaned) % 2:
        raise CommandError("A byte array needs an even number of hex digits.")

    try:
        return bytes.fromhex(cleaned)
    except ValueError:
        raise CommandError(f"{text!r} is not a hex byte array.")


@dataclass(frozen=True)
class ValueType:
    """One entry in the shell's type vocabulary.

    :param name: canonical name, as printed by ``help types``.
    :param pytype: the Python type handed to PyMemoryEditor.
    :param size: fixed width in bytes, or :data:`VARIABLE_WIDTH` when the
        caller must supply one (``string`` and ``bytes``).
    :param aliases: alternative spellings accepted on the command line.
    :param unsigned: reinterpret the signed value the library reads/writes as
        unsigned of the same width (see the module docstring).
    :param summary: one-line description for ``help types``.
    """

    name: str
    pytype: type
    size: int
    aliases: Tuple[str, ...] = ()
    unsigned: bool = False
    summary: str = ""
    struct_code: Optional[str] = field(default=None, compare=False)

    @property
    def is_variable_width(self) -> bool:
        return self.size == VARIABLE_WIDTH

    # -- parsing ---------------------------------------------------------

    def parse(self, text: str) -> Any:
        """Turn command-line text into a value of this type."""
        if self.pytype is bool:
            word = text.strip().lower()
            if word in _TRUE_WORDS:
                return True
            if word in _FALSE_WORDS:
                return False
            raise CommandError(f"{text!r} is not a boolean (true/false, 1/0).")

        if self.pytype is int:
            value = _parse_int_text(text)
            self._check_int_range(value)
            return value

        if self.pytype is float:
            try:
                return float(text.strip())
            except ValueError:
                raise CommandError(f"{text!r} is not a number.")

        if self.pytype is bytes:
            return _parse_hex_bytes(text)

        # str — taken verbatim. An empty string would size to a one-byte NUL
        # buffer, which matches every zeroed byte in the target on a scan and
        # writes nothing at all, so neither meaning is the one intended.
        if not text:
            raise CommandError("Empty string value.")
        return text

    def _check_int_range(self, value: int) -> None:
        bits = self.size * 8
        low, high = (0, (1 << bits) - 1) if self.unsigned else (
            -(1 << (bits - 1)),
            (1 << (bits - 1)) - 1,
        )
        if not low <= value <= high:
            raise CommandError(
                f"{value} is out of range for {self.name} ({low} to {high})."
            )

    # -- widths ----------------------------------------------------------

    def width_for(self, value: Any, length: Optional[int] = None) -> int:
        """Byte width to use for ``value``, honouring an explicit ``length``.

        Fixed-width types ignore ``length`` — a 4-byte int is four bytes
        whatever the user says. Variable-width types default to the natural
        width of the value: the encoded UTF-8 length for a string (counting
        characters would silently truncate accented or CJK text), the array
        length for bytes.
        """
        if not self.is_variable_width:
            return self.size
        if length is not None:
            if length < 1:
                raise CommandError("Length must be at least 1 byte.")
            return length
        if isinstance(value, str):
            return max(1, len(value.encode("utf-8")))
        if isinstance(value, (bytes, bytearray)):
            return max(1, len(value))
        raise CommandError(f"Type {self.name} needs an explicit length.")

    def read_width(self, length: Optional[int] = None) -> int:
        """Byte width to read at a bare address (no value to measure)."""
        if not self.is_variable_width:
            return self.size
        if length is None:
            raise CommandError(
                f"Type {self.name} needs a length: e.g. 'read <address> "
                f"{self.name} 32'."
            )
        if length < 1:
            raise CommandError("Length must be at least 1 byte.")
        return length

    # -- the signed/unsigned bridge --------------------------------------

    def encode(self, value: Any) -> Any:
        """Convert a parsed value into what PyMemoryEditor should be given."""
        if self.unsigned and isinstance(value, int):
            bits = self.size * 8
            # Same bit pattern, signed reading — c_int32(-1) and an unsigned
            # 0xFFFFFFFF put identical bytes on the wire.
            return value - (1 << bits) if value >= (1 << (bits - 1)) else value
        return value

    def decode(self, value: Any) -> Any:
        """Convert what PyMemoryEditor returned into the user's reading of it."""
        if value is None:
            return None
        if self.unsigned and isinstance(value, int):
            bits = self.size * 8
            return value + (1 << bits) if value < 0 else value
        return value

    # -- formatting ------------------------------------------------------

    def format(self, value: Any, *, hex_output: bool = False) -> str:
        """Render a value for a result table."""
        if value is None:
            return "?"
        if self.pytype is bool:
            return "true" if value else "false"
        if self.pytype is int:
            return f"0x{value:X}" if hex_output and value >= 0 else str(value)
        if self.pytype is float:
            return f"{value:g}"
        if self.pytype is bytes:
            return " ".join(f"{byte:02X}" for byte in value)
        return printable(str(value))

    def to_bytes(self, value: Any, width: int) -> bytes:
        """Best-effort byte image of ``value`` at ``width`` bytes.

        Used by the *_BY refine comparisons and by nothing that touches the
        target, so an unrepresentable value is a programming error rather than
        something to report to the user.
        """
        wire = self.encode(value)
        if self.struct_code:
            return struct.pack("<" + self.struct_code, wire)
        if isinstance(wire, str):
            return wire.encode("utf-8")[:width].ljust(width, b"\x00")
        return bytes(wire)[:width].ljust(width, b"\x00")


#: Every type the shell knows, in the order ``help types`` prints them.
VALUE_TYPES: Tuple[ValueType, ...] = (
    ValueType("int8", int, 1, ("i8", "char", "sbyte"), summary="signed 1-byte integer", struct_code="b"),
    ValueType("int16", int, 2, ("i16", "short"), summary="signed 2-byte integer", struct_code="h"),
    ValueType("int32", int, 4, ("i32", "int"), summary="signed 4-byte integer (the usual default)", struct_code="i"),
    ValueType("int64", int, 8, ("i64", "long", "longlong"), summary="signed 8-byte integer", struct_code="q"),
    ValueType("uint8", int, 1, ("u8", "byte", "ubyte"), unsigned=True, summary="unsigned 1-byte integer", struct_code="B"),
    ValueType("uint16", int, 2, ("u16", "ushort", "word"), unsigned=True, summary="unsigned 2-byte integer", struct_code="H"),
    ValueType("uint32", int, 4, ("u32", "uint", "dword"), unsigned=True, summary="unsigned 4-byte integer", struct_code="I"),
    ValueType("uint64", int, 8, ("u64", "ulong", "qword"), unsigned=True, summary="unsigned 8-byte integer", struct_code="Q"),
    ValueType("float", float, 4, ("f32", "single"), summary="4-byte IEEE float", struct_code="f"),
    ValueType("double", float, 8, ("f64",), summary="8-byte IEEE float", struct_code="d"),
    ValueType("bool", bool, 1, ("boolean",), summary="1-byte boolean", struct_code="?"),
    ValueType("string", str, VARIABLE_WIDTH, ("str", "utf8", "text"), summary="UTF-8 text; give a length in bytes"),
    ValueType("bytes", bytes, VARIABLE_WIDTH, ("hex", "bytearray", "aob"), summary="raw bytes, written as hex ('DE AD BE EF')"),
)

_BY_NAME: Dict[str, ValueType] = {}
for _value_type in VALUE_TYPES:
    _BY_NAME[_value_type.name] = _value_type
    for _alias in _value_type.aliases:
        _BY_NAME[_alias] = _value_type

#: Default type when a command takes one but the user did not say which.
DEFAULT_TYPE = _BY_NAME["int32"]


def resolve(name: str) -> ValueType:
    """Look up a type by canonical name or alias.

    :raises CommandError: when the name is unknown, listing what is valid —
        a shell that answers "no such type" without saying which types exist
        makes the user go and read a manual.
    """
    value_type = _BY_NAME.get(name.strip().lower())
    if value_type is None:
        known = ", ".join(item.name for item in VALUE_TYPES)
        raise CommandError(f"Unknown type {name!r}. Known types: {known}.")
    return value_type


def type_names() -> Tuple[str, ...]:
    """Every accepted spelling, for tab completion."""
    return tuple(sorted(_BY_NAME))


__all__ = (
    "DEFAULT_TYPE",
    "VALUE_TYPES",
    "VARIABLE_WIDTH",
    "ValueType",
    "printable",
    "resolve",
    "type_names",
)
