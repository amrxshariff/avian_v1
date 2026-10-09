"""
tests/test_retry_offer.py — P2.9b: the offer to classify after a key arrives.

A separate control from the notice's retry button: REASON_NO_KEY (and a dead
own-key) stay in _NOT_RETRYABLE on purpose, so this cannot be can_retry()
reacting to the reason. It fires on a key arriving, reuses retry_targets and
the caller's own on_retry, and quotes the cost from provenance rather than the
headcount, because the number shown is the number someone is about to be
charged for.

Run from the repo root:
    python -m pytest tests/test_retry_offer.py -v
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.dashboard.retry_offer import (
    OFFER_SLOT,
    clear_offer,
    offer_retry,
    offered,
    take_offer,
)
from src.dashboard.state import STATE_CLASSIFIED, STATE_NOT_CLASSIFIED
from src.dashboard.unclassified import REASON_COLUMN


class _FakeColumn:
    def __init__(self, click: bool):
        self.buttons: list[str] = []
        self._click = click

    def button(self, label: str, **kwargs) -> bool:
        self.buttons.append(label)
        return self._click


class FakeStreamlit:
    """Records what a render call would have drawn. No Streamlit runtime."""

    def __init__(self, accept: bool = False, decline: bool = False):
        self.infos: list[str] = []
        self._accept = accept
        self._decline = decline
        self.accept_col: _FakeColumn | None = None
        self.decline_col: _FakeColumn | None = None

    def info(self, text: str) -> None:
        self.infos.append(text)

    def columns(self, n: int):
        self.accept_col = _FakeColumn(self._accept)
        self.decline_col = _FakeColumn(self._decline)
        return self.accept_col, self.decline_col


class _Built:
    """Stands in for a BuildResult — only provenance matters here."""

    def __init__(self, provenance: dict | None = None):
        self.provenance = provenance or {}


def _df(states) -> pd.DataFrame:
    return pd.DataFrame({
        "person_index": list(range(len(states))),
        "name": [f"P{i}" for i in range(len(states))],
        "display_state": states,
        REASON_COLUMN: [""] * len(states),
    })


# --- the slot ------------------------------------------------------------


def test_offer_retry_sets_the_slot():
    store: dict = {}
    offer_retry(store)
    assert offered(store)
    assert store[OFFER_SLOT] is True


def test_clear_offer_is_idempotent():
    store: dict = {}
    clear_offer(store)          # nothing to clear — must not raise
    offer_retry(store)
    clear_offer(store)
    clear_offer(store)
    assert not offered(store)


# --- take_offer ------------------------------------------------------------


def test_take_offer_renders_nothing_when_no_offer_is_pending():
    st = FakeStreamlit()
    df = _df([STATE_NOT_CLASSIFIED])
    assert take_offer(df, _Built(), lambda targets: None, st=st, store={}) is False
    assert st.infos == []


def test_take_offer_clears_a_stale_offer_when_nobody_is_pending():
    """The build was replaced, or a retry already succeeded."""
    st = FakeStreamlit()
    df = _df([STATE_CLASSIFIED])
    store = {OFFER_SLOT: True}

    assert take_offer(df, _Built(), lambda targets: None, st=st, store=store) is False
    assert not offered(store)
    assert st.infos == []


def test_accepting_calls_on_retry_with_the_pending_indices_and_clears_the_slot():
    st = FakeStreamlit(accept=True)
    called: list[list[int]] = []
    df = _df([STATE_NOT_CLASSIFIED, STATE_CLASSIFIED, STATE_NOT_CLASSIFIED])
    store = {OFFER_SLOT: True}

    result = take_offer(df, _Built(), called.append, st=st, store=store)

    assert result is True
    assert called == [[0, 2]]
    assert not offered(store)
    assert st.accept_col.buttons == ["Classify them now"]


def test_declining_clears_the_slot_without_calling_on_retry():
    st = FakeStreamlit(decline=True)
    called: list[list[int]] = []
    df = _df([STATE_NOT_CLASSIFIED])
    store = {OFFER_SLOT: True}

    result = take_offer(df, _Built(), called.append, st=st, store=store)

    assert result is False
    assert called == []
    assert not offered(store)
    assert st.decline_col.buttons == ["Not now"]


def test_neither_button_leaves_the_offer_pending():
    """Nobody has answered yet — the prompt must still be there next run."""
    st = FakeStreamlit()
    called: list[list[int]] = []
    df = _df([STATE_NOT_CLASSIFIED])
    store = {OFFER_SLOT: True}

    result = take_offer(df, _Built(), called.append, st=st, store=store)

    assert result is False
    assert called == []
    assert offered(store)


# --- the cost clause ---------------------------------------------------------


def test_the_cost_clause_quotes_uncached_titles_not_the_headcount():
    st = FakeStreamlit()
    df = _df([STATE_NOT_CLASSIFIED] * 5)
    built = _Built({"uncached_titles": 2})
    store = {OFFER_SLOT: True}

    take_offer(df, built, lambda targets: None, st=st, store=store)

    assert "2" in st.infos[0]
    assert "5" not in st.infos[0].split("2", 1)[1].split("title")[0]


def test_the_cost_clause_says_nothing_when_provenance_lacks_the_figure():
    st = FakeStreamlit()
    df = _df([STATE_NOT_CLASSIFIED])
    built = _Built({})  # no "uncached_titles" — an older build
    store = {OFFER_SLOT: True}

    take_offer(df, built, lambda targets: None, st=st, store=store)

    assert st.infos[0] == "Your key is ready. 1 people are not classified yet."


def test_a_zero_cost_says_the_classification_is_free():
    st = FakeStreamlit()
    df = _df([STATE_NOT_CLASSIFIED] * 3)
    built = _Built({"uncached_titles": 0})
    store = {OFFER_SLOT: True}

    take_offer(df, built, lambda targets: None, st=st, store=store)

    assert "will not use your key" in st.infos[0]
