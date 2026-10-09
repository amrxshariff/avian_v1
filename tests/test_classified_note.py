"""
tests/test_classified_note.py — the upload note names whose key paid, truthfully (D-83).

"Classified with your key" was shown after every classified build, including
one the project's key paid for, to a visitor who had pasted nothing. The
provenance line said it correctly; the note was worded separately. Both now
take the answer from provenance.whose_key, over the build's recorded source.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.dashboard.keys import KEY_NONE, KEY_PROJECT, KEY_USER, remember_key
from src.dashboard.provenance import built_line
from src.dashboard.upload import CLASSIFIED_TAIL, classified_note, render_upload_panel
from tests.test_build import _Client
from tests.test_upload import FakeStreamlit, _Upload, _build, _csv


def _note(st) -> str:
    notes = [c for c in st.captions if CLASSIFIED_TAIL in c]
    assert len(notes) == 1
    return notes[0]


def test_a_build_on_the_project_key_does_not_say_your_key(monkeypatch):
    monkeypatch.setattr("src.dashboard.keys.key_source", lambda store=None: KEY_PROJECT)
    st = FakeStreamlit(upload=_Upload(_csv(10)))
    render_upload_panel(st=st, store={},
                        build_fn=lambda s, **k: _build(s, client=_Client(), **k))

    note = _note(st)
    assert "this demo's shared allowance" in note
    assert "your" not in note.split(".")[0].lower()


def test_a_build_on_a_pasted_key_says_so(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    store: dict = {}
    remember_key("sk-ant-visitor", store)
    st = FakeStreamlit(upload=_Upload(_csv(10)))
    render_upload_panel(st=st, store=store,
                        build_fn=lambda s, **k: _build(s, client=_Client(), **k))

    assert "your own API key" in _note(st)


@pytest.mark.parametrize("provenance", [
    {"source": KEY_PROJECT, "mixed_sources": True},
    {"source": None},
    {"source": "project_key"},          # build_network's default before D-63
])
def test_an_unknown_or_mixed_source_claims_no_key(provenance):
    note = classified_note(SimpleNamespace(provenance=provenance))
    assert note == f"Classified. {CLASSIFIED_TAIL}"


@pytest.mark.parametrize("source", [KEY_PROJECT, KEY_USER, None, KEY_NONE])
def test_the_note_and_the_provenance_line_name_the_same_key(source):
    """One answer to "whose key paid", read by both surfaces."""
    built = SimpleNamespace(provenance={"source": source, "model": "m"})
    note, line = classified_note(built), built_line(built)
    for phrase in ("your own API key", "this demo's shared allowance"):
        assert (phrase in note) == (phrase in line) or line == ""
