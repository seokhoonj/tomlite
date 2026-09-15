# tomlite

[![check](https://github.com/seokhoonj/tomlite/actions/workflows/check.yml/badge.svg)](https://github.com/seokhoonj/tomlite/actions/workflows/check.yml)
[![PyPI](https://img.shields.io/pypi/v/tomlite)](https://pypi.org/project/tomlite/)
[![Python](https://img.shields.io/pypi/pyversions/tomlite)](https://pypi.org/project/tomlite/)
[![License](https://img.shields.io/pypi/l/tomlite)](https://github.com/seokhoonj/tomlite/blob/main/LICENSE)

Change a TOML config file from your code **without throwing away the comments and layout
the user wrote.** `tomlite` edits the file's lines in place — it touches only what changes,
so a hand-written `# note`, a blank line, and a column of aligned `=` all survive an edit.

Reading TOML is already solved by the standard library (`tomllib`); `tomlite` is the other
half — writing — kept small and dependency-free.

**English** | [한국어](README.ko.md)

```python
from tomlite import TOMLEditor

doc = TOMLEditor.load("config.toml")
doc.set_table_key("contacts", "lead", "lead@example.com")
doc.save("config.toml")
```

## When it fits

`tomlite` is small on purpose. It fits when:

- **You want to add, change, or remove a few entries in a config file the program owns**,
  and keep the user's comments and layout intact.
- **Reading is already covered.** The standard library parses TOML (`tomllib`); `tomlite`
  only does the part it doesn't — a comment-preserving *write*.
- **The file has a flat shape**: a few top-level keys, a `[[table array]]` or two, a
  `[table]` of keys, with string / number / boolean / one-line-array values.

It is deliberately not a general TOML manipulation library. TOML outside that shape —
nested tables, inline tables, arrays of arrays, dotted-key trees — is out of contract;
for that, use a full-featured TOML library instead.

## Install

```sh
pip install tomlite
```

It pulls in nothing else. Python 3.11+.

## What it edits

`tomlite` understands three shapes — the ones a config file managed by a program uses:

```toml
default_account = "personal"     # a top-level key

[[accounts]]                     # a table array: entries matched by a field
email = "you@naver.com"
alias = "personal"

[contacts]                       # a flat table of keys
lead = "lead@example.com"
team = ["lead", "boss"]          # values: string, int, bool, or a one-line string array
```

## API

`TOMLEditor` is a file held as lines. Load it, apply edits, save it.

| Method | What it does |
|---|---|
| `TOMLEditor.load(path)` | Read a file (an empty document if it does not exist yet). |
| `TOMLEditor.loads(text)` | A document from a TOML string. |
| `.dumps()` → `str` | The document as text. |
| `.save(path)` | Write atomically, preserving an existing file's mode. |
| `.set_root_key(key, value, *, only_if_absent=False)` | Set a top-level key. `only_if_absent` seeds a default without overwriting. |
| `.unset_root_key(key)` → `bool` | Remove a top-level key. |
| `.has_in_array(array, *, match_field, match_value)` → `bool` | Whether a `[[array]]` block has `match_field = match_value`. |
| `.append_to_array(array, fields, *, before_table=None)` | Add a `[[array]]` block; optionally before a named table. |
| `.update_in_array(array, *, match_field, match_value, field, value)` → `bool` | In the block where `match_field = match_value`, set `field`. |
| `.remove_from_array(array, *, match_field, match_value)` → `bool` | Remove the block where `match_field = match_value`. |
| `.set_table_key(table, key, value)` | Set `key` in `[table]`, creating the table if needed. |
| `.unset_table_key(table, key)` → `bool` | Remove `key` from `[table]`. |

Values are `str`, `int`, `float`, `bool`, or a sequence of `str` (written as a one-line
array). A method that can find-nothing returns `bool`; a plain setter returns `None`. The
match arguments are keyword-only, because a row of interchangeable strings is easy to
misorder into a valid-but-wrong call.

### A worked example

```python
from tomlite import TOMLEditor

doc = TOMLEditor.load("config.toml")           # empty if the file is new

# add an account only if this address isn't configured yet
if not doc.has_in_array("accounts", match_field="email", match_value="you@gmail.com"):
    doc.append_to_array("accounts", [("email", "you@gmail.com"), ("alias", "work")],
                        before_table="contacts")

# seed the default the first time; later runs don't clobber it
doc.set_root_key("default_account", "work", only_if_absent=True)

# add or update an address-book entry
doc.set_table_key("contacts", "lead", "lead@example.com")

doc.save("config.toml")
```

Read the values back with the standard library:

```python
import tomllib
with open("config.toml", "rb") as f:
    config = tomllib.load(f)
```

## The round-trip guarantee

`tomlite` round-trips **anything it emits**. A value or key containing a bracket, an equals
sign, a quote, a backslash, a control character, or an exotic line separator is written with
full escaping and read back intact — it cannot corrupt the file on a later edit. Updating an
entry keeps the inline comment on that line, and every other line's content is unchanged
(loading normalizes line endings to LF, so on a CRLF file the endings — not the content —
change).

What is out of contract is a value `tomlite` never *writes*: a nested array, an inline
table, or a multi-line value other than a one-per-line array of scalars. In particular, a
**multi-line string** (`"""…"""` / `'''…'''`) whose interior lines would be misread as
structure makes `tomlite` **refuse the edit with `UnsupportedTOMLError` rather than corrupt
the file** — reading and `dumps` still work. For arbitrary TOML, use a full-featured TOML
library instead.

## License

MIT
