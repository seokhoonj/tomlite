"""tomlite -- a tiny, zero-dependency TOML editor that preserves comments and layout.

Read a TOML file with the standard library's `tomllib`; edit it with `TOMLEditor`. An
edit changes only the lines it touches, so hand-written comments, blank lines, and aligned
`=` columns survive:

    from tomlite import TOMLEditor

    doc = TOMLEditor.load("config.toml")
    doc.set_table_key("contacts", "lead", "lead@example.com")
    doc.save("config.toml")

It is not a general TOML library -- it edits the shape a machine-managed config file takes
(a top-level key, `[[table array]]` entries, a flat `[table]`), with scalar and string-array
values (on one line or one per line), and round-trips anything it emits. See `TOMLEditor`
for the contract.
"""

from tomlite.document import (
    TOMLEditor,
    TomliteError,
    TOMLScalar,
    TOMLValue,
    UnsupportedTOMLError,
)

__all__ = [
    "TOMLEditor",
    "TOMLScalar",
    "TOMLValue",
    "TomliteError",
    "UnsupportedTOMLError",
]

__version__ = "0.1.1"
