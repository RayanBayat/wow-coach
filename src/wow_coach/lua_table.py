"""A tiny parser for the Lua data files that WoW writes (SavedVariables).

WoW saves addon data as plain Lua assignments, for example::

    CoachLinkDB = {
    ["level"] = 7,
    ["bags"] = {
    ["free"] = 3,
    },
    }

We only need the *data* subset of Lua: strings, numbers, booleans, nil and tables.
So instead of running Lua (unsafe and heavy) this file reads the text with a small
"recursive descent" parser: one method per grammar rule, each calling the others.

Conversion rules:
    * a table with only positional items becomes a ``list`` (``nil`` becomes ``None``)
    * a table with keys becomes a ``dict`` (keys are ``str`` or ``int``)
    * a mixed table becomes a ``dict`` with the positional items under keys 1..n
    * an empty table ``{}`` becomes an empty ``dict``
"""

from wow_coach.errors import LuaParseError

type LuaValue = str | int | float | bool | list[LuaValue] | dict[str | int, LuaValue] | None

_SIMPLE_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "'": "'"}
_NUMBER_CHARS = set("0123456789.-+eExXabcdefABCDEF")


def parse_saved_variables(text: str) -> dict[str, LuaValue]:
    """Parse a whole SavedVariables file into ``{variable name: value}``.

    Args:
        text: The file contents.

    Returns:
        One entry per top-level assignment ``Name = value``.

    Raises:
        LuaParseError: If the text is not valid; the message includes the line number.
    """
    return _Parser(text).parse_file()


class _Parser:
    """Walks through the text one character at a time, keeping a position."""

    def __init__(self, text: str) -> None:
        self._text = text
        self._pos = 0

    # ---- error helper -------------------------------------------------

    def _error(self, expected: str) -> LuaParseError:
        line = self._text.count("\n", 0, self._pos) + 1
        found = self._text[self._pos : self._pos + 10] or "end of file"
        return LuaParseError(f"line {line}: expected {expected}, found {found!r}")

    # ---- low-level reading ----------------------------------------------

    def _skip_blanks(self) -> None:
        """Skip whitespace (including CRLF) and ``-- comments``."""
        while self._pos < len(self._text):
            char = self._text[self._pos]
            if char.isspace():
                self._pos += 1
            elif self._text.startswith("--", self._pos):
                newline = self._text.find("\n", self._pos)
                self._pos = len(self._text) if newline == -1 else newline
            else:
                return

    def _peek(self) -> str:
        """Return the next significant character, or '' at the end."""
        self._skip_blanks()
        return self._text[self._pos] if self._pos < len(self._text) else ""

    def _expect(self, char: str) -> None:
        if self._peek() != char:
            raise self._error(repr(char))
        self._pos += 1

    def _read_name(self) -> str:
        """Read an identifier such as ``CoachLinkDB``."""
        self._skip_blanks()
        start = self._pos
        while self._pos < len(self._text) and (
            self._text[self._pos].isalnum() or self._text[self._pos] == "_"
        ):
            self._pos += 1
        if start == self._pos:
            raise self._error("a variable name")
        return self._text[start : self._pos]

    # ---- grammar rules ---------------------------------------------------

    def parse_file(self) -> dict[str, LuaValue]:
        """file = { Name '=' value }"""
        result: dict[str, LuaValue] = {}
        while self._peek() != "":
            name = self._read_name()
            self._expect("=")
            result[name] = self._parse_value()
        return result

    def _parse_value(self) -> LuaValue:
        """value = table | string | number | true | false | nil"""
        char = self._peek()
        if char == "{":
            return self._parse_table()
        if char == '"':
            return self._parse_string()
        if char == "" or not (char.isalnum() or char in "-+."):
            raise self._error("a value")
        if char.isalpha():
            return self._parse_keyword()
        return self._parse_number()

    def _parse_keyword(self) -> bool | None:
        for word, value in (("true", True), ("false", False), ("nil", None)):
            if self._text.startswith(word, self._pos):
                self._pos += len(word)
                return value
        raise self._error("true, false, nil, a number, a string or a table")

    def _parse_number(self) -> int | float:
        start = self._pos
        while self._pos < len(self._text) and self._text[self._pos] in _NUMBER_CHARS:
            self._pos += 1
        raw = self._text[start : self._pos]
        try:
            return int(raw)
        except ValueError:
            pass
        try:
            return float(raw)
        except ValueError:
            self._pos = start
            raise self._error("a number") from None

    def _parse_string(self) -> str:
        self._expect('"')
        pieces: list[str] = []
        while self._pos < len(self._text):
            char = self._text[self._pos]
            if char == '"':
                self._pos += 1
                return "".join(pieces)
            if char == "\\":
                pieces.append(self._read_escape())
            else:
                pieces.append(char)
                self._pos += 1
        raise self._error("a closing quote")

    def _read_escape(self) -> str:
        """Read a backslash escape; ``self._pos`` is on the backslash."""
        self._pos += 1
        char = self._text[self._pos : self._pos + 1]
        if char in _SIMPLE_ESCAPES:
            self._pos += 1
            return _SIMPLE_ESCAPES[char]
        if char.isdigit():
            digits = ""
            while len(digits) < 3 and self._text[self._pos : self._pos + 1].isdigit():
                digits += self._text[self._pos]
                self._pos += 1
            return chr(int(digits))
        raise self._error('a valid escape such as \\n or \\"')

    def _parse_table(self) -> LuaValue:
        """table = '{' { entry [','] } '}' where entry = '[' key ']' '=' value | value"""
        self._expect("{")
        positional: list[LuaValue] = []
        keyed: dict[str | int, LuaValue] = {}
        while self._peek() != "}":
            if self._peek() == "":
                raise self._error("'}' to close the table")
            if self._peek() == "[":
                key = self._parse_bracket_key()
                self._expect("=")
                keyed[key] = self._parse_value()
            else:
                positional.append(self._parse_value())
            if self._peek() in (",", ";"):
                self._pos += 1
        self._expect("}")
        return _build_table(positional, keyed)

    def _parse_bracket_key(self) -> str | int:
        """Read ``["name"]`` or ``[0]``."""
        self._expect("[")
        key = self._parse_value()
        if isinstance(key, bool) or not isinstance(key, (str, int, float)):
            raise self._error("a string or number key")
        self._expect("]")
        return int(key) if isinstance(key, float) and key.is_integer() else key  # type: ignore[return-value]


def _build_table(positional: list[LuaValue], keyed: dict[str | int, LuaValue]) -> LuaValue:
    """Decide whether a parsed table becomes a list or a dict."""
    if not keyed:
        return positional if positional else {}
    for index, item in enumerate(positional, start=1):
        keyed[index] = item
    return keyed
