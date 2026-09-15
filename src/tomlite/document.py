"""A TOML file edited in place, without disturbing what the reader wrote around it.

Reading a TOML file is the standard library's job (`tomllib`). This module owns the other
direction -- turning a change into an edit on disk. It edits the file's *lines*, touching
only the ones that change, so a hand-written comment, a blank line, or a column of aligned
`=` survives an edit exactly as it was left. That is the whole reason it exists rather than
a parse-and-reserialize round trip, which would rewrite the file and drop every comment.

It is deliberately small -- it is not a general TOML manipulation library. It understands
the shape a machine-managed config file takes:

- a top-level key (`default_account = "..."`),
- a `[[table array]]` of entries, each matched by one of its fields,
- a flat `[table]` of keys.

The values it reads and writes are scalars (string, integer, boolean) and one-line arrays
of strings. It **round-trips anything it is willing to emit**: strings are written with
spec-complete escaping (every control character escaped) and read back the same, so an
address or a name containing a bracket, an equals sign, a quote, a backslash, or a control
character cannot corrupt the file on a later edit. What it does **not** support is a value
it never emits: a nested array, an inline table, or a multi-line value other than a
one-per-line array of scalars. Hand-writing one of those and then editing the file with
this module is out of contract.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator, Sequence
from pathlib import Path

__all__ = ["TOMLDocument", "TOMLScalar", "TOMLValue"]

# What this module can write: a scalar, or a one-line array of strings. `bool` is an `int`
# subclass, so callers and `_emit_value` must test it first.
TOMLScalar = str | int | bool
TOMLValue = TOMLScalar | Sequence[str]

# A key that can be written bare (unquoted) in TOML. Anything else -- a dot, a space, a
# non-ASCII letter -- must be quoted, or TOML reads the dot as nesting.
_BARE_KEY = re.compile(r"[A-Za-z0-9_-]+")

# The escapes a TOML basic string requires by name; every other control character (U+0000
# to U+001F except these, plus U+007F) is written as \uXXXX by `_emit_string`.
_NAMED_ESCAPES = {
    "\\": "\\\\",
    '"': '\\"',
    "\b": "\\b",
    "\t": "\\t",
    "\n": "\\n",
    "\f": "\\f",
    "\r": "\\r",
}
_NAMED_UNESCAPES = {"\\": "\\", '"': '"', "b": "\b", "t": "\t", "n": "\n", "f": "\f", "r": "\r"}


class TOMLDocument:
    """A TOML file held as lines, edited so the surrounding text is left intact.

    Load it, apply one or more edits, and save; each edit rewrites only the lines it
    changes. It is a mutable document with a lifecycle (load -> edit -> save), not a value
    object -- construct it through `load` / `loads`, not by hand (though the bare
    constructor takes the raw line list, which is handy in tests).
    """

    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    @classmethod
    def load(cls, path: str | Path) -> TOMLDocument:
        """The document at `path`, or an empty one when the file does not exist yet (so a
        first write can create the file from nothing)."""
        try:
            text = Path(path).read_text(encoding="utf-8")
        except FileNotFoundError:
            return cls([])
        return cls.loads(text)

    @classmethod
    def loads(cls, text: str) -> TOMLDocument:
        """A document from TOML `text`. Line endings are normalized to `\\n` -- and only a
        real `\\n` (or `\\r\\n`/`\\r`) is a line boundary, matching what `dumps` joins on, so
        an exotic in-string separator like U+2028 is not mistaken for the end of a line."""
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        lines = normalized.split("\n")
        if lines and lines[-1] == "":
            lines.pop()  # a trailing newline is the file's, not an empty final line
        return cls(lines)

    def dumps(self) -> str:
        """The document as text, with the single trailing newline a text file wants."""
        if not self._lines:
            return ""
        return "\n".join(self._lines) + "\n"

    def save(self, path: str | Path) -> None:
        """Write the document to `path` atomically, preserving an existing file's mode.

        The parent directory is created owner-only (0700) if absent. The write goes to a
        sibling temp file and is renamed over the target, so a crash mid-write cannot leave
        a half-written file. A brand-new file is created at the process umask (a config file
        is not a secret); an existing file keeps whatever mode it had.
        """
        target = Path(path)
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        tmp = target.with_name(f"{target.name}.tmp")
        tmp.write_text(self.dumps(), encoding="utf-8")
        try:
            mode: int | None = target.stat().st_mode
        except FileNotFoundError:
            mode = None
        os.replace(tmp, target)
        if mode is not None:
            os.chmod(target, mode)

    # -- top-level key -------------------------------------------------------

    def set_root_key(
        self, name: str, value: TOMLValue, *, only_if_absent: bool = False
    ) -> None:
        """Set a top-level `name = value`, above any table. `only_if_absent=True` leaves an
        existing value untouched (so a first entry can seed a default without a later one
        silently overwriting it)."""
        index = self._root_key_index(name)
        line = f"{_emit_key(name)} = {_emit_value(value)}"
        if index is not None:
            if not only_if_absent:
                self._lines[index] = line
            return
        # A blank line after it only when something follows, so a one-line file is not left
        # with a trailing blank.
        self._lines[0:0] = [line, ""] if self._lines else [line]

    # -- [[table array]] -----------------------------------------------------

    def has_in_array(self, array: str, *, field: str, value: str) -> bool:
        """Whether some `[[array]]` block has `field = value` (a string match). `field` and
        `value` are keyword-only: several interchangeable strings positionally are easy to
        misorder into a valid-but-wrong call."""
        return self._array_entry(array, field, value) is not None

    def append_to_array(
        self,
        array: str,
        fields: Sequence[tuple[str, TOMLValue]],
        *,
        before_table: str | None = None,
    ) -> None:
        """Append a new `[[array]]` block with `fields` in the given order. When
        `before_table` names a table, the block is inserted before that table's header (so
        related arrays stay grouped above it); otherwise it goes at end of file."""
        block = [f"[[{array}]]"]
        block += [f"{_emit_key(key)} = {_emit_value(val)}" for key, val in fields]
        at = self._header_index(f"[{before_table}]") if before_table else None
        if at is None:
            at = len(self._lines)
        pad = [""] if at > 0 and self._lines[at - 1].strip() else []
        self._lines[at:at] = [*pad, *block]

    def update_in_array(
        self,
        array: str,
        *,
        match_field: str,
        match_value: str,
        field: str,
        value: TOMLValue,
    ) -> bool:
        """In the `[[array]]` block where `match_field = match_value`, set `field` --
        replacing its line if present, else inserting it after the matched field. Returns
        whether a matching block was found. All match/field arguments are keyword-only:
        `update_in_array("accounts", "email", x, "alias", y)` is four interchangeable
        strings, and a swap would silently write the wrong field."""
        block = self._array_entry(array, match_field, match_value)
        if block is None:
            return False
        start, end = block
        line = f"{_emit_key(field)} = {_emit_value(value)}"
        anchor = start  # after the header, if the field is not already present
        for key, first, last in self._entries(start + 1, end):
            if key == field:
                self._lines[first:last] = [line + _trailing_comment(self._lines[first])]
                return True
            if key == match_field:
                anchor = first
        self._lines.insert(anchor + 1, line)
        return True

    # -- [table] key ---------------------------------------------------------

    def set_table_key(self, table: str, key: str, value: TOMLValue) -> None:
        """Set `key = value` inside `[table]`, replacing an existing entry or adding one,
        and opening the table at end of file when it does not exist yet."""
        line = f"{_emit_key(key)} = {_emit_value(value)}"
        header = self._header_index(f"[{table}]")
        if header is None:
            self._lines += ([""] if self._lines else []) + [f"[{table}]", line]
            return
        end = self._table_end(header + 1)
        for entry_key, first, last in self._entries(header + 1, end):
            if entry_key == key:
                self._lines[first:last] = [line + _trailing_comment(self._lines[first])]
                return
        self._lines.insert(end, line)

    # -- geometry ------------------------------------------------------------

    def _array_entry(self, array: str, field: str, value: str) -> tuple[int, int] | None:
        """The `[[array]]` block (start, end) whose `field` equals `value`, or None."""
        header = f"[[{array}]]"
        for start, line in enumerate(self._lines):
            if not (_is_header(line) and line.strip() == header):
                continue
            end = self._table_end(start + 1)
            for key, first, _ in self._entries(start + 1, end):
                if key == field and _line_value_string(self._lines[first]) == value:
                    return start, end
        return None

    def _header_index(self, header: str) -> int | None:
        """The line index of table header `header` (`[contacts]`), or None."""
        for index, line in enumerate(self._lines):
            if _is_header(line) and line.strip() == header:
                return index
        return None

    def _root_key_index(self, name: str) -> int | None:
        """The line index of a top-level key `name`, searched only before the first table
        header (a key under a table is not the top-level one), or None."""
        for index, line in enumerate(self._lines):
            if _is_header(line):
                return None
            if _line_key(line) == name:
                return index
        return None

    def _table_end(self, start: int) -> int:
        """One past the last line belonging to the table whose body starts at `start` -- the
        next header, or the line count. Trailing blank lines are excluded so an insert lands
        against the last entry rather than after a gap."""
        end = start
        while end < len(self._lines) and not _is_header(self._lines[end]):
            end += 1
        while end > start and not self._lines[end - 1].strip():
            end -= 1
        return end

    def _entries(self, start: int, end: int) -> Iterator[tuple[str, int, int]]:
        """Yield `(key, first, last)` for each `key = value` entry in `lines[start:end]`,
        consuming a value that runs across lines (a user's multi-line array) so its inner
        lines are never mistaken for keys. Bracket counting ignores brackets inside strings,
        so a value like `"see [team]"` does not look like an opened array. `first`/`last`
        bound the entry so a replacement can span it.
        """
        index = start
        while index < end:
            key = _line_key(self._lines[index])
            if key is None:
                index += 1
                continue
            after = index + 1
            depth = _bracket_delta(self._lines[index])
            while depth > 0 and after < end:
                depth += _bracket_delta(self._lines[after])
                after += 1
            yield key, index, after
            index = after


def _is_header(line: str) -> bool:
    """Whether `line` is a table header (`[contacts]`, `[[accounts]]`, ...). Within the
    supported grammar a value line never starts with `[`: strings are quoted, scalars are
    not bracketed, and the arrays this module writes are one line and keyed."""
    return line.lstrip().startswith("[")


def _line_key(line: str) -> str | None:
    """The key a `key = value` line defines, or None when the line is not one -- a comment,
    a blank, a header, or a continuation line inside a multi-line value. A quoted key is
    read to its own closing quote before the `=` is looked for, so a key containing `=`
    (`"a=b" = ...`) is not split at the wrong place."""
    stripped = line.lstrip()
    if not stripped or stripped[0] in "#[":
        return None
    if stripped[0] == '"':
        spans = _string_spans(stripped)
        if not spans or spans[0][0] != 0:
            return None
        start, stop = spans[0]
        if not stripped[stop:].lstrip().startswith("="):
            return None
        return _unescape(stripped[start + 1 : stop - 1])
    raw, sep, _ = line.partition("=")
    if not sep:
        return None
    key = raw.strip()
    return key if _BARE_KEY.fullmatch(key) else None


def _line_value_string(line: str) -> str | None:
    """The string value on a `key = "value"` line, or None when the value is not a lone
    basic string (an array, a number, a literal string). Used to match an entry by a field.
    The closing quote is found honoring backslash escapes, so a value ending in `\\` is not
    mistaken for an unterminated string."""
    _, sep, rest = line.partition("=")
    if not sep:
        return None
    value = rest.strip()
    if not value.startswith('"'):
        return None
    spans = _string_spans(value)
    if not spans or spans[0][0] != 0:
        return None
    start, stop = spans[0]
    return _unescape(value[start + 1 : stop - 1])


def _string_spans(line: str) -> list[tuple[int, int]]:
    """The half-open `(start, end)` ranges of quoted string literals in `line`. A basic
    string (`"..."`) honors backslash escapes -- `\\"` and `\\\\` do not end it; a literal
    string (`'...'`) has no escapes. Used to count brackets and locate values outside of
    strings, which is what keeps in-string punctuation from being read as structure."""
    spans: list[tuple[int, int]] = []
    index, length = 0, len(line)
    while index < length:
        char = line[index]
        if char == '"':
            cursor = index + 1
            while cursor < length:
                if line[cursor] == "\\":
                    cursor += 2
                    continue
                if line[cursor] == '"':
                    break
                cursor += 1
            spans.append((index, min(cursor + 1, length)))
            index = cursor + 1
        elif char == "'":
            close = line.find("'", index + 1)
            if close == -1:
                spans.append((index, length))
                index = length
            else:
                spans.append((index, close + 1))
                index = close + 1
        else:
            index += 1
    return spans


def _trailing_comment(line: str) -> str:
    """The trailing `# comment` on `line` (with the whitespace before it), or `""` -- so
    updating an entry's value keeps the note the reader left on that line. A `#` inside a
    string is not a comment, so it is masked before the search."""
    hash_at = _without_strings(line).find("#")
    if hash_at == -1:
        return ""
    start = hash_at
    while start > 0 and line[start - 1] in " \t":
        start -= 1
    return line[start:]


def _bracket_delta(line: str) -> int:
    """`[` minus `]` on `line`, counting only brackets outside quoted strings, so a bracket
    inside a value does not read as an opened or closed array."""
    bare = _without_strings(line)
    return bare.count("[") - bare.count("]")


def _without_strings(line: str) -> str:
    """`line` with every quoted string's characters replaced by spaces, so structural
    punctuation (`[`, `]`, `=`) can be found without the contents of strings interfering."""
    chars = list(line)
    for start, stop in _string_spans(line):
        for index in range(start, stop):
            chars[index] = " "
    return "".join(chars)


def _emit_key(name: str) -> str:
    """A TOML key for `name`: bare when it can be, a quoted basic string otherwise."""
    return name if _BARE_KEY.fullmatch(name) else _emit_string(name)


def _emit_value(value: TOMLValue) -> str:
    """`value` as TOML: a boolean, an integer, a basic string, or a one-line array of
    strings. `bool` is checked before `int` because it is a subclass of it."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return _emit_string(value)
    return "[" + ", ".join(_emit_string(one) for one in value) + "]"


def _emit_string(value: str) -> str:
    """`value` as a TOML basic string, escaping everything the spec requires: the quote and
    backslash, the named control escapes, and every other control character as `\\uXXXX`.
    This is what lets the reader round-trip it -- an unescaped control character would be
    invalid TOML, and an unescaped bracket/quote would be mis-scanned on the next edit."""
    out = ['"']
    for char in value:
        named = _NAMED_ESCAPES.get(char)
        if named is not None:
            out.append(named)
        elif char < " " or char == "\x7f":
            out.append(f"\\u{ord(char):04x}")
        else:
            out.append(char)
    out.append('"')
    return "".join(out)


def _unescape(text: str) -> str:
    """Reverse `_emit_string`: the named escapes plus `\\uXXXX` / `\\UXXXXXXXX`, so a quoted
    key or value read back from the file compares equal to what was written. A malformed
    escape is left as written rather than raising, since the input may be hand-edited."""
    out: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char != "\\" or index + 1 >= len(text):
            out.append(char)
            index += 1
            continue
        nxt = text[index + 1]
        if nxt in _NAMED_UNESCAPES:
            out.append(_NAMED_UNESCAPES[nxt])
            index += 2
        elif nxt in "uU":
            width = 4 if nxt == "u" else 8
            digits = text[index + 2 : index + 2 + width]
            try:
                out.append(chr(int(digits, 16)))
                index += 2 + width
            except ValueError:
                out.append(char)
                index += 1
        else:
            out.append(nxt)
            index += 2
    return "".join(out)
