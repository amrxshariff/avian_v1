"""
tests/test_session_build.py — D-65: work done on one network never outlives it.

Corrections and notes are keyed by person_index, which is a row position. A
correction made to the demo's person 87 and still held when the visitor's own
network arrives is shown on THEIR person 87 as a judgement they gave. Every way
the network on screen can change — a new upload, "Use the demo instead", Start
over — must drop that work. A retry must not: it is the same network.

Run from the repo root:
    python -m pytest tests/test_session_build.py -v
"""

from __future__ import annotations

from src.build import build_network, retry_unclassified
from src.dashboard.chat import HIGHLIGHT_KEY, HISTORY_KEY
from src.dashboard.chat_allowance import SESSION_KEY as CHAT_ASKED_KEY
from src.dashboard.enrich import KEY_ABOUT, KEY_RESULT, KEY_TITLE
from src.dashboard.keys import KEY_CHECK_SLOT, USER_KEY_SLOT
from src.dashboard.lifetime import SAVED_KEY
from src.dashboard.notes import NOTES_KEY
from src.dashboard.people_list import PAGE_KEY, SELECTED_KEY, SKIPPED_KEY
from src.dashboard.retry_offer import OFFER_SLOT
from src.dashboard.session_build import (
    BUILT_KEY,
    clear_built,
    forget_network_work,
    get_built,
    set_built,
)
from src.dashboard.session_io import KEY_APPLIED, KEY_REPORT
from src.dashboard.state import CORRECTIONS_KEY
from src.dashboard.summaries import SUMMARIES_KEY
from src.dashboard.upload import render_upload_panel
from src.dashboard.welcome import start_over
from tests.test_build import _Client, _embed, _people, _project
from tests.test_upload import FakeStreamlit, _Upload, _csv

NETWORK_WORK = {
    CORRECTIONS_KEY: {87: "13"},
    NOTES_KEY: {87: "met at the Kings Cross meetup"},
    HISTORY_KEY: [("who works in finance?", "Priya Shah, ...")],
    HIGHLIGHT_KEY: {87},
    SUMMARIES_KEY: {"13:abc": "Mostly analysts."},
    SKIPPED_KEY: {4},
    SELECTED_KEY: 87,
    OFFER_SLOT: True,
    KEY_REPORT: object(),
    SAVED_KEY: {"corrections": {87: "13"}, "notes": {}, "enrichment": None},
    f"{PAGE_KEY}_review": 3,
    f"{PAGE_KEY}_all": 2,
}

VISITOR_STATE = {
    USER_KEY_SLOT: "sk-ant-test",
    KEY_CHECK_SLOT: "valid",
    CHAT_ASKED_KEY: 4,
    KEY_TITLE: "Data scientist",
    KEY_ABOUT: "I build things.",
    KEY_RESULT: object(),
    KEY_APPLIED: ("session.json", 812),
}


def _store(**extra) -> dict:
    return {**NETWORK_WORK, **VISITOR_STATE, **extra}


def _network(n=10):
    return build_network(people=_people(n), classify=False,
                         embed=_embed, project=_project)


# --- what goes and what stays ------------------------------------------------


def test_forgetting_drops_everything_keyed_to_the_network():
    store = _store()
    forget_network_work(store)
    for key in NETWORK_WORK:
        assert key not in store, key


def test_forgetting_keeps_what_belongs_to_the_visitor():
    """The allowance above all: resetting it here would make "upload again"
    a way round the free tier."""
    store = _store()
    forget_network_work(store)
    for key, value in VISITOR_STATE.items():
        assert store[key] is value, key


# --- every way the network on screen changes ---------------------------------


def test_a_new_upload_does_not_inherit_the_demos_corrections(monkeypatch):
    """The welcome screen's two options, taken in order: explore the demo and
    correct someone, then upload your own export."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    store = _store()
    del store[USER_KEY_SLOT]           # keyless, so the build makes no calls
    st = FakeStreamlit(upload=_Upload(_csv(20)))

    result = render_upload_panel(
        st=st, store=store,
        build_fn=lambda src, **kw: build_network(
            src, embed=_embed, project=_project, **kw),
    )

    assert get_built(store) is result
    assert CORRECTIONS_KEY not in store and NOTES_KEY not in store
    assert store[CHAT_ASKED_KEY] == 4


def test_going_back_to_the_demo_drops_the_uploads_work():
    store = _store(**{BUILT_KEY: _network()})
    st = FakeStreamlit(click=True)                 # "Use the demo instead"

    render_upload_panel(st=st, store=store)

    assert get_built(store) is None
    assert CORRECTIONS_KEY not in store and NOTES_KEY not in store


def test_start_over_drops_the_work_with_the_network():
    store = _store(**{BUILT_KEY: _network()})
    start_over(store)
    assert BUILT_KEY not in store
    assert CORRECTIONS_KEY not in store and NOTES_KEY not in store


def test_clearing_with_nothing_held_is_harmless():
    store: dict = {}
    clear_built(store)
    assert store == {}


# --- and the one that must not -----------------------------------------------


def test_a_retry_keeps_the_corrections(tmp_path):
    """Same network, more of it classified. The work stays."""
    cache = tmp_path / "c.json"
    before = build_network(
        people=_people(40, titles=[f"Role {i}" for i in range(40)]),
        client=_Client(fail_at=2), cache_path=cache,
        embed=_embed, project=_project,
    )
    store = _store(**{BUILT_KEY: before})

    set_built(retry_unclassified(before, client=_Client(), cache_path=cache),
              store)

    assert store[CORRECTIONS_KEY] == {87: "13"}
    assert store[NOTES_KEY] == {87: "met at the Kings Cross meetup"}
