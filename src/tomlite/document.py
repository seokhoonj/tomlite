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

The values it reads and writes are scalars (string, integer, float, boolean) and one-line
arrays of strings. It **round-trips anything it is willing to emit**: strings are written with
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
import tempfile
from collections.abc import Iterator, Sequence
from pathlib import Path

__all__ = [
    "TOMLEditor",
    "TOMLScalar",
    "TOMLValue",
    "TomliteError",
    "UnsupportedTOMLError",
]

# What this module can write: a scalar, or a one-line array of strings. `bool` is an `int`
# subclass and `float` is separate, so `_emit_value` tests them in the right order.
TOMLScalar = str | int | float | bool
TOMLValue = TOMLScalar | Sequence[str]


class TomliteError(Exception):
    """Base class for every error tomlite raises."""


class UnsupportedTOMLError(TomliteError):
    """The file or edit is outside tomlite's flat grammar and cannot be edited safely -- a
    triple-quoted string, an array of arrays, a dotted or otherwise unparseable key, a table
    header that is not a bare-key path, or a key that collides with a table of the same name.
    tomlite edits the flat config-file grammar only; anything else is out of contract, and
    the message names the offending line or name."""


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


class TOMLEditor:
    """A TOML file held as lines, edited so the surrounding text is left intact.

    Load it, apply one or more edits, and save; each edit rewrites only the lines it
    changes. It is a mutable document with a lifecycle (load -> edit -> save), not a value
    object -- construct it through `load` / `loads`, not by hand (though the bare
    constructor takes the raw line list, which is handy in tests).
    """

    def __init__(self, lines: list[str]) -> None:
        self._lines = lines
        # Scanned once: a multi-line string anywhere makes the line scan unsafe, so the
        # editing operations refuse (reading -- dumps/save -- stays fine). tomlite never
        # emits one, so this verdict stays valid across edits.
        self._unsupported = _find_unsupported(lines)

    @classmethod
    def load(cls, path: str | Path) -> TOMLEditor:
        """The document at `path`, or an empty one when the file does not exist yet (so a
        first write can create the file from nothing).

        Raises:
            OSError: the path exists but cannot be read (permission, is-a-directory, ...).
            UnsupportedTOMLError: the file is not valid UTF-8.
        """
        try:
            text = Path(path).read_text(encoding="utf-8")
        except FileNotFoundError:
            return cls([])
        except UnicodeDecodeError as err:
            raise UnsupportedTOMLError(f"{path} is not valid UTF-8: {err}") from err
        return cls.loads(text)

    @classmethod
    def loads(cls, text: str) -> TOMLEditor:
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

        The immediate parent directory is created owner-only (0700) if absent (any deeper
        missing ancestors take the process umask). The write goes to a uniquely-named temp
        file in the same directory, whose mode is set *before* the rename, so the file never
        appears at the target path with a wider mode -- a crash mid-write leaves the target
        untouched, and a concurrent save cannot clobber the temp. An existing file keeps its
        mode; a new one is created owner-only (0600, the temp's default). A symlink or
        hardlink at `path` is *replaced* (the atomic rename swaps the path), not written
        through, so the previous target file is left untouched.

        Raises:
            OSError: the temp write, chmod, or rename failed.
        """
        target = Path(path)
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            mode: int | None = target.stat().st_mode
        except FileNotFoundError:
            mode = None
        fd, tmp_name = tempfile.mkstemp(
            dir=target.parent, prefix=f"{target.name}.", suffix=".tmp"
        )
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(self.dumps())
            if mode is not None:
                os.chmod(tmp, mode)  # the mode travels with the file, so no post-rename gap
            os.replace(tmp, target)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    # -- top-level key -------------------------------------------------------

    def set_root_key(
        self, key: str, value: TOMLValue, *, only_if_absent: bool = False
    ) -> None:
        """Set a top-level `key = value`, above any table. `only_if_absent=True` leaves an
        existing value untouched (so a first entry can seed a default without a later one
        silently overwriting it).

        Raises:
            UnsupportedTOMLError: the document is outside the flat grammar, or `key` is
                already declared as a table (a TOML key and table cannot share a name).
        """
        entry = self._root_entry(key)
        line = f"{_emit_key(key)} = {_emit_value(value)}"
        if entry is not None:
            if not only_if_absent:
                first, last = entry
                self._lines[first:last] = [line + _trailing_comment(self._lines[first])]
            return
        if self._table_declares(key):
            raise UnsupportedTOMLError(
                f"{key!r} is already a table; tomlite cannot also set it as a top-level key"
            )
        # A blank line after it only when a non-blank line follows, so a one-line file is
        # not left with a trailing blank and a doc already starting blank gains no second.
        pad = [""] if self._lines and self._lines[0].strip() else []
        self._lines[0:0] = [line, *pad]

    # -- [[table array]] -----------------------------------------------------

    def has_in_array(self, array: str, *, match_field: str, match_value: str) -> bool:
        """Whether some `[[array]]` block has `match_field = match_value` (a string match).
        The match arguments are keyword-only and named as in `update_in_array` /
        `remove_from_array`: several interchangeable strings positionally are easy to
        misorder into a valid-but-wrong call."""
        return self._array_entry(array, match_field, match_value) is not None

    def append_to_array(
        self,
        array: str,
        fields: Sequence[tuple[str, TOMLValue]],
        *,
        before_table: str | None = None,
    ) -> None:
        """Append a new `[[array]]` block with `fields` in the given order. When
        `before_table` names a header -- a plain `[table]` or a `[[table array]]` -- the block
        is inserted before it (so related arrays stay grouped above it); when it names nothing,
        or is omitted, the block goes at end of file.

        Raises:
            UnsupportedTOMLError: the document is outside the flat grammar; `array` is not a
                bare-key path (`a` or `a.b`) that a header can be written from; or `array`
                already names a plain `[array]` table or a top-level key (a TOML name cannot
                be two kinds at once). An existing `[[array]]` is the normal case -- another
                block is appended.
        """
        # The one mutator whose default path (before_table=None -> end of file) reaches no
        # scanner, so it guards here to refuse an unsupported document like its siblings.
        self._require_supported()
        _require_bare_path(array)
        if self._header_index(array) is not None:
            raise UnsupportedTOMLError(
                f"{array!r} is already a table ([{array}]); tomlite cannot also append to it "
                f"as an array-of-tables"
            )
        if self._root_entry(array) is not None:
            raise UnsupportedTOMLError(
                f"{array!r} is already a top-level key; tomlite cannot also open it as an "
                f"array-of-tables"
            )
        if isinstance(fields, str):  # a str is a Sequence, so guard it out with a clear error
            raise TypeError("fields must be a sequence of (key, value) pairs, not a str")
        block = [f"[[{array}]]"]
        for field in fields:
            if not (isinstance(field, tuple) and len(field) == 2):
                raise TypeError(f"each field must be a (key, value) pair, not {field!r}")
            key, val = field
            block.append(f"{_emit_key(key)} = {_emit_value(val)}")
        header = self._before_table_index(before_table) if before_table else None
        if header is None:  # end of file -- a leading blank if the last line is not one
            at = len(self._lines)
            pad = [""] if at > 0 and self._lines[at - 1].strip() else []
            self._lines[at:at] = [*pad, *block]
            return
        # Insert above the target header's leading comment run (not between the comment and its
        # header), blank-separated on both sides so the new block groups cleanly with the table
        # it precedes rather than butting against the header.
        at = self._header_comment_start(header)
        before = [""] if at > 0 and self._lines[at - 1].strip() else []
        after = [""] if self._lines[at].strip() else []
        self._lines[at:at] = [*before, *block, *after]

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
        and opening the table at end of file when it does not exist yet.

        Raises:
            UnsupportedTOMLError: the document is outside the flat grammar; `table` is not a
                bare-key path a header can be written from; or `table` already names a
                top-level key or an array-of-tables (a TOML name cannot be two kinds at once).
        """
        _require_bare_path(table)
        line = f"{_emit_key(key)} = {_emit_value(value)}"
        header = self._header_index(table)
        if header is None:
            if self._root_entry(table) is not None:
                raise UnsupportedTOMLError(
                    f"{table!r} is already a top-level key; tomlite cannot also open it "
                    f"as a table"
                )
            if self._header_index(table, is_array=True) is not None:
                raise UnsupportedTOMLError(
                    f"{table!r} is already an array-of-tables ([[{table}]]); tomlite cannot "
                    f"also open it as a table"
                )
            pad = [""] if self._lines and self._lines[-1].strip() else []
            self._lines += [*pad, f"[{table}]", line]
            return
        end = self._table_end(header + 1)
        for entry_key, first, last in self._entries(header + 1, end):
            if entry_key == key:
                self._lines[first:last] = [line + _trailing_comment(self._lines[first])]
                return
        self._lines.insert(end, line)

    # -- removal -------------------------------------------------------------

    def unset_root_key(self, key: str) -> bool:
        """Remove a top-level `key`, its multi-line value if it has one, and one blank
        separator around it. Returns whether it was there.

        Raises:
            UnsupportedTOMLError: the document uses a multi-line string.
        """
        entry = self._root_entry(key)
        if entry is None:
            return False
        self._drop(*entry)
        return True

    def remove_from_array(
        self, array: str, *, match_field: str, match_value: str
    ) -> bool:
        """Remove the `[[array]]` block where `match_field = match_value` (and one blank
        separator around it). Returns whether a block matched; match arguments are
        keyword-only, like the rest of the array API."""
        block = self._array_entry(array, match_field, match_value)
        if block is None:
            return False
        self._drop(*block)
        return True

    def unset_table_key(self, table: str, key: str) -> bool:
        """Remove `key` from `[table]`, leaving the table (even if now empty) and its
        comments in place. Returns whether the key was there."""
        header = self._header_index(table)
        if header is None:
            return False
        for entry_key, first, last in self._entries(header + 1, self._table_end(header + 1)):
            if entry_key == key:
                del self._lines[first:last]
                return True
        return False

    def _drop(self, start: int, end: int) -> None:
        """Delete `lines[start:end]` plus one adjacent blank separator -- the one before it,
        else the one after -- so removing a block or a key leaves no orphan gap."""
        if start > 0 and not self._lines[start - 1].strip():
            start -= 1
        elif end < len(self._lines) and not self._lines[end].strip():
            end += 1
        del self._lines[start:end]

    # -- geometry ------------------------------------------------------------

    def _require_supported(self) -> None:
        """Refuse to edit a file that uses a construct outside tomlite's flat grammar (a
        multi-line string, an array of arrays, a bare dotted key, or an exotic header),
        whose lines the scan would misread. The verdict is computed once, at construction."""
        if self._unsupported is not None:
            raise UnsupportedTOMLError(self._unsupported)

    def _array_entry(self, array: str, field: str, value: str) -> tuple[int, int] | None:
        """The `[[array]]` block (start, end) whose `field` equals `value`, or None. The
        header is matched by name, so a trailing comment or surrounding whitespace on it
        does not hide the block."""
        self._require_supported()
        for start, line in enumerate(self._lines):
            if _header_name(line) != (array, True):
                continue
            end = self._table_end(start + 1)
            for key, first, _ in self._entries(start + 1, end):
                if key == field and _line_value_string(self._lines[first]) == value:
                    return start, end
        return None

    def _header_index(self, name: str, *, is_array: bool = False) -> int | None:
        """The line index of the `[name]` (or `[[name]]`) header, matched by name -- a
        trailing comment or surrounding whitespace on the header does not hide it -- or
        None."""
        self._require_supported()
        for index, line in enumerate(self._lines):
            if _header_name(line) == (name, is_array):
                return index
        return None

    def _before_table_index(self, name: str) -> int | None:
        """The header line to insert a new array block before, matching `name` as either a
        plain `[name]` table or a `[[name]]` array-of-tables (the first block of it) -- so a
        `before_table` argument positions correctly regardless of the target's kind. None if
        no header of either kind names it (the caller then appends at end of file)."""
        header = self._header_index(name)
        if header is not None:
            return header
        return self._header_index(name, is_array=True)

    def _header_comment_start(self, header: int) -> int:
        """The first line of the comment run directly above the header at `header` -- a run of
        full-line `# comment`s with no blank between them and the header -- or `header` itself
        if none. An insert before a table lands here, above the comment that annotates it."""
        start = header
        while start > 0 and self._lines[start - 1].lstrip().startswith("#"):
            start -= 1
        return start

    def _root_entry(self, key: str) -> tuple[int, int] | None:
        """The `(first, last)` span of a top-level `key`'s entry, searched only before the
        first table header (a key under a table is not the top-level one). The span covers a
        multi-line value, so replacing or removing it -- the same bracket-consuming walk the
        table path uses -- never leaves orphan lines. None if absent."""
        self._require_supported()
        for entry_key, first, last in self._entries(0, self._preamble_end()):
            if entry_key == key:
                return first, last
        return None

    def _preamble_end(self) -> int:
        """The index of the first table header, i.e. one past the last top-level line."""
        for index, line in enumerate(self._lines):
            if _is_header(line):
                return index
        return len(self._lines)

    def _table_declares(self, name: str) -> bool:
        """Whether a table header declares `name` at the top level -- `[name]`, `[[name]]`,
        or a nested `[name.sub]` -- so a top-level key of the same name would collide (TOML
        forbids a key and a table sharing a name)."""
        for line in self._lines:
            parsed = _header_name(line)
            if parsed is not None and parsed[0].split(".", 1)[0].strip() == name:
                return True
        return False

    def _table_end(self, start: int) -> int:
        """One past the last *entry* line of the table whose body starts at `start` -- the next
        header, or the line count, with trailing blank and full-line comment lines excluded.
        Those trailing lines are the boundary zone between tables: trimming them makes an insert
        land against the last entry rather than after a gap or below a comment, and keeps a
        block removal from swallowing a comment that annotates the following block."""
        end = start
        while end < len(self._lines) and not _is_header(self._lines[end]):
            end += 1
        while end > start and _is_blank_or_comment(self._lines[end - 1]):
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


def _find_unsupported(lines: list[str]) -> str | None:
    """A message naming the first construct outside tomlite's flat grammar, or None. These
    are refused rather than corrupted because the line scan cannot edit them safely:

    - a multi-line string (`\"\"\"` / `'''`), whose interior lines look like structure;
    - an array of arrays -- a `[`-opening line inside an open multi-line array, which the
      scan would misread as a table header;
    - a table header whose name is not a bare-key path (`[a b]`, `["a"]`, `[café]`), which
      the by-name match and the writer cannot represent;
    - any other assignment whose key the scanner cannot parse -- a dotted key (`a.b = 1`),
      a mixed quoted/bare dotted key (`a."b" = 1`), all of which denote table nesting.

    tomlite never emits any of these, so one can only come from a hand-edited file.
    """
    depth = 0
    for index, line in enumerate(lines):
        if _uses_triple_quote(line):
            return _outside(index, "a triple-quoted string")
        if depth > 0:
            if _is_header(line):
                return _outside(index, "an array of arrays")
        else:
            header = _header_name(line)
            if header is not None:
                if not _is_bare_path(header[0]):
                    return _outside(index, "a table header that is not a bare-key path")
            elif _has_unparseable_key(line):
                return _outside(index, "a dotted or otherwise unsupported key")
        depth += _bracket_delta(line)
    return None


def _outside(index: int, what: str) -> str:
    return f"line {index + 1}: {what} is outside the flat grammar tomlite can edit safely"


def _uses_triple_quote(line: str) -> bool:
    """Whether `line` uses a triple-quoted string (`\"\"\"` / `'''`) as a value delimiter,
    which tomlite can neither represent nor scan, so it is refused -- whether the string is
    multi-line or closed on one line (`x = \"\"\"a\"\"\"`). A triple-quote *inside* a single-line
    string or a comment is content, not a delimiter, and is fine."""
    index, length = 0, len(line)
    while index < length:
        char = line[index]
        if char == "#":
            return False  # the rest of the line is a comment
        if char in "\"'":
            if line[index : index + 3] in ('"""', "'''"):
                return True  # a triple-quote at a delimiter position
            cursor = index + 1  # a single-line string: skip past it to its close
            while cursor < length:
                if char == '"' and line[cursor] == "\\":
                    cursor += 2
                    continue
                if line[cursor] == char:
                    break
                cursor += 1
            index = cursor + 1
        else:
            index += 1
    return False


def _is_bare_path(name: str) -> bool:
    """Whether `name` is a dotted path of bare keys (`a`, `a.b`) -- the only table/array
    names tomlite can write and match unambiguously. A quoted, spaced, empty, or non-ASCII
    name is not one."""
    return bool(name) and all(_BARE_KEY.fullmatch(seg) for seg in name.split("."))


def _require_bare_path(name: str) -> None:
    """Raise unless `name` is a bare-key path -- the only table/array name a header can be
    written from. Guards the writer against emitting an unrepresentable `[a b]` / `[café]`
    that no TOML reader would accept."""
    if not _is_bare_path(name):
        raise UnsupportedTOMLError(
            f"{name!r} is not a table name tomlite can write; use a bare-key path like "
            f"'a' or 'a.b'"
        )


def _has_unparseable_key(line: str) -> bool:
    """Whether `line` is an assignment (a structural `=`, outside any string or comment)
    whose key the scanner cannot parse -- a dotted or mixed quoted/bare dotted key. Such a
    line is invisible to `_entries`, so it is refused rather than silently mis-edited."""
    masked = _without_strings(line)
    hash_at = masked.find("#")
    if hash_at != -1:
        masked = masked[:hash_at]
    return "=" in masked and _line_key(line) is None


def _header_name(line: str) -> tuple[str, bool] | None:
    """`(name, is_array)` for a table header line -- `[name]` -> `(name, False)`,
    `[[name]]` -> `(name, True)` -- with a trailing comment and surrounding whitespace
    stripped, or None when the line is not a header. The name is what callers compare, so
    `[ contacts ]   # note` still matches the name `contacts`."""
    stripped = line.strip()
    if not stripped.startswith("["):
        return None
    is_array = stripped.startswith("[[")
    close = "]]" if is_array else "]"
    end = stripped.find(close, len(close))
    if end == -1:
        return None
    trailer = stripped[end + len(close) :].lstrip()
    if trailer and not trailer.startswith("#"):
        return None
    return stripped[len(close) : end].strip(), is_array


def _is_header(line: str) -> bool:
    """Whether `line` is a table header (`[contacts]`, `[[accounts]]`, ...). Within the
    supported grammar a value line never starts with `[`: strings are quoted, scalars are
    not bracketed, and the arrays this module writes are one line and keyed."""
    return line.lstrip().startswith("[")


def _is_blank_or_comment(line: str) -> bool:
    """Whether `line` carries no entry -- it is blank or a full-line `# comment`. These are
    the boundary zone between one table's last entry and the next header; `_table_end` trims
    them so an insert lands against the last entry and a removal does not swallow a comment
    that annotates the following block."""
    stripped = line.strip()
    return not stripped or stripped.startswith("#")


def _line_key(line: str) -> str | None:
    """The key a `key = value` line defines, or None when the line is not one -- a comment,
    a blank, a header, or a continuation line inside a multi-line value. A quoted key is
    read to its own closing quote before the `=` is looked for, so a key containing `=`
    (`"a=b" = ...`) is not split at the wrong place."""
    stripped = line.lstrip()
    if not stripped or stripped[0] in "#[":
        return None
    if stripped[0] in "\"'":
        # A quoted key -- basic ("...") or literal ('...') -- is read to its own closing
        # quote before the `=` is looked for, so a key containing `=` is not mis-split. A
        # literal string carries no escapes; a basic one is unescaped to its real text.
        spans = _string_spans(stripped)
        if not spans or spans[0][0] != 0:
            return None
        start, stop = spans[0]
        if not stripped[stop:].lstrip().startswith("="):
            return None
        inner = stripped[start + 1 : stop - 1]
        return _unescape(inner) if stripped[0] == '"' else inner
    raw, sep, _ = line.partition("=")
    if not sep:
        return None
    key = raw.strip()
    return key if _BARE_KEY.fullmatch(key) else None


def _value_after_key(line: str) -> str | None:
    """The text after a `key = value` line's structural `=`, or None. The key may be a
    quoted string containing `=`, so the split is after the whole key, not at the first
    `=` -- otherwise `"a=b" = "x"` would split inside the key."""
    stripped = line.lstrip()
    if not stripped or stripped[0] in "#[":
        return None
    if stripped[0] in "\"'":
        spans = _string_spans(stripped)
        if not spans or spans[0][0] != 0:
            return None
        rest = stripped[spans[0][1] :].lstrip()
        return rest[1:].strip() if rest.startswith("=") else None
    raw, sep, rest = line.partition("=")
    if not sep or not _BARE_KEY.fullmatch(raw.strip()):
        return None
    return rest.strip()


def _line_value_string(line: str) -> str | None:
    """The string value on a `key = "value"` line -- basic (`"..."`) or literal (`'...'`) --
    or None when the value is not a lone string (an array, a number). Used to match an entry
    by a field. A basic string's closing quote is found honoring backslash escapes (so a
    value ending in `\\` is not mistaken for unterminated) and is unescaped; a literal string
    is taken verbatim."""
    value = _value_after_key(line)
    if value is None or not value or value[0] not in "\"'":
        return None
    spans = _string_spans(value)
    if not spans or spans[0][0] != 0:
        return None
    start, stop = spans[0]
    inner = value[start + 1 : stop - 1]
    return _unescape(inner) if value[0] == '"' else inner


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
    """`[` minus `]` on `line`, counting only brackets that are structure -- outside quoted
    strings and outside a trailing comment -- so a bracket inside a value or a `# note [`
    does not read as an opened or closed array."""
    bare = _without_strings(line)
    hash_at = bare.find("#")  # a `#` inside a string is already masked, so this is the real one
    if hash_at != -1:
        bare = bare[:hash_at]
    return bare.count("[") - bare.count("]")


def _without_strings(line: str) -> str:
    """`line` with every quoted string's characters replaced by spaces, so structural
    punctuation (`[`, `]`, `=`) can be found without the contents of strings interfering."""
    chars = list(line)
    for start, stop in _string_spans(line):
        for index in range(start, stop):
            chars[index] = " "
    return "".join(chars)


def _emit_key(key: str) -> str:
    """A TOML key for `key`: bare when it can be, a quoted basic string otherwise."""
    return key if _BARE_KEY.fullmatch(key) else _emit_string(key)


def _emit_value(value: TOMLValue) -> str:
    """`value` as TOML: a boolean, an integer, a float, a basic string, or a one-line array
    of strings. `bool` is checked before `int` because it is a subclass of it, and `float`
    after `int` so an integer is not spelled with a trailing `.0`. A value of any other type
    -- a dict, a set, `None`, bytes, or a sequence with a non-string element -- is a clear
    error, not silently emitted as the wrong thing (a dict would otherwise become an array
    of its keys, a set a nondeterministically-ordered array).

    Raises:
        TypeError: `value` is not a supported TOML value type.
        UnsupportedTOMLError: an integer is outside TOML's signed 64-bit range.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        if not -(2**63) <= value < 2**63:
            raise UnsupportedTOMLError(
                f"integer {value} is outside TOML's signed 64-bit range"
            )
        return str(value)
    if isinstance(value, float):
        # repr gives the shortest round-tripping form, and TOML spells inf/nan the same.
        return repr(value)
    if isinstance(value, str):
        return _emit_string(value)
    if isinstance(value, (list, tuple)):  # an ordered sequence of strings -> one-line array
        for index, one in enumerate(value):
            if not isinstance(one, str):
                raise TypeError(
                    f"a TOML array value must be a list/tuple of str; item {index} is "
                    f"{type(one).__name__}"
                )
        return "[" + ", ".join(_emit_string(one) for one in value) + "]"
    raise TypeError(
        f"unsupported TOML value type {type(value).__name__}; expected str, int, float, "
        f"bool, or a list/tuple of str"
    )


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
        elif "\ud800" <= char <= "\udfff":
            # A lone surrogate is not a Unicode scalar value, so it is not a valid TOML string
            # character and cannot be UTF-8 encoded. Refuse with a domain error here rather
            # than let it surface as a late UnicodeEncodeError at save().
            raise UnsupportedTOMLError(
                f"string contains a lone surrogate (U+{ord(char):04X}), which is not a valid "
                f"TOML string character"
            )
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
                if len(digits) != width:  # a truncated \uXX at end-of-text is not an escape
                    raise ValueError
                out.append(chr(int(digits, 16)))
                index += 2 + width
            except ValueError:
                out.append(char)
                index += 1
        else:
            out.append(nxt)
            index += 2
    return "".join(out)
