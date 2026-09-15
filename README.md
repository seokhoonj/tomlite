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
from tomlite import TOMLDocument

doc = TOMLDocument.load("config.toml")
doc.set_table_key("contacts", "lead", "lead@example.com")
doc.save("config.toml")
```

## Why not `tomlkit`?

[tomlkit](https://pypi.org/project/tomlkit/) is the full-featured, style-preserving TOML
library — it models the whole document as a tree and can express any TOML. `tomlite` is a
smaller thing on purpose:

- **Read with `tomllib`, write with `tomlite`.** You already have a parser in the standard
  library. `tomlite` only does the part it doesn't: a comment-preserving *write*.
- **Zero dependencies**, pure Python, one small module.
- **A narrow, safe surface** for the shape a machine-managed config file actually takes —
  a few top-level keys, a `[[table array]]` or two, a flat `[table]` — rather than the
  whole TOML grammar.

If you need to manipulate arbitrary TOML (nested tables, inline tables, arrays of arrays,
dotted-key trees), reach for `tomlkit`. If you have a CLI that adds an account or a feed to
its own config and wants the user's comments left alone, `tomlite` is the smaller fit.

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

`TOMLDocument` is a file held as lines. Load it, apply edits, save it.

| Method | What it does |
|---|---|
| `TOMLDocument.load(path)` | Read a file (an empty document if it does not exist yet). |
| `TOMLDocument.loads(text)` | A document from a TOML string. |
| `.dumps()` → `str` | The document as text. |
| `.save(path)` | Write atomically, preserving an existing file's mode. |
| `.set_root_key(name, value, *, only_if_absent=False)` | Set a top-level key. `only_if_absent` seeds a default without overwriting. |
| `.has_in_array(array, *, field, value)` → `bool` | Whether a `[[array]]` block has `field = value`. |
| `.append_to_array(array, fields, *, before_table=None)` | Add a `[[array]]` block; optionally before a named table. |
| `.update_in_array(array, *, match_field, match_value, field, value)` → `bool` | In the block where `match_field = match_value`, set `field`. |
| `.set_table_key(table, key, value)` | Set `key` in `[table]`, creating the table if needed. |

Values are `str`, `int`, `bool`, or a sequence of `str` (written as a one-line array).
The match/field arguments are keyword-only, because a row of interchangeable strings is
easy to misorder into a valid-but-wrong call.

### A worked example

```python
from tomlite import TOMLDocument

doc = TOMLDocument.load("config.toml")           # empty if the file is new

# add an account only if this address isn't configured yet
if not doc.has_in_array("accounts", field="email", value="you@gmail.com"):
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
entry keeps the inline comment on that line, and every other line is left byte-for-byte.

What is out of contract is a value `tomlite` never *writes*: a nested array, an inline
table, or a multi-line value other than a one-per-line array of scalars. Hand-write one of
those and then edit the file with `tomlite`, and the edit is not guaranteed to land cleanly.
For arbitrary TOML, use `tomlkit`.

## License

MIT
