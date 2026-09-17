"""TOMLEditor: edits change only what they touch, and round-trip anything they emit.

Two promises are pinned here. First, the comment-preservation promise: a hand-written
comment, an aligned `=`, and a neighbouring entry survive an edit byte-for-byte. Second,
the round-trip promise: a value or key containing a bracket, an equals sign, a quote, a
backslash, a control character, or an exotic line separator is written and read back
intact, and cannot corrupt the file on a later edit. Round-trips are checked against the
standard library's own parser (`tomllib`), which is the real reader.
"""

import tomllib
from pathlib import Path
from typing import Any

import pytest

from tomlite import TOMLEditor, UnsupportedTOMLError


def _doc(text: str) -> TOMLEditor:
    return TOMLEditor.loads(text)


def _parsed(doc: TOMLEditor) -> dict[str, Any]:
    """The document as the real reader sees it -- proves the emitted text is valid TOML."""
    return tomllib.loads(doc.dumps())


# -- seeding and scalars ----------------------------------------------------


def test_seed_a_file_from_nothing():
    doc = TOMLEditor([])
    doc.append_to_array("accounts", [("email", "you@naver.com"), ("alias", "me")])
    doc.set_root_key("default_account", "me", only_if_absent=True)
    assert doc.dumps() == (
        'default_account = "me"\n'
        "\n"
        "[[accounts]]\n"
        'email = "you@naver.com"\n'
        'alias = "me"\n'
    )


def test_set_root_key_only_if_absent_keeps_an_existing_value():
    doc = _doc('default_account = "me"\n')
    doc.set_root_key("default_account", "other", only_if_absent=True)
    assert doc.dumps() == 'default_account = "me"\n'


def test_set_root_key_replaces_without_the_guard():
    doc = _doc('default_account = "me"\n')
    doc.set_root_key("default_account", "other")
    assert doc.dumps() == 'default_account = "other"\n'


def test_root_key_only_matches_above_the_first_table():
    doc = _doc('[[accounts]]\nemail = "x@naver.com"\n')
    doc.set_root_key("email", "top@naver.com")
    text = doc.dumps()
    assert text.startswith('email = "top@naver.com"')
    assert 'email = "x@naver.com"' in text  # the in-table key is untouched


def test_int_and_bool_scalars():
    doc = TOMLEditor([])
    doc.set_root_key("poll_interval", 30)
    doc.set_table_key("options", "verbose", True)
    assert _parsed(doc) == {"poll_interval": 30, "options": {"verbose": True}}


# -- comment / layout preservation ------------------------------------------


def test_append_preserves_comments_and_alignment():
    original = (
        'default_account = "me"\n'
        "\n"
        "# my mailbox\n"
        "[[accounts]]\n"
        'email = "you@naver.com"\n'
        'alias = "me"\n'
        "\n"
        "[contacts]\n"
        "# people\n"
        'lead = "lead@example.com"\n'
        'boss = "boss@example.com"\n'
        'team = ["lead", "boss"]   # weekly\n'
    )
    doc = _doc(original)
    doc.set_table_key("contacts", "friend", "friend@example.com")
    text = doc.dumps()
    assert original in text  # every original line survives untouched
    assert 'friend = "friend@example.com"' in text
    assert 'team = ["lead", "boss"]   # weekly' in text  # neighbour undisturbed


def test_update_replaces_only_that_value():
    doc = _doc('[contacts]\n# people\nlead = "lead@example.com"\nboss = "boss@x.com"\n')
    doc.set_table_key("contacts", "lead", "lead@newco.com")
    assert doc.dumps() == (
        "[contacts]\n# people\nlead = \"lead@newco.com\"\nboss = \"boss@x.com\"\n"
    )


def test_update_keeps_the_inline_comment_on_the_matched_line():
    doc = _doc('[contacts]\nlead = "old@x.com"   # the team lead\n')
    doc.set_table_key("contacts", "lead", "new@x.com")
    assert doc.dumps() == '[contacts]\nlead = "new@x.com"   # the team lead\n'


def test_updating_a_multiline_array_keeps_it_multiline_and_spares_the_next_entry():
    doc = _doc(
        "[contacts]\n"
        "team = [\n"
        '    "lead",\n'
        '    "boss",\n'
        "]\n"
        'me = "you@naver.com"\n'
    )
    doc.set_table_key("contacts", "team", ("lead", "boss", "friend"))
    assert doc.dumps() == (
        "[contacts]\n"
        "team = [\n"
        '    "lead",\n'
        '    "boss",\n'
        '    "friend",\n'
        "]\n"
        'me = "you@naver.com"\n'
    )


def test_updating_a_one_line_array_stays_one_line():
    doc = _doc('[contacts]\nteam = ["lead", "boss"]\n')
    doc.set_table_key("contacts", "team", ("lead", "boss", "friend"))
    assert doc.dumps() == '[contacts]\nteam = ["lead", "boss", "friend"]\n'


def test_multiline_array_keeps_its_indent_and_opener_comment():
    doc = _doc(
        "hosts = [  # production\n"
        '  "alpha.internal.example.com",\n'
        '  "bravo.internal.example.com",\n'
        "]\n"
    )
    doc.set_root_key(
        "hosts",
        [
            "alpha.internal.example.com",
            "bravo.internal.example.com",
            "charlie.internal.example.com",
        ],
    )
    assert doc.dumps() == (
        "hosts = [  # production\n"
        '  "alpha.internal.example.com",\n'
        '  "bravo.internal.example.com",\n'
        '  "charlie.internal.example.com",\n'
        "]\n"
    )


def test_multiline_array_keeps_the_closing_bracket_comment():
    doc = _doc('xs = [\n  "a",\n  "b",\n]  # tail\n')
    doc.set_root_key("xs", ["a", "b", "c"])
    assert doc.dumps() == 'xs = [\n  "a",\n  "b",\n  "c",\n]  # tail\n'


def test_replacing_an_empty_multiline_array_indents_items_four_spaces():
    doc = _doc("xs = [\n]\n")  # no item line to read an indent from
    doc.set_root_key("xs", ["a", "b"])
    assert doc.dumps() == 'xs = [\n    "a",\n    "b",\n]\n'


def test_a_multiline_array_tomlite_wrote_can_be_re_edited():
    doc = _doc('xs = [\n  "a",\n  "b",\n]\n')
    doc.set_root_key("xs", ["a", "b", "c"])  # stays multi-line
    reloaded = TOMLEditor.loads(doc.dumps())  # our own multi-line output is not refused
    reloaded.set_root_key("xs", ["a", "b", "c", "d"])
    assert '  "d",\n' in reloaded.dumps()
    assert _parsed(reloaded)["xs"] == ["a", "b", "c", "d"]


def test_multiline_flag_authors_a_new_array_multi_line():
    doc = TOMLEditor([])
    doc.set_root_key("packages", ["alpha", "bravo", "charlie"], multiline=True)
    assert doc.dumps() == (
        "packages = [\n"
        '    "alpha",\n'
        '    "bravo",\n'
        '    "charlie",\n'
        "]\n"
    )
    assert _parsed(doc)["packages"] == ["alpha", "bravo", "charlie"]


def test_a_new_array_is_one_line_by_default():
    doc = TOMLEditor([])
    doc.set_root_key("packages", ["alpha", "bravo"])
    assert doc.dumps() == 'packages = ["alpha", "bravo"]\n'


def test_multiline_flag_converts_a_one_line_array():
    doc = TOMLEditor.loads('xs = ["a", "b"]\n')
    doc.set_root_key("xs", ["a", "b", "c"], multiline=True)
    assert doc.dumps() == 'xs = [\n    "a",\n    "b",\n    "c",\n]\n'


def test_multiline_flag_works_on_set_table_key():
    doc = TOMLEditor([])
    doc.set_table_key("t", "xs", ["a", "b"], multiline=True)
    assert doc.dumps() == '[t]\nxs = [\n    "a",\n    "b",\n]\n'


def test_multiline_flag_is_ignored_for_a_scalar():
    doc = TOMLEditor([])
    doc.set_root_key("port", 8080, multiline=True)
    assert doc.dumps() == "port = 8080\n"


def test_a_group_is_written_as_a_one_line_array():
    doc = TOMLEditor([])
    doc.set_table_key("contacts", "team", ("lead", "boss@example.com"))
    assert doc.dumps() == '[contacts]\nteam = ["lead", "boss@example.com"]\n'


def test_contact_is_inserted_before_a_following_section():
    doc = _doc('[contacts]\nlead = "lead@x.com"\n\n[options]\nverbose = true\n')
    doc.set_table_key("contacts", "boss", "boss@x.com")
    text = doc.dumps()
    assert text.index("boss@x.com") < text.index("[options]")  # stays inside [contacts]
    assert _parsed(doc)["contacts"] == {"lead": "lead@x.com", "boss": "boss@x.com"}


# -- array-of-tables --------------------------------------------------------


def test_update_in_array_matched_by_a_field():
    doc = _doc(
        "[[accounts]]\n"
        'email = "you@naver.com"\n'
        'alias = "me"\n'
        "\n"
        "[[accounts]]\n"
        'email = "you@gmail.com"\n'
        'alias = "work"\n'
    )
    found = doc.update_in_array(
        "accounts", match_field="email", match_value="you@gmail.com",
        field="alias", value="office",
    )
    assert found
    text = doc.dumps()
    assert 'alias = "office"' in text
    assert 'alias = "me"' in text  # the other block is untouched
    assert 'alias = "work"' not in text


def test_update_in_array_inserts_a_missing_field_after_the_match():
    doc = _doc('[[accounts]]\nemail = "you@gmail.com"\n')
    found = doc.update_in_array(
        "accounts", match_field="email", match_value="you@gmail.com",
        field="alias", value="work",
    )
    assert found
    assert doc.dumps() == '[[accounts]]\nemail = "you@gmail.com"\nalias = "work"\n'


def test_update_in_array_reports_a_missing_block():
    doc = _doc('[[accounts]]\nemail = "you@gmail.com"\n')
    assert not doc.update_in_array(
        "accounts", match_field="email", match_value="absent@x.com",
        field="alias", value="a",
    )


def test_has_in_array():
    doc = _doc('[[accounts]]\nemail = "you@gmail.com"\n')
    assert doc.has_in_array("accounts", match_field="email", match_value="you@gmail.com")
    assert not doc.has_in_array("accounts", match_field="email", match_value="nobody@x.com")


def test_append_before_a_table_keeps_arrays_grouped_above_it():
    doc = _doc(
        'default_account = "me"\n'
        "\n"
        "[[accounts]]\n"
        'email = "you@naver.com"\n'
        "\n"
        "[contacts]\n"
        'lead = "lead@example.com"\n'
    )
    doc.append_to_array("accounts", [("email", "you@gmail.com")], before_table="contacts")
    text = doc.dumps()
    assert text.index("you@gmail.com") < text.index("[contacts]")
    # the new block is blank-separated from the following header, not butted against it
    assert '"you@gmail.com"\n\n[contacts]' in text


def test_append_before_a_table_lands_above_that_tables_comment():
    doc = _doc(
        "[[accounts]]\n"
        'email = "a@x.com"\n'
        "\n"
        "# the settings section\n"
        "[settings]\n"
        'theme = "dark"\n'
    )
    doc.append_to_array("accounts", [("email", "b@x.com")], before_table="settings")
    text = doc.dumps()
    # the comment stays attached to its header; the new block goes above the comment
    assert text.index("b@x.com") < text.index("# the settings section")
    assert "# the settings section\n[settings]" in text
    assert _parsed(doc)["accounts"] == [{"email": "a@x.com"}, {"email": "b@x.com"}]


def test_append_before_an_array_of_tables_is_positioned_not_dropped_at_eof():
    # before_table may name a [[table array]], not only a plain [table]; the block lands
    # before it rather than silently falling through to end of file.
    doc = _doc(
        "[[servers]]\n"
        'host = "s1"\n'
        "\n"
        "[[accounts]]\n"
        'email = "a@x.com"\n'
    )
    doc.append_to_array("accounts", [("email", "b@x.com")], before_table="servers")
    text = doc.dumps()
    assert text.index("b@x.com") < text.index("[[servers]]")


def test_append_to_array_writes_a_multiline_field_when_asked():
    doc = TOMLEditor([])
    doc.append_to_array(
        "accounts",
        [("email", "x@y.com"), ("roles", ["admin", "user"])],
        multiline=True,
    )
    assert doc.dumps() == (
        "[[accounts]]\n"
        'email = "x@y.com"\n'
        "roles = [\n"
        '    "admin",\n'
        '    "user",\n'
        "]\n"
    )
    assert _parsed(doc)["accounts"] == [{"email": "x@y.com", "roles": ["admin", "user"]}]


def test_append_to_array_field_array_is_one_line_by_default():
    doc = TOMLEditor([])
    doc.append_to_array("accounts", [("roles", ["admin", "user"])])
    assert doc.dumps() == '[[accounts]]\nroles = ["admin", "user"]\n'


# -- the round-trip promise (values/keys with TOML-special characters) ------


def test_a_dotted_key_is_quoted_and_round_trips():
    doc = TOMLEditor([])
    doc.set_table_key("contacts", "jane.doe", "jane@example.com")
    assert doc.dumps() == '[contacts]\n"jane.doe" = "jane@example.com"\n'
    assert _parsed(doc)["contacts"] == {"jane.doe": "jane@example.com"}
    doc.set_table_key("contacts", "jane.doe", "jane@newco.com")  # finds the quoted key
    assert _parsed(doc)["contacts"] == {"jane.doe": "jane@newco.com"}


def test_a_value_containing_brackets_does_not_corrupt_the_next_edit():
    doc = TOMLEditor([])
    doc.set_table_key("contacts", "foo", "a[b]c@x.com")  # brackets in the value
    doc.set_table_key("contacts", "lead", "lead@x.com")
    doc.set_table_key("contacts", "lead", "new@x.com")  # update -- must find lead, not dup
    parsed = _parsed(doc)["contacts"]
    assert parsed == {"foo": "a[b]c@x.com", "lead": "new@x.com"}


def test_a_value_containing_an_equals_sign_round_trips():
    doc = TOMLEditor([])
    doc.set_table_key("contacts", "foo", "a=b@x.com")
    doc.set_table_key("contacts", "foo", "c=d@x.com")  # update, not duplicate
    assert _parsed(doc)["contacts"] == {"foo": "c=d@x.com"}


def test_a_quoted_key_containing_an_equals_sign_round_trips():
    doc = TOMLEditor([])
    doc.set_table_key("contacts", "a=b", "x@y.com")
    doc.set_table_key("contacts", "a=b", "z@y.com")  # update, not duplicate
    assert _parsed(doc)["contacts"] == {"a=b": "z@y.com"}


def test_control_characters_are_escaped_and_round_trip():
    doc = TOMLEditor([])
    for name, char in [("esc", "\x1b"), ("vtab", "\x0b"), ("ff", "\x0c"), ("nul", "\x00")]:
        doc.set_table_key("contacts", name, f"a{char}b")
    parsed = _parsed(doc)["contacts"]  # must be valid TOML despite the control chars
    assert parsed == {"esc": "a\x1bb", "vtab": "a\x0bb", "ff": "a\x0cb", "nul": "a\x00b"}


def test_a_unicode_line_separator_is_not_split_on_reload():
    doc = TOMLEditor([])
    doc.set_table_key("contacts", "foo", "a b@x.com")  # U+2028 is legal in a value
    reloaded = TOMLEditor.loads(doc.dumps())  # must not split the line
    reloaded.set_table_key("contacts", "foo", "new@x.com")  # update, not duplicate
    assert _parsed(reloaded)["contacts"] == {"foo": "new@x.com"}


def test_a_value_ending_in_a_backslash_is_matched_by_its_field():
    doc = TOMLEditor([])
    doc.append_to_array("accounts", [("email", "x@y.com\\"), ("alias", "me")])
    # the escaped backslash must not fool the closing-quote scan
    assert doc.has_in_array("accounts", match_field="email", match_value="x@y.com\\")
    found = doc.update_in_array(
        "accounts", match_field="email", match_value="x@y.com\\",
        field="alias", value="work",
    )
    assert found
    assert doc.dumps().count("[[accounts]]") == 1  # updated in place, no duplicate block
    assert _parsed(doc)["accounts"][0] == {"email": "x@y.com\\", "alias": "work"}


# -- I/O --------------------------------------------------------------------


def test_crlf_input_keeps_its_crlf_endings():
    doc = TOMLEditor.loads('[contacts]\r\nlead = "lead@x.com"\r\n')
    doc.set_table_key("contacts", "boss", "boss@x.com")
    out = doc.dumps()
    assert out.count("\n") == out.count("\r\n")  # every newline is CRLF, the added line included
    assert 'boss = "boss@x.com"\r\n' in out
    assert _parsed(doc)["contacts"] == {"lead": "lead@x.com", "boss": "boss@x.com"}


def test_save_preserves_crlf_endings(tmp_path: Path):
    path = tmp_path / "c.toml"
    path.write_bytes(b'a = 1\r\nb = 2\r\n')
    doc = TOMLEditor.load(path)
    doc.set_root_key("a", 9)
    doc.save(path)
    assert path.read_bytes() == b"a = 9\r\nb = 2\r\n"  # edited and untouched lines both CRLF


def test_save_preserves_lf_endings(tmp_path: Path):
    path = tmp_path / "c.toml"
    path.write_bytes(b"a = 1\nb = 2\n")
    doc = TOMLEditor.load(path)
    doc.set_root_key("a", 9)
    doc.save(path)
    assert path.read_bytes() == b"a = 9\nb = 2\n"  # LF stays LF, no OS translation to CRLF


def test_save_is_atomic_and_preserves_mode(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text('[contacts]\nme = "you@naver.com"\n', encoding="utf-8")
    path.chmod(0o600)
    doc = TOMLEditor.load(path)
    doc.set_table_key("contacts", "lead", "lead@example.com")
    doc.save(path)
    assert path.stat().st_mode & 0o777 == 0o600
    assert 'lead = "lead@example.com"' in path.read_text(encoding="utf-8")
    assert not (tmp_path / "config.toml.tmp").exists()


def test_load_missing_file_is_empty(tmp_path: Path):
    assert TOMLEditor.load(tmp_path / "nope.toml").dumps() == ""


def test_save_creates_owner_only_parent(tmp_path: Path):
    path = tmp_path / "fresh" / "config.toml"
    doc = TOMLEditor([])
    doc.set_table_key("contacts", "me", "you@naver.com")
    doc.save(path)
    assert path.exists()
    assert (tmp_path / "fresh").stat().st_mode & 0o777 == 0o700


def test_save_accepts_a_string_path(tmp_path: Path):
    path = tmp_path / "config.toml"
    doc = TOMLEditor([])
    doc.set_root_key("default_account", "me")
    doc.save(str(path))
    assert TOMLEditor.load(str(path)).dumps() == 'default_account = "me"\n'


# -- float values -----------------------------------------------------------


def test_float_scalars_round_trip():
    doc = TOMLEditor([])
    doc.set_root_key("timeout", 2.5)
    doc.set_table_key("options", "ratio", 0.1)
    assert _parsed(doc) == {"timeout": 2.5, "options": {"ratio": 0.1}}


def test_a_whole_number_float_is_emitted_as_a_float_not_an_int():
    doc = TOMLEditor([])
    doc.set_root_key("rate", 2.0)
    assert doc.dumps() == "rate = 2.0\n"  # not `rate = 2`, which would read back as int


# -- removal ----------------------------------------------------------------


def test_unset_root_key_removes_it_and_its_separator():
    doc = _doc('default_account = "me"\n\n[[accounts]]\nemail = "x@naver.com"\n')
    assert doc.unset_root_key("default_account")
    assert doc.dumps() == '[[accounts]]\nemail = "x@naver.com"\n'


def test_unset_root_key_reports_a_miss():
    doc = _doc('[[accounts]]\nemail = "x@naver.com"\n')
    assert not doc.unset_root_key("default_account")


def test_remove_from_array_drops_the_block_and_spares_the_rest():
    doc = _doc(
        "[[accounts]]\n"
        'email = "a@naver.com"\n'
        'alias = "me"\n'
        "\n"
        "[[accounts]]\n"
        'email = "b@gmail.com"\n'
    )
    assert doc.remove_from_array("accounts", match_field="email", match_value="a@naver.com")
    assert _parsed(doc)["accounts"] == [{"email": "b@gmail.com"}]


def test_remove_from_array_reports_a_miss():
    doc = _doc('[[accounts]]\nemail = "a@naver.com"\n')
    assert not doc.remove_from_array("accounts", match_field="email", match_value="z@x.com")


def test_remove_from_array_keeps_a_comment_annotating_the_next_block():
    # The comment above the second header annotates the block that survives; removing the
    # first block must not swallow it (regression: `_table_end` used to fold trailing comment
    # lines into the removed span).
    doc = _doc(
        "[[accounts]]\n"
        'email = "a@naver.com"\n'
        "\n"
        "# the backup account\n"
        "[[accounts]]\n"
        'email = "b@gmail.com"\n'
    )
    assert doc.remove_from_array("accounts", match_field="email", match_value="a@naver.com")
    assert "# the backup account" in doc.dumps()
    assert _parsed(doc)["accounts"] == [{"email": "b@gmail.com"}]


def test_remove_from_array_keeps_stacked_trailing_comments():
    doc = _doc(
        "[[accounts]]\n"
        'email = "a@naver.com"\n'
        "# note one\n"
        "# note two\n"
        "[[accounts]]\n"
        'email = "b@gmail.com"\n'
    )
    assert doc.remove_from_array("accounts", match_field="email", match_value="a@naver.com")
    out = doc.dumps()
    assert "# note one" in out and "# note two" in out


def test_set_table_key_inserts_above_a_trailing_comment():
    # A new key lands against the last entry, not below a comment that trails the table.
    doc = _doc("[t]\na = 1\n# trailing note\n")
    doc.set_table_key("t", "b", 2)
    assert doc.dumps() == "[t]\na = 1\nb = 2\n# trailing note\n"


def test_unset_table_key_removes_only_that_key_and_keeps_comments():
    doc = _doc('[contacts]\n# people\nlead = "lead@x.com"\nboss = "boss@x.com"\n')
    assert doc.unset_table_key("contacts", "lead")
    assert doc.dumps() == '[contacts]\n# people\nboss = "boss@x.com"\n'


def test_unset_table_key_reports_a_miss():
    doc = _doc('[contacts]\nlead = "lead@x.com"\n')
    assert not doc.unset_table_key("contacts", "absent")


# -- multi-line strings are refused, not corrupted --------------------------


def test_editing_a_file_with_a_multiline_string_is_refused():
    doc = TOMLEditor.loads('[info]\nnote = """\nline one\nline two\n"""\n')
    with pytest.raises(UnsupportedTOMLError, match="triple-quoted string"):
        doc.set_table_key("contacts", "lead", "lead@x.com")
    with pytest.raises(UnsupportedTOMLError):
        doc.unset_root_key("anything")


def test_reading_a_multiline_string_file_is_left_intact():
    text = '[info]\nnote = """\nhello\n"""\n'
    # load and dumps do not scan, so a file tomlite cannot edit still round-trips on read
    assert TOMLEditor.loads(text).dumps() == text


# every editing operation refuses an unsupported document -- none silently edits it
_MUTATORS = [
    lambda d: d.set_root_key("k", "v"),
    lambda d: d.unset_root_key("k"),
    lambda d: d.set_table_key("t", "k", "v"),
    lambda d: d.unset_table_key("t", "k"),
    lambda d: d.append_to_array("a", [("f", "v")]),  # before_table=None (the EOF path)
    lambda d: d.append_to_array("a", [("f", "v")], before_table="t"),
    lambda d: d.has_in_array("a", match_field="f", match_value="v"),
    lambda d: d.update_in_array("a", match_field="f", match_value="v", field="g", value="w"),
    lambda d: d.remove_from_array("a", match_field="f", match_value="v"),
]


@pytest.mark.parametrize("op", _MUTATORS)
@pytest.mark.parametrize("delim", ['"""', "'''"])
def test_every_editing_operation_refuses_a_multiline_document(op, delim):
    doc = TOMLEditor.loads(f"note = {delim}\nline\n{delim}\n")
    before = doc.dumps()
    with pytest.raises(UnsupportedTOMLError):
        op(doc)
    assert doc.dumps() == before  # the refused op left the document untouched


# -- grammar edges: handle in-contract input, never corrupt -----------------


def test_set_root_key_replaces_a_root_level_multiline_array():
    doc = _doc('team = [\n    "lead",\n    "boss",\n]\nother = "x"\n')
    doc.set_root_key("team", "solo")  # must consume the whole span, not one line
    assert _parsed(doc) == {"team": "solo", "other": "x"}


def test_unset_root_key_removes_a_root_level_multiline_array():
    doc = _doc('team = [\n    "lead",\n    "boss",\n]\nother = "x"\n')
    assert doc.unset_root_key("team")
    assert _parsed(doc) == {"other": "x"}


def test_a_literal_string_key_is_updated_not_duplicated():
    doc = _doc("'a b' = \"old\"\n")  # a valid literal-string key
    doc.set_root_key("a b", "new")
    assert _parsed(doc) == {"a b": "new"}  # found and replaced, not a second entry


def test_a_literal_string_field_value_matches_an_array_entry():
    doc = _doc("[[accounts]]\nemail = 'you@gmail.com'\n")  # literal-string value
    assert doc.has_in_array("accounts", match_field="email", match_value="you@gmail.com")


# -- float, removal, escape, and I/O boundaries -----------------------------


def test_float_representation_edges_round_trip():
    import math

    doc = TOMLEditor([])
    doc.set_root_key("big", 1e100)
    doc.set_root_key("whole", 2.0)
    doc.set_root_key("pos_inf", math.inf)
    doc.set_root_key("neg_inf", -math.inf)
    doc.set_root_key("not_a_number", math.nan)
    parsed = _parsed(doc)
    assert parsed["big"] == 1e100 and isinstance(parsed["whole"], float)
    assert parsed["pos_inf"] == math.inf and parsed["neg_inf"] == -math.inf
    assert math.isnan(parsed["not_a_number"])


def test_remove_from_array_handles_first_only_and_eof_blocks():
    two = (
        '[[a]]\nk = "1"\n\n[[a]]\nk = "2"\n'
    )
    first = _doc(two)
    assert first.remove_from_array("a", match_field="k", match_value="1")  # start == 0
    assert _parsed(first)["a"] == [{"k": "2"}]
    last = _doc(two)
    assert last.remove_from_array("a", match_field="k", match_value="2")  # EOF block
    assert _parsed(last)["a"] == [{"k": "1"}]
    only = _doc('[[a]]\nk = "1"\n')
    assert only.remove_from_array("a", match_field="k", match_value="1")  # the only block
    assert _parsed(only) == {}


def test_unset_root_key_of_the_only_line_empties_the_document():
    doc = _doc('only = "x"\n')
    assert doc.unset_root_key("only")
    assert doc.dumps() == ""


def test_unset_table_key_keeps_the_header_when_the_table_becomes_empty():
    doc = _doc('[contacts]\n# people\nlead = "lead@x.com"\n')
    assert doc.unset_table_key("contacts", "lead")
    assert doc.dumps() == "[contacts]\n# people\n"
    assert _parsed(doc) == {"contacts": {}}


def test_update_in_array_keeps_inline_comment_and_ignores_a_hash_in_the_value():
    doc = _doc('[[a]]\nurl = "http://x/#frag"   # the endpoint\n')
    doc.update_in_array("a", match_field="url", match_value="http://x/#frag",
                        field="url", value="http://y/#new")
    assert doc.dumps() == '[[a]]\nurl = "http://y/#new"   # the endpoint\n'


@pytest.mark.parametrize("char", [chr(c) for c in range(0x20)] + ["\x7f", '"', "\\"])
def test_every_control_and_special_character_round_trips(char):
    doc = TOMLEditor([])
    doc.set_table_key("t", "k", f"a{char}b")
    assert _parsed(doc)["t"]["k"] == f"a{char}b"  # valid TOML, exact value back


@pytest.mark.parametrize("text", ["", 'k = "v"', 'k = "v"\n', 'k = "v"\r\n'])
def test_loads_then_dumps_is_idempotent_and_keeps_the_newline_style(text):
    once = TOMLEditor.loads(text).dumps()
    assert TOMLEditor.loads(once).dumps() == once  # a second round changes nothing
    if "\r\n" in text:
        assert once.count("\n") == once.count("\r\n")  # CRLF input stays CRLF
    elif once:
        assert "\r" not in once  # LF (or newline-less) input emits LF


def test_set_root_key_only_if_absent_ignores_a_same_named_key_inside_a_table():
    doc = _doc('[t]\ndefault = "in-table"\n')
    doc.set_root_key("default", "top", only_if_absent=True)  # no top-level `default` yet
    text = doc.dumps()
    assert text.startswith('default = "top"')  # seeded at the top
    assert 'default = "in-table"' in text  # the in-table key is not the top-level one


def test_save_creates_a_new_file_owner_only(tmp_path: Path):
    path = tmp_path / "c.toml"
    doc = TOMLEditor([])
    doc.set_root_key("k", "v")
    doc.save(path)
    assert path.stat().st_mode & 0o777 == 0o600  # a new file is owner-only


# -- out-of-grammar constructs are refused, never silently corrupted --------


def test_an_array_of_arrays_is_refused():
    doc = TOMLEditor.loads("[d]\nm = [\n  [1, 2],\n  [3, 4],\n]\nother = 5\n")
    with pytest.raises(UnsupportedTOMLError, match="array of arrays"):
        doc.set_table_key("d", "other", 9)


def test_a_bare_dotted_key_is_refused():
    for text in ("a.b = 1\n", "a . b = 1\n", "[t]\na.b = 1\n"):
        with pytest.raises(UnsupportedTOMLError, match="dotted"):
            TOMLEditor.loads(text).set_root_key("x", 1)


def test_a_mixed_quoted_dotted_key_is_refused():
    # `a."b.c"` and `"a".b` are nesting, invisible to the scanner -- refuse, do not corrupt.
    for text in ('a."b.c" = 1\n', '"a".b = 1\n'):
        with pytest.raises(UnsupportedTOMLError):
            TOMLEditor.loads(text).set_root_key("x", 1)


def test_a_quoted_dotted_key_is_not_flagged_as_dotted():
    # `"a.b"` is a single literal key, not nesting -- it must stay editable.
    doc = TOMLEditor.loads('"a.b" = 1\n')
    doc.set_root_key("a.b", 2)
    assert _parsed(doc) == {"a.b": 2}


def test_an_exotic_table_header_is_refused():
    for text in ('["c"]\nk = 1\n', "[a . b]\nk = 1\n", "[café]\nk = 1\n"):
        with pytest.raises(UnsupportedTOMLError, match="bare-key path"):
            TOMLEditor.loads(text).set_table_key("c", "k", 2)


def test_a_dotted_table_header_stays_editable():
    # `[a.b]` is a bare-key path (nested table) -- valid and editable, not refused.
    doc = TOMLEditor.loads("[a.b]\nk = 1\n")
    doc.set_table_key("a.b", "k", 2)
    assert _parsed(doc) == {"a": {"b": {"k": 2}}}


# -- headers matched by name (comment / whitespace tolerant) ----------------


def test_a_commented_table_header_is_matched_not_duplicated():
    doc = TOMLEditor.loads("[contacts]  # people\nlead = 1\n")
    doc.set_table_key("contacts", "lead", 2)
    assert _parsed(doc) == {"contacts": {"lead": 2}}  # updated in place, no dup table


def test_a_spaced_table_header_is_matched():
    doc = TOMLEditor.loads("[ contacts ]\nk = 1\n")
    doc.set_table_key("contacts", "k", 2)
    assert _parsed(doc) == {"contacts": {"k": 2}}


def test_a_commented_array_header_is_matched():
    doc = TOMLEditor.loads('[[a]]   # first\nid = "x"\nv = 1\n')
    assert doc.update_in_array("a", match_field="id", match_value="x", field="v", value=2)
    assert _parsed(doc)["a"] == [{"id": "x", "v": 2}]


def test_a_match_field_key_containing_an_equals_sign():
    doc = TOMLEditor.loads('[[a]]\n"k=v" = "x"\nn = 1\n')
    assert doc.has_in_array("a", match_field="k=v", match_value="x")


# -- key/table name collisions are refused, not corrupted -------------------


def test_set_root_key_refuses_a_name_that_is_a_table():
    for text in ("[a]\nb = 1\n", "[[a]]\nb = 1\n"):
        with pytest.raises(UnsupportedTOMLError, match="already a table"):
            TOMLEditor.loads(text).set_root_key("a", "x")


def test_set_table_key_refuses_a_name_that_is_a_root_key():
    doc = TOMLEditor.loads('a = "x"\n')
    with pytest.raises(UnsupportedTOMLError, match="already a top-level key"):
        doc.set_table_key("a", "k", 1)


def test_set_table_key_refuses_a_name_that_is_an_array_of_tables():
    # Opening [u] when [[u]] exists would make the same name two kinds -- tomllib rejects it.
    doc = TOMLEditor.loads('[[u]]\nid = "u0"\n')
    with pytest.raises(UnsupportedTOMLError, match="already an array-of-tables"):
        doc.set_table_key("u", "k", "v")


def test_set_table_key_allows_opening_a_table_whose_subtable_exists():
    # [u.x] then [u] is valid TOML (the subtable implicitly creates u; [u] defines it), so
    # this must NOT be refused as a collision.
    doc = TOMLEditor.loads('[u.x]\na = 1\n')
    doc.set_table_key("u", "b", 2)
    assert _parsed(doc) == {"u": {"x": {"a": 1}, "b": 2}}


def test_append_onto_a_dotted_header_table_is_refused_not_corrupted():
    # [accounts.personal] makes `accounts` an implicit table, so appending [[accounts]] would
    # make one name two kinds -- tomllib rejects it. (The legacy-config shape that first
    # surfaced this.) Must refuse and leave the file untouched.
    src = '[accounts.personal]\nemail = "x@naver.com"\n'
    doc = TOMLEditor.loads(src)
    with pytest.raises(UnsupportedTOMLError):
        doc.append_to_array("accounts", [("email", "y@gmail.com")])
    assert doc.dumps() == src  # rolled back


def test_dotted_table_name_colliding_with_a_root_key_is_refused():
    doc = TOMLEditor.loads("x = 1\n")
    with pytest.raises(UnsupportedTOMLError):
        doc.set_table_key("x.y.z", "k", 2)  # [x.y.z] would make root key x a table
    assert doc.dumps() == "x = 1\n"


def test_set_table_key_field_that_collides_with_an_array_of_tables_is_refused():
    doc = TOMLEditor.loads("[[a.b]]\nx = 1\n")  # a.b is an array-of-tables
    with pytest.raises(UnsupportedTOMLError):
        doc.set_table_key("a", "b", 1)  # [a] with key b would set a.b to a scalar
    assert doc.dumps() == "[[a.b]]\nx = 1\n"


def test_append_to_array_rejects_duplicate_field_keys():
    with pytest.raises(ValueError, match="duplicate field key"):
        TOMLEditor([]).append_to_array("t", [("a", "1"), ("a", "2")])


def test_a_refused_edit_leaves_the_document_untouched():
    doc = TOMLEditor.loads('x = 1\ny = 2\n')
    with pytest.raises(UnsupportedTOMLError):
        doc.set_table_key("x.z", "k", 3)
    assert doc.dumps() == "x = 1\ny = 2\n"  # atomic: nothing partially written


def test_no_single_edit_ever_emits_invalid_toml_fuzz():
    # The load-bearing invariant: for any valid input and any single edit (every writer AND
    # every remover), the result parses in tomllib OR the edit is refused -- never silently
    # corrupt. A compact deterministic fuzz so a future change that reopens a corruption path
    # fails here.
    import random

    def scalar() -> str:
        return random.choice(['1', '"s"', "'lit'", '"a=b"', "0xFF", 'true', '["p","q"]'])

    def doc_text() -> str:
        lines = []
        for _ in range(random.randint(0, 3)):
            lines.append(random.choice([f'{random.choice(["a", "x"])} = {scalar()}', "", "# c"]))
        for _ in range(random.randint(1, 5)):
            r = random.random()
            if r < 0.4:
                lines.append(f'{random.choice(["a", "name", "x"])} = {scalar()}')
            elif r < 0.7:
                lines.append(f'[{random.choice(["t", "a.b", "x.y", "x.y.z"])}]')
            else:
                lines.append(f'[[{random.choice(["accounts", "x", "a.b"])}]]')
        return "\n".join(lines) + "\n"

    names = ["a", "x", "a.b", "x.y", "x.y.z", "accounts"]
    random.seed(2026)
    for _ in range(4000):
        src = doc_text()
        try:
            tomllib.loads(src)  # only edit valid TOML
        except tomllib.TOMLDecodeError:
            continue
        doc = TOMLEditor.loads(src)
        name = random.choice(names)
        op = random.random()
        try:
            if op < 0.24:
                doc.set_root_key(name, "v")
            elif op < 0.44:
                doc.set_table_key(name, random.choice(["k", "a", "b"]), 1)
            elif op < 0.62:
                doc.append_to_array(name, [("a", "1"), (random.choice(["b", "c"]), "y")])
            elif op < 0.78:
                doc.update_in_array(name, match_field="a", match_value="1", field="k", value=2)
            elif op < 0.85:  # removers too -- they carry no net, so the fuzz must cover them
                doc.unset_root_key(name)
            elif op < 0.93:
                doc.unset_table_key(name, random.choice(["k", "a", "b"]))
            else:
                doc.remove_from_array(name, match_field="a", match_value="1")
        except (UnsupportedTOMLError, TypeError, ValueError):
            continue  # refused -- the safe branch of handle-or-refuse
        tomllib.loads(doc.dumps())  # MUST parse; raises here if a corruption path reopened


def test_a_setter_edit_produces_exactly_the_expected_dict_fuzz():
    # Beyond validity: the edited file must parse to exactly the RIGHT dict -- the value set,
    # nothing else lost or changed -- or be refused. Guards against a valid-but-wrong edit
    # (silent data loss / wrong value). Single-segment names so the expected dict is exact.
    import copy
    import random

    def kind(x: object) -> str | None:
        if isinstance(x, dict):
            return "table"
        if isinstance(x, list) and x and all(isinstance(e, dict) for e in x):
            return "aot"
        if x is None:
            return None
        return "value"  # scalar, scalar-array, or empty array = an inline value

    def scalar() -> str:
        return random.choice(["1", '"s"', "true", '"a=b"'])

    def doc_text() -> str:
        lines: list[str] = []
        for _ in range(random.randint(0, 2)):
            lines.append(random.choice([f'{random.choice(["a", "x"])} = {scalar()}', ""]))
        for _ in range(random.randint(0, 3)):
            r = random.random()
            if r < 0.4:
                lines.append(f'[{random.choice(["srv", "g"])}]\np = {scalar()}')
            elif r < 0.7:
                lines.append(f'[[{random.choice(["accounts", "items"])}]]\nid = {scalar()}')
            else:
                lines.append(f'{random.choice(["a", "x"])} = {random.choice([scalar(), chr(91) + chr(34) + "p" + chr(34) + chr(93)])}')
        return "\n".join(lines) + "\n"

    names = ["a", "x", "srv", "accounts", "items", "g", "new"]
    random.seed(7)
    for _ in range(3000):
        src = doc_text()
        try:
            d0 = tomllib.loads(src)
        except tomllib.TOMLDecodeError:
            continue
        doc = TOMLEditor.loads(src)
        name = random.choice(names)
        key = random.choice(["p", "k", "name"])
        op = random.random()
        k0 = kind(d0.get(name))
        expected = copy.deepcopy(d0)
        refuse = False
        try:
            if op < 0.34:  # set_root_key: reassigns a top-level key; refused only over a table/aot
                if k0 in ("table", "aot"):
                    refuse = True
                else:
                    expected[name] = "V"
                doc.set_root_key(name, "V")
            elif op < 0.67:  # set_table_key: opens/extends [name]; refused over a value or aot
                if k0 in ("aot", "value"):
                    refuse = True
                else:
                    expected.setdefault(name, {})[key] = 1
                doc.set_table_key(name, key, 1)
            else:  # append_to_array: adds a [[name]] block; refused over a table or value
                if k0 in ("table", "value"):
                    refuse = True
                else:
                    expected[name] = (list(d0[name]) if k0 == "aot" else []) + [{"id": "x"}]
                doc.append_to_array(name, [("id", "x")])
        except (UnsupportedTOMLError, TypeError, ValueError):
            assert refuse, f"over-refused a valid edit: {src!r} name={name} op={op}"
            continue
        assert not refuse, f"should have refused: {src!r} name={name} op={op}"
        assert tomllib.loads(doc.dumps()) == expected, f"wrong result for {src!r} name={name}"


def test_append_to_array_refuses_a_name_that_is_a_table():
    doc = TOMLEditor.loads('[u]\nid = "u0"\n')
    with pytest.raises(UnsupportedTOMLError, match="already a table"):
        doc.append_to_array("u", [("id", "x")])


def test_append_to_array_refuses_a_name_that_is_a_root_key():
    doc = TOMLEditor.loads('u = 1\n')
    with pytest.raises(UnsupportedTOMLError, match="already a top-level key"):
        doc.append_to_array("u", [("id", "x")])


def test_append_to_array_allows_a_second_block_of_an_existing_array():
    doc = TOMLEditor.loads('[[u]]\nid = "u0"\n')
    doc.append_to_array("u", [("id", "u1")])
    assert _parsed(doc)["u"] == [{"id": "u0"}, {"id": "u1"}]


def test_array_matching_is_on_string_fields_only():
    # Matching compares string-valued fields; a non-string field is simply not matched
    # (documented behavior, not a silent bug -- the caller gets a clear False).
    doc = TOMLEditor.loads('[[s]]\nport = 8080\nname = "old"\n')
    assert not doc.has_in_array("s", match_field="port", match_value="8080")


# -- brackets/triple-quotes inside comments and strings ---------------------


def test_an_open_bracket_in_a_comment_does_not_swallow_the_next_key():
    doc = _doc("[t]\na = 1  # todo [\nb = 2\n")
    doc.set_table_key("t", "a", 99)
    assert _parsed(doc) == {"t": {"a": 99, "b": 2}}  # b survives


def test_a_close_bracket_in_a_comment_does_not_orphan_an_array():
    doc = _doc('[t]\nx = [    # trailing ]\n  "a",\n  "b",\n]\ny = 9\n')
    doc.set_table_key("t", "x", "new")
    assert _parsed(doc) == {"t": {"x": "new", "y": 9}}


def test_a_triple_quote_in_a_value_or_comment_is_not_refused():
    for text in (
        'quote = \'She said """hi"""\'\n',  # literal-string value
        'x = 1  # see """docs"""\n',  # comment
        "x = \"has ''' inside\"\n",  # basic value containing '''
    ):
        doc = TOMLEditor.loads(text)
        doc.set_root_key("added", 1)  # must not raise
        assert '"""' in doc.dumps() or "'''" in doc.dumps()


def test_a_genuine_multiline_string_is_still_refused():
    with pytest.raises(UnsupportedTOMLError):
        TOMLEditor.loads('note = """\nhi\n"""\n').set_root_key("x", 1)


def test_a_single_line_triple_quoted_value_is_refused():
    # tomlite cannot represent triple-quoted strings, so it refuses rather than mis-scan.
    with pytest.raises(UnsupportedTOMLError):
        TOMLEditor.loads('x = """a"""\n').set_root_key("y", 1)


# -- header names that a header cannot be written from are refused ----------


def test_set_table_key_refuses_a_non_bare_table_name():
    for name in ("a b", "café", "a.b c", '"x"', ""):
        with pytest.raises(UnsupportedTOMLError, match="bare-key path"):
            TOMLEditor([]).set_table_key(name, "k", 1)


def test_append_to_array_refuses_a_non_bare_array_name():
    with pytest.raises(UnsupportedTOMLError, match="bare-key path"):
        TOMLEditor([]).append_to_array("a b", [("x", 1)])


# -- no double-blank drift --------------------------------------------------


def test_set_table_key_adds_no_second_blank_when_the_doc_ends_blank():
    doc = TOMLEditor.loads("[t]\nk = 1\n\n")
    doc.set_table_key("t2", "k", 1)
    assert "\n\n\n" not in doc.dumps()


def test_set_root_key_adds_no_second_blank_when_the_doc_starts_blank():
    doc = TOMLEditor.loads("\n[t]\nk = 1\n")
    doc.set_root_key("r", 1)
    assert "\n\n\n" not in doc.dumps()


# -- bad values are clear errors, never silently mis-emitted -----------------


def test_a_dict_value_is_a_clear_error_not_an_array_of_keys():
    with pytest.raises(TypeError, match="unsupported TOML value type"):
        TOMLEditor([]).set_root_key("k", {"a": 1})  # type: ignore[arg-type]


def test_a_set_value_is_rejected_not_emitted_in_nondeterministic_order():
    with pytest.raises(TypeError, match="unsupported TOML value type"):
        TOMLEditor([]).set_root_key("k", {"a", "b"})  # type: ignore[arg-type]


def test_none_and_bytes_values_are_clear_errors():
    for bad in (None, b"hi"):
        with pytest.raises(TypeError, match="unsupported TOML value type"):
            TOMLEditor([]).set_root_key("k", bad)  # type: ignore[arg-type]


def test_a_non_string_array_element_names_the_offender():
    with pytest.raises(TypeError, match="item 1 is int"):
        TOMLEditor([]).set_table_key("t", "k", ["a", 1])  # type: ignore[list-item]


def test_an_out_of_range_integer_is_refused():
    with pytest.raises(UnsupportedTOMLError, match="64-bit"):
        TOMLEditor([]).set_root_key("k", 2**63)


def test_a_lone_surrogate_value_is_refused_not_written():
    # A lone surrogate is not a valid TOML string character; refuse with a domain error at
    # emit time rather than let it surface as a UnicodeEncodeError at save().
    with pytest.raises(UnsupportedTOMLError, match="surrogate"):
        TOMLEditor([]).set_root_key("k", "\ud800")


def test_append_to_array_rejects_a_bare_string_for_fields():
    with pytest.raises(TypeError, match="sequence of"):
        TOMLEditor([]).append_to_array("a", "notalist")  # type: ignore[arg-type]


def test_append_to_array_rejects_a_wrong_arity_field():
    with pytest.raises(TypeError, match="key, value"):
        TOMLEditor([]).append_to_array("a", [("k",)])  # type: ignore[list-item]


def test_load_of_a_non_utf8_file_is_a_tomlite_error(tmp_path: Path):
    path = tmp_path / "c.toml"
    path.write_bytes(b'a = "\xff\xfe"\n')
    with pytest.raises(UnsupportedTOMLError, match="UTF-8"):
        TOMLEditor.load(path)
