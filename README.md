# tomlite

[![check](https://github.com/seokhoonj/tomlite/actions/workflows/check.yml/badge.svg)](https://github.com/seokhoonj/tomlite/actions/workflows/check.yml)
[![PyPI](https://img.shields.io/pypi/v/tomlite)](https://pypi.org/project/tomlite/)
[![Python](https://img.shields.io/pypi/pyversions/tomlite)](https://pypi.org/project/tomlite/)
[![License](https://img.shields.io/pypi/l/tomlite)](https://github.com/seokhoonj/tomlite/blob/main/LICENSE)

tomlite edits a TOML config file without touching its comments or layout. Only the lines
that change are rewritten, so comments, blank lines, and aligned `=` stay as they were.

**English** | [한국어](README.ko.md)

```python
from tomlite import TOMLEditor

doc = TOMLEditor.load("config.toml")
doc.set_table_key("server", "port", 9090)
doc.save("config.toml")
```

## Install

```sh
pip install tomlite
```

No dependencies. Python 3.11+.

## Supported shapes

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
raises `UnsupportedTOMLError`.

## API

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

```python
doc = TOMLEditor.load("config.toml")

if not doc.has_in_array("user", match_field="name", match_value="bob"):
    doc.append_to_array("user", [("name", "bob"), ("role", "guest")])
doc.set_root_key("title", "My App", only_if_absent=True)
doc.set_table_key("server", "port", 9090)
doc.save("config.toml")
```

## Reading

Read the file with `tomllib`:

```python
import tomllib

with open("config.toml", "rb") as f:
    config = tomllib.load(f)
```

## Round-trip

tomlite reads back anything it writes. A value or key with a bracket, quote, backslash,
control character, or unusual line separator is escaped on write and restored on read.
Updating an entry keeps its inline comment; other lines stay unchanged. Line endings are
normalized to LF on load.

## License

MIT
