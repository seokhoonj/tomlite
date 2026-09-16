# tomlite

[![check](https://github.com/seokhoonj/tomlite/actions/workflows/check.yml/badge.svg)](https://github.com/seokhoonj/tomlite/actions/workflows/check.yml)
[![PyPI](https://img.shields.io/pypi/v/tomlite)](https://pypi.org/project/tomlite/)
[![Python](https://img.shields.io/pypi/pyversions/tomlite)](https://pypi.org/project/tomlite/)
[![License](https://img.shields.io/pypi/l/tomlite)](https://github.com/seokhoonj/tomlite/blob/main/LICENSE)

**English** | [한국어](README.ko.md)

Change values in a TOML config file from Python, keeping the comments and layout the user
wrote. tomlite rewrites only the lines that change, so hand-written comments, blank lines,
and aligned `=` survive the edit.

```python
from tomlite import TOMLEditor

doc = TOMLEditor.load("config.toml")
doc.set_table_key("server", "debug", False)
doc.save("config.toml")
```

Works on Windows, macOS, and Linux. It installs nothing but itself — no other libraries
come along.

## 1. Install

```sh
pip install tomlite
```

Python 3.11+.

## 2. What it edits

tomlite edits three shapes — the ones a machine-managed config file uses:

```toml
title = "My App"                 # top-level key

[server]                         # table
host = "localhost"
port = 8080
debug = true
tags = ["web", "prod"]           # values: str, int, float, bool, one-line array

[[user]]                         # table array, entries matched by a field
name = "alice"
role = "admin"
```

A nested table, an inline table, an array of arrays, a dotted key, or a multi-line string
raises `UnsupportedTOMLError` at the edit — reading and `dumps` still work.

## 3. Editing

```python
doc = TOMLEditor.load("config.toml")

if not doc.has_in_array("user", match_field="name", match_value="bob"):
    doc.append_to_array("user", [("name", "bob"), ("role", "guest")])
doc.set_root_key("title", "My App", only_if_absent=True)
doc.set_table_key("server", "debug", False)
doc.save("config.toml")
```

Read the values back with `tomllib`:

```python
import tomllib

with open("config.toml", "rb") as f:
    config = tomllib.load(f)
```

## 4. Round-trip

tomlite reads back anything it writes. A value or key with a bracket, quote, backslash,
control character, or unusual line separator is escaped on write and restored on read.
Updating an entry keeps its inline comment; other lines stay unchanged. Line endings are
normalized to LF on load, so a CRLF file's endings change but its content does not.

## 5. API

| Method | Description |
|---|---|
| `TOMLEditor.load(path)` | Read a file; an empty document if it does not exist. |
| `TOMLEditor.loads(text)` | A document from a TOML string. |
| `.dumps()` → `str` | The document as text. |
| `.save(path)` | Write atomically, keeping an existing file's mode. |
| `.set_root_key(key, value, *, only_if_absent=False)` | Set a top-level key. `only_if_absent` skips an existing value. |
| `.unset_root_key(key)` → `bool` | Remove a top-level key. |
| `.has_in_array(array, *, match_field, match_value)` → `bool` | Whether a `[[array]]` block has `match_field = match_value`. |
| `.append_to_array(array, fields, *, before_table=None)` | Add a `[[array]]` block, optionally before a named table. |
| `.update_in_array(array, *, match_field, match_value, field, value)` → `bool` | Set `field` in the matched block. |
| `.remove_from_array(array, *, match_field, match_value)` → `bool` | Remove the matched block. |
| `.set_table_key(table, key, value)` | Set `key` in `[table]`, creating the table if needed. |
| `.unset_table_key(table, key)` → `bool` | Remove `key` from `[table]`. |

Values are `str`, `int`, `float`, `bool`, or a sequence of `str`. Match arguments are
keyword-only.

## 6. License

[MIT](LICENSE)
