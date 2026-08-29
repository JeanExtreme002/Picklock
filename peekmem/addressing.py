# -*- coding: utf-8 -*-

"""
The little address language every command shares.

Anywhere Peekmem takes an address it takes an *expression*, so the workflows
that matter can be typed on one line instead of copied between commands:

===============================  =========================================
``0x7ffee3a01000`` / ``140...``  a literal, hex or decimal
``game.exe+0x1234``              a module base plus a static offset (ASLR-proof)
``"libfoo-1.so"+0x20``           the same, quoted when the name has a ``-``
``[game.exe+0x1234]+0x10``       read the pointer there, then add ``0x10``
``[[base+0x8]+0x20]+0x4``        a pointer chain, nested as deep as you like
``#3``                           the address on row 3 of the last scan
===============================  =========================================

The grammar is deliberately tiny — brackets, ``+``, ``-`` and the three kinds
of term above — because an address expression that needs its own manual page
has stopped being a convenience.
"""

from typing import TYPE_CHECKING, Any, List, Optional, Tuple

from .errors import CommandError

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .session import Session

_IDENT_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.")

#: Token kinds produced by :func:`_tokenize`.
_NUMBER, _IDENT, _RESULT, _OPEN, _CLOSE, _PLUS, _MINUS = range(7)


def _tokenize(text: str) -> List[Tuple[int, Any]]:
    tokens: List[Tuple[int, Any]] = []
    index = 0
    length = len(text)

    while index < length:
        char = text[index]

        if char.isspace():
            index += 1
            continue

        if char == "[":
            tokens.append((_OPEN, "["))
            index += 1
            continue

        if char == "]":
            tokens.append((_CLOSE, "]"))
            index += 1
            continue

        if char == "+":
            tokens.append((_PLUS, "+"))
            index += 1
            continue

        if char == "-":
            tokens.append((_MINUS, "-"))
            index += 1
            continue

        if char == "#":
            index += 1
            start = index
            while index < length and text[index].isdigit():
                index += 1
            if start == index:
                raise CommandError("'#' must be followed by a result number, e.g. #3.")
            tokens.append((_RESULT, int(text[start:index])))
            continue

        if char in ("'", '"'):
            end = text.find(char, index + 1)
            if end == -1:
                raise CommandError(f"Unterminated {char} in address expression.")
            tokens.append((_IDENT, text[index + 1 : end]))
            index = end + 1
            continue

        if char.lower() == "0" and text[index : index + 2].lower() == "0x":
            start = index
            index += 2
            while index < length and text[index] in "0123456789abcdefABCDEF_":
                index += 1
            try:
                tokens.append((_NUMBER, int(text[start:index].replace("_", ""), 16)))
            except ValueError:
                raise CommandError(f"{text[start:index]!r} is not a hex number.")
            continue

        if char in _IDENT_CHARS:
            start = index
            while index < length and text[index] in _IDENT_CHARS:
                index += 1
            word = text[start:index]
            # A run of digits is a decimal literal; anything else (including
            # "game.exe" and "libc.so.6") is a module name.
            if word.replace("_", "").isdigit():
                tokens.append((_NUMBER, int(word.replace("_", ""))))
            else:
                tokens.append((_IDENT, word))
            continue

        raise CommandError(f"Unexpected character {char!r} in address expression.")

    return tokens


class _Parser:
    """Recursive-descent parser over the token list. One expression per call."""

    def __init__(self, tokens: List[Tuple[int, Any]], session: "Session"):
        self.tokens = tokens
        self.session = session
        self.position = 0

    def peek(self) -> Optional[Tuple[int, Any]]:
        if self.position < len(self.tokens):
            return self.tokens[self.position]
        return None

    def next(self) -> Tuple[int, Any]:
        token = self.peek()
        if token is None:
            raise CommandError("Unexpected end of address expression.")
        self.position += 1
        return token

    def parse_expression(self) -> int:
        value = self.parse_term()
        while True:
            token = self.peek()
            if token is None or token[0] not in (_PLUS, _MINUS):
                return value
            self.position += 1
            operand = self.parse_term()
            value = value + operand if token[0] == _PLUS else value - operand

    def parse_term(self) -> int:
        kind, value = self.next()

        if kind == _NUMBER:
            return int(value)

        if kind == _RESULT:
            return self.session.result_address(int(value))

        if kind == _IDENT:
            return self.session.module_base(str(value))

        if kind == _OPEN:
            inner = self.parse_expression()
            closing = self.next()
            if closing[0] != _CLOSE:
                raise CommandError("Missing ']' in address expression.")
            return self.session.read_pointer(inner)

        raise CommandError("Expected an address, a module name or '[' here.")


def parse_address(text: str, session: "Session") -> int:
    """Evaluate an address expression against ``session``.

    :raises CommandError: on any syntax error, unknown module, out-of-range
        result index or unreadable dereference — all of which are the user's
        to correct, so the shell keeps running.
    """
    tokens = _tokenize(text)
    if not tokens:
        raise CommandError("Empty address.")

    parser = _Parser(tokens, session)
    address = parser.parse_expression()

    if parser.peek() is not None:
        raise CommandError(f"Trailing characters in address {text!r}.")
    if address < 0:
        raise CommandError(f"Address expression {text!r} resolved below zero.")
    return address


def parse_int(text: str, what: str = "value") -> int:
    """Parse a plain integer argument (hex or decimal), not an address."""
    cleaned = text.strip().replace("_", "")
    try:
        if cleaned[:2].lower() == "0x":
            return int(cleaned, 16)
        return int(cleaned, 10)
    except (ValueError, IndexError):
        raise CommandError(f"{text!r} is not a valid {what}.")


__all__ = ("parse_address", "parse_int")
