"""A small TOML reader for python3 < 3.11, where tomllib does not exist.

It reads the subset providers.toml uses, and refuses everything else with a
line number instead of guessing:

  * comments, blank lines
  * [table] and [dotted.table-name] headers (bare keys: A-Za-z0-9_-)
  * key = value, with bare or "quoted" keys
  * values: "basic strings" (escapes: backslash, quote, n, t, r, b, f, uXXXX),
    'literal strings', integers, booleans, arrays (multi-line, trailing
    comma allowed) and { inline = "tables" }

The suite checks that it returns exactly what tomllib returns on
providers.toml whenever tomllib is available.
"""


class TOMLError(ValueError):
    pass


_BARE = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-")
_ESCAPES = {'"': '"', "\\": "\\", "n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f"}


class _Parser:
    def __init__(self, text):
        self.s = text
        self.i = 0
        self.line = 1

    def error(self, msg):
        raise TOMLError("line %d: %s" % (self.line, msg))

    def peek(self):
        return self.s[self.i] if self.i < len(self.s) else ""

    def advance(self):
        ch = self.s[self.i]
        self.i += 1
        if ch == "\n":
            self.line += 1
        return ch

    def skip_inline_ws(self):
        while self.peek() in (" ", "\t"):
            self.advance()

    def skip_comment(self):
        if self.peek() == "#":
            while self.peek() not in ("", "\n"):
                self.advance()

    def skip_ws_newlines_comments(self):
        while True:
            ch = self.peek()
            if ch in (" ", "\t", "\r", "\n"):
                self.advance()
            elif ch == "#":
                self.skip_comment()
            else:
                return

    def end_of_line(self):
        self.skip_inline_ws()
        self.skip_comment()
        if self.peek() == "\r":
            self.advance()
        if self.peek() not in ("", "\n"):
            self.error("unexpected %r after a value" % self.peek())
        if self.peek() == "\n":
            self.advance()

    def key_part(self):
        ch = self.peek()
        if ch == '"':
            return self.basic_string()
        if ch == "'":
            return self.literal_string()
        start = self.i
        while self.peek() in _BARE and self.peek() != "":
            self.advance()
        if start == self.i:
            self.error("expected a key, found %r" % ch)
        return self.s[start:self.i]

    def dotted_key(self):
        parts = [self.key_part()]
        while True:
            self.skip_inline_ws()
            if self.peek() != ".":
                return parts
            self.advance()
            self.skip_inline_ws()
            parts.append(self.key_part())

    def basic_string(self):
        self.advance()  # opening quote
        out = []
        while True:
            ch = self.peek()
            if ch in ("", "\n"):
                self.error("unterminated string")
            self.advance()
            if ch == '"':
                return "".join(out)
            if ch == "\\":
                esc = self.peek()
                if esc in _ESCAPES:
                    self.advance()
                    out.append(_ESCAPES[esc])
                elif esc == "u":
                    self.advance()
                    digits = self.s[self.i:self.i + 4]
                    if len(digits) != 4:
                        self.error("bad \\u escape")
                    try:
                        out.append(chr(int(digits, 16)))
                    except ValueError:
                        self.error("bad \\u escape")
                    self.i += 4
                else:
                    self.error("unsupported escape \\%s" % esc)
            else:
                out.append(ch)

    def literal_string(self):
        self.advance()
        start = self.i
        while self.peek() != "'":
            if self.peek() in ("", "\n"):
                self.error("unterminated literal string")
            self.advance()
        value = self.s[start:self.i]
        self.advance()
        return value

    def value(self):
        ch = self.peek()
        if ch == '"':
            if self.s.startswith('"""', self.i):
                self.error("multi-line strings are not supported")
            return self.basic_string()
        if ch == "'":
            if self.s.startswith("'''", self.i):
                self.error("multi-line strings are not supported")
            return self.literal_string()
        if ch == "[":
            return self.array()
        if ch == "{":
            return self.inline_table()
        start = self.i
        while self.peek() not in ("", " ", "\t", "\n", "\r", ",", "]", "}", "#"):
            self.advance()
        word = self.s[start:self.i]
        if word == "true":
            return True
        if word == "false":
            return False
        digits = word.replace("_", "")
        if digits.lstrip("+-").isdigit():
            return int(digits)
        self.error("unsupported value %r" % word)

    def array(self):
        self.advance()
        items = []
        while True:
            self.skip_ws_newlines_comments()
            if self.peek() == "]":
                self.advance()
                return items
            items.append(self.value())
            self.skip_ws_newlines_comments()
            if self.peek() == ",":
                self.advance()
            elif self.peek() == "]":
                self.advance()
                return items
            else:
                self.error("expected ',' or ']' in an array")

    def inline_table(self):
        self.advance()
        table = {}
        self.skip_inline_ws()
        if self.peek() == "}":
            self.advance()
            return table
        while True:
            self.skip_inline_ws()
            keys = self.dotted_key()
            self.skip_inline_ws()
            if self.peek() != "=":
                self.error("expected '=' in an inline table")
            self.advance()
            self.skip_inline_ws()
            self.assign(table, keys, self.value())
            self.skip_inline_ws()
            if self.peek() == ",":
                self.advance()
            elif self.peek() == "}":
                self.advance()
                return table
            else:
                self.error("expected ',' or '}' in an inline table")

    def assign(self, table, keys, value):
        for key in keys[:-1]:
            table = table.setdefault(key, {})
            if not isinstance(table, dict):
                self.error("key %r is not a table" % key)
        if keys[-1] in table:
            self.error("duplicate key %r" % keys[-1])
        table[keys[-1]] = value

    def document(self):
        root = {}
        current = root
        defined = set()
        while True:
            self.skip_ws_newlines_comments()
            if self.peek() == "":
                return root
            if self.peek() == "[":
                self.advance()
                if self.peek() == "[":
                    self.error("arrays of tables are not supported")
                self.skip_inline_ws()
                keys = self.dotted_key()
                self.skip_inline_ws()
                if self.peek() != "]":
                    self.error("expected ']' after a table name")
                self.advance()
                name = tuple(keys)
                if name in defined:
                    self.error("table [%s] defined twice" % ".".join(keys))
                defined.add(name)
                current = root
                for key in keys:
                    current = current.setdefault(key, {})
                    if not isinstance(current, dict):
                        self.error("key %r is not a table" % key)
                self.end_of_line()
                continue
            keys = self.dotted_key()
            self.skip_inline_ws()
            if self.peek() != "=":
                self.error("expected '=' after a key")
            self.advance()
            self.skip_inline_ws()
            self.assign(current, keys, self.value())
            self.end_of_line()


def loads(text):
    return _Parser(text).document()


def load(handle):
    data = handle.read()
    if isinstance(data, bytes):
        data = data.decode("utf-8")
    return loads(data)
