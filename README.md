# tomlite

[![check](https://github.com/seokhoonj/tomlite/actions/workflows/check.yml/badge.svg)](https://github.com/seokhoonj/tomlite/actions/workflows/check.yml)
[![PyPI](https://img.shields.io/pypi/v/tomlite)](https://pypi.org/project/tomlite/)
[![Python](https://img.shields.io/pypi/pyversions/tomlite)](https://pypi.org/project/tomlite/)
[![License](https://img.shields.io/pypi/l/tomlite)](https://github.com/seokhoonj/tomlite/blob/main/LICENSE)

**English** | [한국어](README.ko.md)

Change values in a TOML config file from Python, keeping the comments and layout the user
wrote. tomlite rewrites only the lines that change, so hand-written comments, blank lines,
and aligned `=` survive the edit.

## 1. Install

```sh
pip install tomlite
```

No dependencies. Python 3.11+. Works on Windows, macOS, and Linux.

## 2. Quickstart

```python
from tomlite import TOMLEditor

doc = TOMLEditor.load("config.toml")                      # read the file, or an empty document if it is new

# add a [[user]] block only if no user named "bob" is there yet
if not doc.has_in_array("user", match_field="name", match_value="bob"):
    doc.append_to_array("user", [("name", "bob"), ("role", "guest")])

doc.set_root_key("title", "My App", only_if_absent=True)  # set title only if it is absent
doc.set_table_key("server", "debug", False)               # change [server].debug to false
doc.save("config.toml")                                   # write it back, keeping the comments and layout
```

Read the values back with `tomllib`:

```python
import tomllib

with open("config.toml", "rb") as f:
    config = tomllib.load(f)
```

## 3. Supported formats

tomlite edits three shapes — the ones a machine-managed config file uses:

```toml
title = "My App"                 # top-level key

[server]                         # table
host = "localhost"
port = 8080
debug = true
tags = ["web", "prod"]           # values: str, int, float, bool, string array

[[user]]                         # table array, entries matched by a field
name = "alice"
role = "admin"
```

A construct its line scanner can't edit safely — a multi-line string or a dotted key
(`a.b = 1`) — raises `UnsupportedTOMLError` instead of risking corruption; reading and
`dumps` still work.

## 4. Round-trip

Any value is stored safely and reads back unchanged, even one with quotes, brackets, or
backslashes. Changing a value keeps the comment on its line, an array you wrote across
several lines stays multi-line, and the file's newline style (LF or CRLF) is preserved. An
edit that would make the file invalid TOML is refused and the file left untouched.

## 5. API

| Method | Description |
|---|---|
| `TOMLEditor.load(path)` | Read a file; an empty document if it does not exist. |
| `TOMLEditor.loads(text)` | A document from a TOML string. |
| `.dumps()` → `str` | The document as text. |
| `.save(path)` | Write atomically, keeping an existing file's mode. |
| `.set_root_key(key, value, *, only_if_absent=False, multiline=False)` | Set a top-level key. `only_if_absent` skips an existing value. |
| `.unset_root_key(key)` → `bool` | Remove a top-level key. |
| `.has_in_array(array, *, match_field, match_value)` → `bool` | Whether a `[[array]]` block has `match_field = match_value`. |
| `.append_to_array(array, fields, *, before_table=None, multiline=False)` | Add a `[[array]]` block, optionally before a named table. |
| `.update_in_array(array, *, match_field, match_value, field, value, multiline=False)` → `bool` | Set `field` in the matched block. |
| `.remove_from_array(array, *, match_field, match_value)` → `bool` | Remove the matched block. |
| `.set_table_key(table, key, value, *, multiline=False)` | Set `key` in `[table]`, creating the table if needed. |
| `.unset_table_key(table, key)` → `bool` | Remove `key` from `[table]`. |

Values are `str`, `int`, `float`, `bool`, or a sequence of `str`. Match arguments are
keyword-only. `multiline=True` writes an array value one item per line; replacing a
multi-line array with a non-empty one keeps it multi-line.

## 6. License

[MIT](LICENSE)
