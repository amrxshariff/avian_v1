"""tests/test_notes_save.py - the notes field saves on an explicit button (D-51).

Runs render_notes() headlessly through Streamlit's AppTest: no browser, no
API key. Before D-51 a note was kept only after Ctrl+Enter or leaving the box,
with no visible save control.
"""
from __future__ import annotations

from streamlit.testing.v1 import AppTest


def _app():
    from src.dashboard.notes import render_notes

    render_notes(7)


def _run():
    return AppTest.from_function(_app, default_timeout=30).run()


def _save_button(at):
    return next(b for b in at.button if b.label == "Save note")


def test_the_field_has_a_visible_save_button():
    at = _run()
    assert not at.exception
    assert [b.label for b in at.button] == ["Save note"]


def test_typing_alone_does_not_save():
    at = _run()
    at.text_area[0].input("met at the Leeds conference").run()
    assert at.session_state["notes"] == {}


def test_save_keeps_the_note_and_confirms_it():
    at = _run()
    at.text_area[0].input("  met at the Leeds conference  ")
    _save_button(at).click().run()
    assert not at.exception
    assert at.session_state["notes"] == {7: "met at the Leeds conference"}
    assert any("Saved for this session." in c.value for c in at.caption)


def test_saving_an_empty_box_removes_the_note():
    at = _run()
    at.text_area[0].input("temporary")
    _save_button(at).click().run()
    at.text_area[0].input("")
    _save_button(at).click().run()
    assert at.session_state["notes"] == {}
