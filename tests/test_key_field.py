"""
tests/test_key_field.py — the session key field: paste, validate once, hold,
forget.

Runs render_key_field() headlessly through Streamlit's AppTest: no browser, no
real API call. validate_key is monkeypatched so the outcome is chosen by the
test, not the network — the same reason check_key's own tests do it in
tests/test_keys.py.
"""

from __future__ import annotations

from streamlit.testing.v1 import AppTest

from src.dashboard.key_field import FIELD_SLOT, NOTICE_SLOT, _paste_handler
from src.dashboard.keys import (
    KEY_MESSAGES,
    KEY_REJECTED,
    KEY_SERVICE_BUSY,
    KEY_VALID,
    USER_KEY_SLOT,
)
from src.dashboard.retry_offer import OFFER_SLOT
from src.dashboard.session_build import BUILT_KEY


def _app():
    import streamlit as st
    from src.dashboard.key_field import render_key_field

    def _mark():
        st.session_state["validated_fired"] = True

    render_key_field(on_validated=_mark)


def _run():
    return AppTest.from_function(_app, default_timeout=30).run()


def _fake_validate(outcome):
    """A stand-in for validate_key that records what it was asked to check."""
    calls: list[str] = []

    def validate(key, client=None):
        calls.append(key)
        return outcome

    return validate, calls


def test_a_valid_paste_stores_the_key_and_clears_the_field(monkeypatch):
    validate, _ = _fake_validate(KEY_VALID)
    monkeypatch.setattr("src.dashboard.keys.validate_key", validate)
    at = _run()

    at.text_input[0].input("sk-ant-good").run()

    assert not at.exception
    assert at.session_state[USER_KEY_SLOT] == "sk-ant-good"
    assert at.session_state[FIELD_SLOT] == ""


def test_a_valid_paste_fires_on_validated(monkeypatch):
    validate, _ = _fake_validate(KEY_VALID)
    monkeypatch.setattr("src.dashboard.keys.validate_key", validate)
    at = _run()

    at.text_input[0].input("sk-ant-good").run()

    assert at.session_state["validated_fired"] is True


def test_a_rejected_key_is_not_stored_and_leaves_the_field_alone(monkeypatch):
    validate, _ = _fake_validate(KEY_REJECTED)
    monkeypatch.setattr("src.dashboard.keys.validate_key", validate)
    at = _run()

    at.text_input[0].input("sk-ant-bad").run()

    assert USER_KEY_SLOT not in at.session_state
    assert at.text_input[0].value == "sk-ant-bad"


def test_a_rejected_key_shows_its_own_message_not_the_busy_one(monkeypatch):
    validate, _ = _fake_validate(KEY_REJECTED)
    monkeypatch.setattr("src.dashboard.keys.validate_key", validate)
    at = _run()

    at.text_input[0].input("sk-ant-bad").run()

    warnings = [w.value for w in at.warning]
    assert KEY_MESSAGES[KEY_REJECTED] in warnings
    assert KEY_MESSAGES[KEY_SERVICE_BUSY] not in warnings


def test_a_busy_service_shows_the_try_again_message(monkeypatch):
    validate, _ = _fake_validate(KEY_SERVICE_BUSY)
    monkeypatch.setattr("src.dashboard.keys.validate_key", validate)
    at = _run()

    at.text_input[0].input("sk-ant-busy").run()

    assert any(w.value == KEY_MESSAGES[KEY_SERVICE_BUSY] for w in at.warning)


def test_clearing_the_field_forgets_the_key(monkeypatch):
    """A rejected paste leaves a notice; clearing the box drops it, so a
    stale verdict never survives an edit."""
    validate, _ = _fake_validate(KEY_REJECTED)
    monkeypatch.setattr("src.dashboard.keys.validate_key", validate)
    at = _run()
    at.text_input[0].input("sk-ant-bad").run()
    assert at.warning  # the rejected notice is showing

    at.text_input[0].input("").run()

    assert not at.warning
    assert USER_KEY_SLOT not in at.session_state
    assert NOTICE_SLOT not in at.session_state


def test_forget_my_key_clears_the_key_the_field_and_the_notice(monkeypatch):
    validate, _ = _fake_validate(KEY_VALID)
    monkeypatch.setattr("src.dashboard.keys.validate_key", validate)
    at = _run()
    at.text_input[0].input("sk-ant-good").run()
    assert at.session_state[USER_KEY_SLOT] == "sk-ant-good"

    at.button[0].click().run()

    assert USER_KEY_SLOT not in at.session_state
    assert at.session_state[FIELD_SLOT] == ""
    assert NOTICE_SLOT not in at.session_state


def test_the_field_is_not_drawn_while_a_key_is_held(monkeypatch):
    validate, _ = _fake_validate(KEY_VALID)
    monkeypatch.setattr("src.dashboard.keys.validate_key", validate)
    at = _run()

    at.text_input[0].input("sk-ant-good").run()

    assert len(at.text_input) == 0
    assert [b.label for b in at.button] == ["Forget my key"]


def test_the_same_key_pasted_twice_validates_once(monkeypatch):
    """check_key's own memo, exercised through the handler rather than
    through AppTest — a widget only fires on_change on an actual value
    change, so the memo is unreachable at the widget layer: the second
    identical paste would never even reach check_key to prove anything.

    Call the handler closure directly instead. This is deliberate, not a
    shortcut: check_key has three more callers coming (slice 3, and the API
    eventually), none of them behind a widget, so this is the only path that
    will still be exercising the thing that matters once those exist. Do not
    "fix" this back through AppTest — that would test Streamlit's widget
    diffing instead of check_key's memo, and pass for the wrong reason."""
    validate, calls = _fake_validate(KEY_REJECTED)
    monkeypatch.setattr("src.dashboard.keys.validate_key", validate)

    store = {FIELD_SLOT: "sk-ant-same"}
    handler = _paste_handler(store, None)
    handler()
    handler()

    assert calls == ["sk-ant-same"]


# --- the retry offer, for a key that arrives after a build ------------------


def test_a_valid_paste_over_a_built_network_offers_a_retry(monkeypatch):
    """REASON_NO_KEY isn't retryable on its own; this is what makes a key
    arriving mid-session offer one anyway."""
    validate, _ = _fake_validate(KEY_VALID)
    monkeypatch.setattr("src.dashboard.keys.validate_key", validate)

    store = {FIELD_SLOT: "sk-ant-good", BUILT_KEY: object()}
    handler = _paste_handler(store, None)
    handler()

    assert store[OFFER_SLOT] is True


def test_a_valid_paste_with_no_build_does_not_offer_a_retry(monkeypatch):
    """Nothing to retry yet — the demo network has no client behind it."""
    validate, _ = _fake_validate(KEY_VALID)
    monkeypatch.setattr("src.dashboard.keys.validate_key", validate)

    store = {FIELD_SLOT: "sk-ant-good"}
    handler = _paste_handler(store, None)
    handler()

    assert OFFER_SLOT not in store


def test_a_rejected_paste_over_a_built_network_does_not_offer_a_retry(monkeypatch):
    """Nothing to retry with — the key that arrived does not work."""
    validate, _ = _fake_validate(KEY_REJECTED)
    monkeypatch.setattr("src.dashboard.keys.validate_key", validate)

    store = {FIELD_SLOT: "sk-ant-bad", BUILT_KEY: object()}
    handler = _paste_handler(store, None)
    handler()

    assert OFFER_SLOT not in store
