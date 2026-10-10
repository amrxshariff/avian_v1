"""tests/test_enrich.py - the self-enrichment panel's error path (D-46).

_run_reading takes `st` as an argument, so it runs here against a stand-in
with no Streamlit runtime, no key and no network.
"""
from __future__ import annotations

import contextlib

import pytest

from src.claude_classifier import ClassificationFailed
from src.dashboard import enrich


class _FakeSt:
    def __init__(self, state: dict):
        self.session_state = state
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def spinner(self, _text):
        return contextlib.nullcontext()

    def error(self, message):
        self.errors.append(message)

    def warning(self, message):
        self.warnings.append(message)


def _raising(exc):
    def classify_from_about(title, about, client=None):
        raise exc
    return classify_from_about


def test_failed_call_shows_plain_message_and_clears_the_old_result(monkeypatch):
    """D-46: the previous reading used to stay on screen under the error."""
    st = _FakeSt({enrich.KEY_RESULT: "previous reading"})
    monkeypatch.setattr(enrich, "classify_from_about", _raising(ClassificationFailed("cut off")))
    enrich._run_reading(st, "Auditor", "text")
    assert enrich.KEY_RESULT not in st.session_state
    assert len(st.errors) == 1 and "incomplete answer" in st.errors[0]


def test_missing_key_still_reports_its_own_message(monkeypatch):
    """ClassificationFailed subclasses RuntimeError, so its branch must come
    first without swallowing the missing-key case."""
    st = _FakeSt({})
    monkeypatch.setattr(enrich, "classify_from_about", _raising(RuntimeError("stub: missing key")))
    enrich._run_reading(st, "Auditor", "text")
    assert st.errors == ["stub: missing key"]


def test_success_replaces_the_previous_result(monkeypatch):
    st = _FakeSt({enrich.KEY_RESULT: "previous reading"})
    monkeypatch.setattr(enrich, "classify_from_about", lambda title, about, client=None: "new reading")
    enrich._run_reading(st, "Auditor", "text")
    assert st.session_state[enrich.KEY_RESULT] == "new reading"
    assert st.errors == []
