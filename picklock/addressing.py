# -*- coding: utf-8 -*-

"""
The little address language every command shares.

Anywhere Picklock takes an address it takes an *expression*, so the workflows
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

from typing import TYPE_CHECKING, Any, List, NamedTuple, Optional

from .errors import CommandError

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .session import Session

_IDENT_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.")

#: Token kinds produced by :func:`_tokenize`.
_NUMBER, _IDENT, _RESULT, _OPEN, _CLOSE, _PLUS, _MINUS = range(7)


class _Token(NamedTuple):
    """One lexeme, with what it looked like and whether a space came first.

    The source text and the spacing are what let a module name containing a
    hyphen be told from a subtraction: ``_ssl.cpython-311-darwin.so`` is one
    name, ``game.exe - 0x10`` is a sum.
    """

    kind: int
    value: Any
    source: str
    spaced_before: bool


def _tokenize(text: str) -> List["_Token"]:
    tokens: List[_Token] = []
    index = 0
    length = len(text)
    spaced = False

    def emit(kind: int, value: Any, source: str) -> None:
        tokens.append(_Token(kind, value, source, spaced))

    while index < length:
        char = text[index]

        if char.isspace():
            index += 1
            spaced = True
            continue

        if char == "[":
            emit(_OPEN, "[", "[")
            index += 1
            spaced = False
            continue

        if char == "]":
            emit(_CLOSE, "]", "]")
            index += 1
            spaced = False
            continue

        if char == "+":
            emit(_PLUS, "+", "+")
            index += 1
            spaced = False
            continue

        if char == "-":
            emit(_MINUS, "-", "-")
            index += 1
            spaced = False
            continue

        if char == "#":
            index += 1
            start = index
            while index < length and text[index].isdigit():
                index += 1
            if start == index:
                raise CommandError("'#' must be followed by a result number, e.g. #3.")
            emit(_RESULT, int(text[start:index]), text[start - 1 : index])
            spaced = False
            continue

        if char in ("'", '"'):
            end = text.find(char, index + 1)
            if end == -1:
                raise CommandError(f"Unterminated {char} in address expression.")
            emit(_IDENT, text[index + 1 : end], text[index : end + 1])
            index = end + 1
            spaced = False
            continue

        if char.lower() == "0" and text[index : index + 2].lower() == "0x":
            start = index
            index += 2
            while index < length and text[index] in "0123456789abcdefABCDEF_":
                index += 1
            try:
                emit(_NUMBER, int(text[start:index].replace("_", ""), 16), text[start:index])
                spaced = False
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
                emit(_NUMBER, int(word.replace("_", "")), word)
            else:
                emit(_IDENT, word, word)
            spaced = False
            continue

        raise CommandError(f"Unexpected character {char!r} in address expression.")

    return tokens


class _Parser:
    """Recursive-descent parser over the token list. One expression per call."""

    def __init__(self, tokens: List[_Token], session: "Session"):
        self.tokens = tokens
        self.session = session
        self.position = 0

    def peek(self, ahead: int = 0) -> Optional[_Token]:
        index = self.position + ahead
        if index < len(self.tokens):
            return self.tokens[index]
        return None

    def next(self) -> _Token:
        token = self.peek()
        if token is None:
            raise CommandError("Unexpected end of address expression.")
        self.position += 1
        return token

    def parse_expression(self) -> int:
        value = self.parse_term()
        while True:
            token = self.peek()
            if token is None or token.kind not in (_PLUS, _MINUS):
                return value
            self.position += 1
            operand = self.parse_term()
            value = value + operand if token.kind == _PLUS else value - operand

    def parse_term(self) -> int:
        token = self.next()

        if token.kind == _NUMBER:
            return int(token.value)

        if token.kind == _RESULT:
            return self.session.result_address(int(token.value))

        if token.kind == _IDENT:
            return self.session.module_base(self._module_name(str(token.value)))

        if token.kind == _OPEN:
            inner = self.parse_expression()
            closing = self.next()
            if closing.kind != _CLOSE:
                raise CommandError("Missing ']' in address expression.")
            return self.session.read_pointer(inner)

        raise CommandError("Expected an address, a module name or '[' here.")

    def _module_name(self, name: str) -> str:
        """Rejoin a module name the tokenizer split on a hyphen.

        A hyphen is a subtraction sign and also a perfectly ordinary character
        in a library's name — ``_ssl.cpython-311-darwin.so`` is what every
        Python process is full of. The two are told apart by asking: the pieces
        are rejoined only while they are written without spaces *and* the
        result names a module that is actually loaded. So
        ``game.exe-0x10`` stays a subtraction, because no such module exists,
        and ``game.exe - 0x10`` never even gets here.
        """
        best, consumed = name, 0
        candidate = name
        ahead = 0

        while True:
            minus, part = self.peek(ahead), self.peek(ahead + 1)
            if minus is None or part is None:
                break
            if minus.kind != _MINUS or minus.spaced_before or part.spaced_before:
                break
            if part.kind not in (_IDENT, _NUMBER):
                break

            candidate += "-" + part.source
            ahead += 2
            if self.session.knows_module(candidate):
                best, consumed = candidate, ahead

        self.position += consumed
        return best


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
