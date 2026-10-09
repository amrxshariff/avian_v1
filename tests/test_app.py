"""
tests/test_app.py — the retry handler's own responsibilities.

app.py is otherwise Streamlit wiring, exercised by hand rather than by a
test suite. These two behaviours don't belong to any other module, though:
they are about what the handler does with retry_unclassified's result and
its failures, not what retry_unclassified itself does (that's
tests/test_retry.py).

  * a retry threads the session's CURRENT key source into provenance, not
    whatever the original build recorded — D-63's other half: someone can
    fail on the project key, then paste their own, and the wording after a
    retry has to follow the key that just answered.
  * a retry that raises shows a redacted message and leaves the build alone.
    An SDK error can quote the request it failed on, and losing someone's
    network because a retry failed would be a second, worse failure.
"""

from __future__ import annotations

import app
from src.build import build_network
from src.dashboard.keys import KEY_PROJECT, KEY_USER
from src.dashboard.state import apply_corrections
from src.dashboard.unclassified import render_notice
from tests.test_build import AuthenticationError, _Client, _embed, _people, _project
from tests.test_unclassified import FakeStreamlit as _NoticeStreamlit


class _Spinner:
    def __enter__(self):
        return None

    def __exit__(self, *exc):
        return False


class FakeStreamlit:
    def __init__(self):
        self.reran = False
        self.errors: list[str] = []

    def spinner(self, _text):
        return _Spinner()

    def rerun(self):
        self.reran = True

    def error(self, text):
        self.errors.append(text)


class _Built:
    def __init__(self, provenance):
        self.provenance = provenance


def test_the_build_source_is_read_from_provenance():
    assert app._build_source(_Built({"source": KEY_USER})) == KEY_USER
    assert app._build_source(_Built({})) is None
    assert app._build_source(None) is None           # the demo


def test_the_notice_quotes_the_builds_source_not_the_sessions(monkeypatch, tmp_path):
    """D-63's regression guard. Build on the project key, have that key die,
    then paste a user key: the notice must still say the service was
    unavailable. Reading the session instead would tell this person their
    own key was rejected — a key that was never used."""
    built = build_network(
        people=_people(20),
        client=_Client(fail_at=1, error=AuthenticationError("bad key")),
        cache_path=tmp_path / "c.json", embed=_embed, project=_project,
        source=KEY_PROJECT,
    )
    # The user's key has now arrived, as far as anything reading the session
    # can tell.
    monkeypatch.setattr(app, "key_source", lambda store=None: KEY_USER)
    monkeypatch.setattr("src.dashboard.keys.key_source", lambda store=None: KEY_USER)

    st = _NoticeStreamlit()
    render_notice(apply_corrections(built.nodes, {}), st=st,
                  source=app._build_source(built))

    assert "unavailable" in st.text
    assert "your api key" not in st.text


def test_a_retry_passes_the_session_key_source_through_to_provenance(monkeypatch):
    seen: dict = {}

    def fake_retry(built, person_indices, source=None, cache_path=None, meters=None):
        seen["source"] = source
        seen["cache_path"] = cache_path
        return "updated-build"

    st = FakeStreamlit()
    monkeypatch.setattr(app, "st", st)
    monkeypatch.setattr(app, "key_source", lambda: KEY_USER)
    monkeypatch.setattr(app, "set_built", lambda result: seen.setdefault("built", result))
    monkeypatch.setattr("src.build.retry_unclassified", fake_retry)

    handler = app._retry_handler(built=object())
    handler([1, 2])

    assert seen["source"] == KEY_USER
    assert seen["built"] == "updated-build"
    assert st.reran is True
    assert st.errors == []


def test_a_retry_uses_the_session_classification_cache(monkeypatch):
    """D-71: the build's cache, not the shared file. Without it the retry
    falls back to its own default, and a title answered in this session is
    paid for again."""
    seen: dict = {}
    session_cache = {"title||": {"soc": "13"}}

    def fake_retry(built, person_indices, source=None, cache_path=None, meters=None):
        seen["cache_path"] = cache_path
        return "updated-build"

    monkeypatch.setattr(app, "st", FakeStreamlit())
    monkeypatch.setattr(app, "key_source", lambda: KEY_USER)
    monkeypatch.setattr(app, "set_built", lambda result: None)
    monkeypatch.setattr(app, "classification_cache", lambda: session_cache)
    monkeypatch.setattr("src.build.retry_unclassified", fake_retry)

    app._retry_handler(built=object())([1])

    assert seen["cache_path"] is session_cache


def test_a_failing_retry_shows_a_redacted_message_and_keeps_the_build(monkeypatch):
    def fake_retry(built, person_indices, source=None, cache_path=None, meters=None):
        raise RuntimeError("failed for key sk-ant-secret")

    st = FakeStreamlit()
    set_built_calls: list = []
    monkeypatch.setattr(app, "st", st)
    monkeypatch.setattr(app, "key_source", lambda: KEY_USER)
    monkeypatch.setattr(
        app, "redact", lambda text: text.replace("sk-ant-secret", "sk-ant-...redacted")
    )
    monkeypatch.setattr(app, "set_built", lambda result: set_built_calls.append(result))
    monkeypatch.setattr("src.build.retry_unclassified", fake_retry)

    handler = app._retry_handler(built="original-build")
    handler([1, 2])

    assert set_built_calls == []                 # the build is left intact
    assert st.reran is False                      # no rerun on failure
    assert st.errors == ["failed for key sk-ant-...redacted"]
