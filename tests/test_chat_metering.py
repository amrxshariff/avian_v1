"""
tests/test_chat_metering.py — the chat allowance and the daily ledger, through
the panels (D-80).

chat_allowance.py was built and tested on its own and never called by the chat
panel, so the ten-question limit and its caption never reached a visitor. These
drive the panels themselves: a question through the chat panel, a summary
through the summaries panel, a comparison through the enrichment panel, a build
through the upload panel.

One ledger, three sources; one question count, one source (design record,
7 October amendment). The ledger is redirected per test by conftest.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from streamlit.testing.v1 import AppTest

import src.spend as spend
from src.dashboard.chat import SEND_LABEL
from src.dashboard.chat_allowance import SESSION_KEY as ASKED
from src.dashboard.keys import KEY_PROJECT, USER_KEY_SLOT
from src.dashboard.metering import BUDGET_SPENT_NOTE
from src.dashboard.state import apply_corrections
from src.dashboard.unclassified import BUDGET_KEY_POINTER, render_notice
from src.dashboard.upload import render_upload_panel
from tests.test_assistant import ok_reply
from tests.test_build import _Client
from tests.test_upload import FakeStreamlit, _Upload, _build, _csv


class _Reply:
    """A chat or summary reply with usage, so the ledger has a cost to record."""

    def __init__(self, text: str, fail: bool = False):
        self.text, self.fail, self.calls = text, fail, 0
        self.messages = self

    def create(self, **kwargs):
        self.calls += 1
        if self.fail:
            raise RuntimeError("stub: the call failed")
        block = SimpleNamespace(type="text", text=self.text)
        return SimpleNamespace(content=[block], stop_reason="end_turn",
                               usage=SimpleNamespace(input_tokens=9000, output_tokens=300))


def _ledger_spent() -> float:
    if not spend.LEDGER_PATH.exists():
        return 0.0
    return json.loads(spend.LEDGER_PATH.read_text(encoding="utf-8"))["spent"]


def _spend_the_day() -> None:
    spend.LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    spend.LEDGER_PATH.write_text(json.dumps(
        {"date": spend._today(), "spent": 30.0, "calls": 0, "networks": 0}),
        encoding="utf-8")


def _project_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-project-test")


# --- the chat panel -------------------------------------------------------------


def _chat_app():
    import streamlit as st
    from src.dashboard.chat import render_chat_panel
    from tests.test_assistant import make_df

    render_chat_panel(make_df(), client=st.session_state["_fake"])


def _chat(fake, **state) -> AppTest:
    at = AppTest.from_function(_chat_app, default_timeout=30)
    at.session_state["_fake"] = fake
    for key, value in state.items():
        at.session_state[key] = value
    return at.run()


def _send(at, question: str) -> AppTest:
    """Type a question and press Send: the chat's only submit path (P2.10.4)."""
    at.text_area[0].input(question)
    next(b for b in at.button if b.label == SEND_LABEL).click()
    return at.run()


def _captions(at) -> str:
    return " | ".join(c.value for c in at.caption)


def test_a_question_through_the_chat_panel_uses_one_question(monkeypatch):
    _project_key(monkeypatch)
    fake = _Reply(ok_reply())
    at = _chat(fake)
    assert "10 free questions left" in _captions(at)

    _send(at, "who works in finance?")

    assert not at.exception
    assert fake.calls == 1
    assert at.session_state[ASKED] == 1
    assert "9 free questions left" in _captions(at)


def test_the_eleventh_question_is_refused_and_points_at_the_key_field(monkeypatch):
    _project_key(monkeypatch)
    fake = _Reply(ok_reply())

    at = _chat(fake, **{ASKED: 10})

    assert fake.calls == 0                       # nothing can be sent
    assert len(at.text_area) == 0                # the box is gone; the chat stops
    assert "add your own key" in _captions(at).lower()


def test_a_question_that_got_no_answer_does_not_use_one_up(monkeypatch):
    _project_key(monkeypatch)
    at = _chat(_Reply("", fail=True))

    _send(at, "who works in finance?")

    asked = at.session_state[ASKED] if ASKED in at.session_state else 0
    assert asked == 0


def test_a_question_on_the_project_key_is_charged_to_the_daily_ledger(monkeypatch):
    _project_key(monkeypatch)
    at = _chat(_Reply(ok_reply()))

    _send(at, "who works in finance?")

    assert _ledger_spent() > 0


def test_the_visitors_own_key_is_neither_counted_nor_charged(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    fake = _Reply(ok_reply())
    at = _chat(fake, **{USER_KEY_SLOT: "sk-ant-visitor"})

    _send(at, "who works in finance?")

    assert fake.calls == 1
    assert ASKED not in at.session_state
    assert "free question" not in _captions(at)
    assert not spend.LEDGER_PATH.exists()


# --- summaries: spend, but never a question ----------------------------------


def _summaries_app():
    import streamlit as st
    from src.dashboard.loader import DEMO_NODES_CSV, load_display_table
    from src.dashboard.summaries import render_summaries_panel

    df = load_display_table(path=DEMO_NODES_CSV)
    render_summaries_panel(df, ["13"], client=st.session_state["_fake"])


def test_a_summary_is_charged_to_the_ledger_and_uses_up_no_questions(monkeypatch):
    """The distinction most likely to blur: a summary spends, but the visitor
    did not ask for it, so it is not one of their ten questions."""
    _project_key(monkeypatch)
    fake = _Reply("These people work across finance and accounting roles.")
    at = AppTest.from_function(_summaries_app, default_timeout=30)
    at.session_state["_fake"] = fake
    at.run()

    assert not at.exception
    assert fake.calls == 1
    assert _ledger_spent() > 0
    assert ASKED not in at.session_state


# --- enrichment ----------------------------------------------------------------


def test_a_reading_is_charged_to_the_ledger(monkeypatch):
    import src.dashboard.enrich as enrich
    from tests.test_enrich import _FakeSt

    _project_key(monkeypatch)
    fake = _Reply("{}")
    monkeypatch.setattr("src.claude_classifier._default_client", lambda: fake)

    def classify_from_about(title, about, client=None):
        client.messages.create(model="m", max_tokens=1, messages=[])
        return "a reading"

    monkeypatch.setattr(enrich, "classify_from_about", classify_from_about)
    enrich._run_reading(_FakeSt({}), "Analyst", "About text " * 10)

    assert fake.calls == 1
    assert _ledger_spent() > 0


def test_a_reading_on_a_spent_day_is_refused_with_the_budget_note(monkeypatch):
    import src.dashboard.enrich as enrich
    from tests.test_enrich import _FakeSt

    _project_key(monkeypatch)
    _spend_the_day()
    fake = _Reply("{}")
    monkeypatch.setattr("src.claude_classifier._default_client", lambda: fake)

    def classify_from_about(title, about, client=None):
        client.messages.create(model="m", max_tokens=1, messages=[])
        return "a reading"

    monkeypatch.setattr(enrich, "classify_from_about", classify_from_about)
    st = _FakeSt({})
    enrich._run_reading(st, "Analyst", "About text " * 10)

    assert fake.calls == 0
    assert BUDGET_SPENT_NOTE in st.warnings


# --- design item 6: the day runs out mid-session ---------------------------------


def test_when_the_day_runs_out_chat_and_a_build_both_refuse_and_point_at_the_key_field(
    monkeypatch,
):
    """Three subsystems reading one exhausted ledger: the chat stops with the
    budget note, and a build lands in the fourth state with a notice that names
    the visitor's own key. Neither sends anything."""
    _project_key(monkeypatch)
    _spend_the_day()

    chat_fake = _Reply(ok_reply())
    at = _chat(chat_fake)
    assert chat_fake.calls == 0
    assert len(at.text_area) == 0
    assert BUDGET_SPENT_NOTE in _captions(at)

    monkeypatch.setattr("src.dashboard.keys.key_source", lambda store=None: KEY_PROJECT)
    build_client = _Client()
    result = render_upload_panel(
        st=FakeStreamlit(upload=_Upload(_csv(10))), store={},
        build_fn=lambda s, **k: _build(s, client=build_client, **k),
    )
    assert build_client.calls == []

    notice = FakeStreamlit()
    render_notice(apply_corrections(result.nodes, {}), st=notice, source=KEY_PROJECT)
    assert BUDGET_KEY_POINTER in " ".join(notice.captions)
