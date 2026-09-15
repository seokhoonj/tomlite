"""TOMLDocument: edits change only what they touch, and round-trip anything they emit.

Two promises are pinned here. First, the comment-preservation promise: a hand-written
comment, an aligned `=`, and a neighbouring entry survive an edit byte-for-byte. Second --
the one the council added -- the round-trip promise: a value or key containing a bracket,
an equals sign, a quote, a backslash, a control character, or an exotic line separator is
written and read back intact, and cannot corrupt the file on a later edit. Round-trips are
checked against the standard library's own parser (`tomllib`), which is the real reader.
"""

import tomllib
from pathlib import Path
from typing import Any

from tomlite import TOMLDocument


def _doc(text: str) -> TOMLDocument:
    return TOMLDocument.loads(text)


def _parsed(doc: TOMLDocument) -> dict[str, Any]:
    """The document as the real reader sees it -- proves the emitted text is valid TOML."""
    return tomllib.loads(doc.dumps())


# -- seeding and scalars ----------------------------------------------------


def test_seed_a_file_from_nothing():
    doc = TOMLDocument([])
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
    doc = TOMLDocument([])
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


def test_updating_a_multiline_array_collapses_it_and_spares_the_next_entry():
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
        'team = ["lead", "boss", "friend"]\n'
        'me = "you@naver.com"\n'
    )


def test_a_group_is_written_as_a_one_line_array():
    doc = TOMLDocument([])
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
    assert doc.has_in_array("accounts", field="email", value="you@gmail.com")
    assert not doc.has_in_array("accounts", field="email", value="nobody@x.com")


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


# -- the round-trip promise (council edge cases) ----------------------------


def test_a_dotted_key_is_quoted_and_round_trips():
    doc = TOMLDocument([])
    doc.set_table_key("contacts", "jane.doe", "jane@example.com")
    assert doc.dumps() == '[contacts]\n"jane.doe" = "jane@example.com"\n'
    assert _parsed(doc)["contacts"] == {"jane.doe": "jane@example.com"}
    doc.set_table_key("contacts", "jane.doe", "jane@newco.com")  # finds the quoted key
    assert _parsed(doc)["contacts"] == {"jane.doe": "jane@newco.com"}


def test_a_value_containing_brackets_does_not_corrupt_the_next_edit():
    doc = TOMLDocument([])
    doc.set_table_key("contacts", "foo", "a[b]c@x.com")  # brackets in the value
    doc.set_table_key("contacts", "lead", "lead@x.com")
    doc.set_table_key("contacts", "lead", "new@x.com")  # update -- must find lead, not dup
    parsed = _parsed(doc)["contacts"]
    assert parsed == {"foo": "a[b]c@x.com", "lead": "new@x.com"}


def test_a_value_containing_an_equals_sign_round_trips():
    doc = TOMLDocument([])
    doc.set_table_key("contacts", "foo", "a=b@x.com")
    doc.set_table_key("contacts", "foo", "c=d@x.com")  # update, not duplicate
    assert _parsed(doc)["contacts"] == {"foo": "c=d@x.com"}


def test_a_quoted_key_containing_an_equals_sign_round_trips():
    doc = TOMLDocument([])
    doc.set_table_key("contacts", "a=b", "x@y.com")
    doc.set_table_key("contacts", "a=b", "z@y.com")  # update, not duplicate
    assert _parsed(doc)["contacts"] == {"a=b": "z@y.com"}


def test_control_characters_are_escaped_and_round_trip():
    doc = TOMLDocument([])
    for name, char in [("esc", "\x1b"), ("vtab", "\x0b"), ("ff", "\x0c"), ("nul", "\x00")]:
        doc.set_table_key("contacts", name, f"a{char}b")
    parsed = _parsed(doc)["contacts"]  # must be valid TOML despite the control chars
    assert parsed == {"esc": "a\x1bb", "vtab": "a\x0bb", "ff": "a\x0cb", "nul": "a\x00b"}


def test_a_unicode_line_separator_is_not_split_on_reload():
    doc = TOMLDocument([])
    doc.set_table_key("contacts", "foo", "a b@x.com")  # U+2028 is legal in a value
    reloaded = TOMLDocument.loads(doc.dumps())  # must not split the line
    reloaded.set_table_key("contacts", "foo", "new@x.com")  # update, not duplicate
    assert _parsed(reloaded)["contacts"] == {"foo": "new@x.com"}


def test_a_value_ending_in_a_backslash_is_matched_by_its_field():
    doc = TOMLDocument([])
    doc.append_to_array("accounts", [("email", "x@y.com\\"), ("alias", "me")])
    # the escaped backslash must not fool the closing-quote scan
    assert doc.has_in_array("accounts", field="email", value="x@y.com\\")
    found = doc.update_in_array(
        "accounts", match_field="email", match_value="x@y.com\\",
        field="alias", value="work",
    )
    assert found
    assert doc.dumps().count("[[accounts]]") == 1  # updated in place, no duplicate block
    assert _parsed(doc)["accounts"][0] == {"email": "x@y.com\\", "alias": "work"}


# -- I/O --------------------------------------------------------------------


def test_crlf_input_is_normalized_to_lf():
    doc = TOMLDocument.loads('[contacts]\r\nlead = "lead@x.com"\r\n')
    doc.set_table_key("contacts", "boss", "boss@x.com")
    assert "\r" not in doc.dumps()
    assert _parsed(doc)["contacts"] == {"lead": "lead@x.com", "boss": "boss@x.com"}


def test_save_is_atomic_and_preserves_mode(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text('[contacts]\nme = "you@naver.com"\n', encoding="utf-8")
    path.chmod(0o600)
    doc = TOMLDocument.load(path)
    doc.set_table_key("contacts", "lead", "lead@example.com")
    doc.save(path)
    assert path.stat().st_mode & 0o777 == 0o600
    assert 'lead = "lead@example.com"' in path.read_text(encoding="utf-8")
    assert not (tmp_path / "config.toml.tmp").exists()


def test_load_missing_file_is_empty(tmp_path: Path):
    assert TOMLDocument.load(tmp_path / "nope.toml").dumps() == ""


def test_save_creates_owner_only_parent(tmp_path: Path):
    path = tmp_path / "fresh" / "config.toml"
    doc = TOMLDocument([])
    doc.set_table_key("contacts", "me", "you@naver.com")
    doc.save(path)
    assert path.exists()
    assert (tmp_path / "fresh").stat().st_mode & 0o777 == 0o700


def test_save_accepts_a_string_path(tmp_path: Path):
    path = tmp_path / "config.toml"
    doc = TOMLDocument([])
    doc.set_root_key("default_account", "me")
    doc.save(str(path))
    assert TOMLDocument.load(str(path)).dumps() == 'default_account = "me"\n'
