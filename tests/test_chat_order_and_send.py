"""
tests/test_chat_order_and_send.py — P2.10.3 and P2.10.4.

P2.10.3: the newest exchange is first. In a panel of fixed height the newest
answer is then in view without scrolling, which is the reason for the order.
P2.10.4: the question box wraps, and only Send submits. Enter is a new line and
leaving the box sends nothing, so a question is not lost as D-51's notes were.
"""

from __future__ import annotations

from types import SimpleNamespace

from streamlit.testing.v1 import AppTest

from src.dashboard.chat import INPUT_HEIGHT, SEND_LABEL, newest_first
from tests.test_assistant import ok_reply


def _turn(role, text):
    return {"role": role, "text": text}


# --- the order --------------------------------------------------------------------


def test_exchanges_are_reversed_and_each_keeps_its_own_order():
    history = [_turn("user", "q1"), _turn("assistant", "a1"),
               _turn("user", "q2"), _turn("assistant", "a2"),
               _turn("user", "q3"), _turn("assistant", "a3")]
    assert newest_first(history) == [
        [_turn("user", "q3"), _turn("assistant", "a3")],
        [_turn("user", "q2"), _turn("assistant", "a2")],
        [_turn("user", "q1"), _turn("assistant", "a1")],
    ]


def test_an_unanswered_question_is_its_own_exchange_and_nothing_is_lost():
    history = [_turn("user", "q1"), _turn("assistant", "a1"), _turn("user", "q2")]
    exchanges = newest_first(history)
    assert exchanges == [[_turn("user", "q2")],
                         [_turn("user", "q1"), _turn("assistant", "a1")]]
    assert sum(len(e) for e in exchanges) == len(history)
    assert newest_first([]) == []


# --- the panel ----------------------------------------------------------------------


class _Numbered:
    """Answers "answer 1", "answer 2", ... so the order on screen can be read."""

    def __init__(self):
        self.calls = 0
        self.messages = self

    def create(self, **kwargs):
        self.calls += 1
        block = SimpleNamespace(type="text", text=ok_reply(answer=f"answer {self.calls}"))
        return SimpleNamespace(content=[block], stop_reason="end_turn")


def _chat_app():
    import streamlit as st
    from src.dashboard.chat import render_chat_panel
    from tests.test_assistant import make_df

    render_chat_panel(make_df(), client=st.session_state["_fake"])


def _panel(monkeypatch, fake) -> AppTest:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)   # unmetered
    at = AppTest.from_function(_chat_app, default_timeout=30)
    at.session_state["_fake"] = fake
    return at.run()


def _send(at, question):
    at.text_area[0].input(question)
    next(b for b in at.button if b.label == SEND_LABEL).click()
    return at.run()


def _messages(at) -> list[tuple[str, str]]:
    return [(m.name, " ".join(md.value for md in m.markdown)) for m in at.chat_message]


def test_the_newest_exchange_is_first_and_stays_first_after_a_rerun(monkeypatch):
    at = _panel(monkeypatch, _Numbered())
    for q in ("first question", "second question", "third question"):
        at = _send(at, q)

    # One plain rerun first. On the answering run the spinner holds the
    # assistant message's first slot; AppTest keeps that run's elements
    # beside the rerun's, where a browser clears them when the run ends.
    shown = _messages(at.run())
    assert [role for role, _ in shown] == ["user", "assistant"] * 3
    assert shown[0][1] == "third question" and "answer 3" in shown[1][1]
    assert shown[4][1] == "first question" and "answer 1" in shown[5][1]
    assert _messages(at.run()) == shown


def test_typing_alone_sends_nothing_and_send_sends_once(monkeypatch):
    fake = _Numbered()
    at = _panel(monkeypatch, fake)

    at.text_area[0].input("who works in finance?").run()
    at.run()
    assert fake.calls == 0                        # Enter, blur or a rerun: nothing sent

    next(b for b in at.button if b.label == SEND_LABEL).click().run()
    assert fake.calls == 1


def _form(at):
    found = []

    def walk(node):
        kids = getattr(node, "children", None)
        if isinstance(kids, dict):
            for child in kids.values():
                proto = getattr(child, "proto", None)
                if proto is not None and hasattr(proto, "ListFields") and                         "form" in [f.name for f, _ in proto.ListFields()]:
                    found.append(proto.form)
                walk(child)

    walk(at._tree)
    assert len(found) == 1
    return found[0]


def test_the_form_asks_for_the_box_to_be_cleared_after_send(monkeypatch):
    """The browser empties the box. AppTest does not emulate clear_on_submit, so
    what can be pinned here is that the form asks for it. Whether the box
    actually empties is a browser verdict."""
    assert _form(_panel(monkeypatch, _Numbered())).clear_on_submit is True


def test_the_question_box_is_a_wrapping_area_with_a_send_button(monkeypatch):
    at = _panel(monkeypatch, _Numbered())
    assert len(at.text_input) == 0
    assert len(at.text_area) == 1 and at.text_area[0].proto.height == INPUT_HEIGHT
    assert [b.label for b in at.button if b.label == SEND_LABEL] == [SEND_LABEL]


# --- the spec's own checks (P2.10.3) ---------------------------------------------


def test_two_questions_read_q2_a2_q1_a1(monkeypatch):
    """Not A2, Q2, A1, Q1 (reversed by message, which still looks newest-first
    at a glance) and not Q1, A1, Q2, A2 (not reversed)."""
    at = _panel(monkeypatch, _Numbered())
    at = _send(_send(at, "first question"), "second question")
    shown = _messages(at.run())
    assert [role for role, _ in shown] == ["user", "assistant", "user", "assistant"]
    assert shown[0][1] == "second question" and "answer 2" in shown[1][1]
    assert shown[2][1] == "first question" and "answer 1" in shown[3][1]


def test_storage_stays_chronological_across_reruns(monkeypatch):
    """The renderer reverses a copy at paint time; nothing reverses in place."""
    from src.dashboard.chat import HISTORY_KEY

    at = _panel(monkeypatch, _Numbered())
    at = _send(_send(at, "first question"), "second question")
    for _ in range(2):
        at = at.run()
        users = [t["text"] for t in at.session_state[HISTORY_KEY] if t["role"] == "user"]
        assert users == ["first question", "second question"]


def _scrolling_app():
    import streamlit as st
    from src.dashboard.chat import render_chat_panel
    from tests.test_assistant import make_df

    render_chat_panel(make_df(), client=st.session_state["_fake"], history_height=300)


def test_the_box_then_the_controls_then_the_history_all_scroll_in_the_region(monkeypatch):
    """Verdict 8: with the box outside the region, an answer to a question asked
    while scrolled down landed out of view. Inside, at the top, typing means
    being at the top, so the new answer lands under the box."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    at = AppTest.from_function(_scrolling_app, default_timeout=30)
    at.session_state["_fake"] = _Numbered()
    at = _send(at.run(), "first question").run()

    order, inside = [], {}

    def walk(node, in_region):
        kids = getattr(node, "children", None)
        if isinstance(kids, dict):
            for child in kids.values():
                proto = getattr(child, "proto", None)
                region = in_region or (type(child).__name__ == "Block" and proto is not None
                                       and proto.HasField("vertical") and proto.vertical.height == 300)
                kind, label = getattr(child, "type", None), str(getattr(child, "label", ""))
                name = ("box" if kind == "text_area" else
                        "controls" if kind == "expander" and label.startswith("What is sent") else
                        "message" if kind == "chat_message" else None)
                if name and name not in inside:
                    order.append(name)
                    inside[name] = region
                walk(child, region)

    walk(at._tree, False)
    assert order == ["box", "controls", "message"]
    assert inside == {"box": True, "controls": True, "message": True}
