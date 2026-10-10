"""
tests/test_session_lifetime.py — P2.9b: how long a network lives, what goes
when it expires, and the prompt that protects work before it does.

The rules under test:

  * a network is dropped after an hour with nothing happening, and the WHOLE
    session goes with it — chat, summaries and the key name people or are
    secrets, and "dropped" has to be true of all of it;
  * the welcome screen says so once, including for a visitor who explored the
    example before uploading;
  * the countdown is shown by the timer's watch, in buckets, in the last
    twenty minutes; the watch never touches the clock;
  * the prompt counts what differs from the last download, from any button.

Run from the repo root:
    python -m pytest tests/test_session_lifetime.py -v
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from src.dashboard.chat import HISTORY_KEY
from src.dashboard.enrich import KEY_RESULT
from src.dashboard.keys import USER_KEY_SLOT
from src.dashboard.lifetime import (
    EXPIRED_KEY,
    PROMPT,
    PROMPT_THRESHOLD,
    SAVED_KEY,
    expire_if_stale,
    minutes_warning,
    record_download,
    render_lifetime_notices,
    should_prompt,
    take_expired,
    unsaved_work,
    watch_session,
    work_snapshot,
)
from src.dashboard.notes import NOTES_KEY
from src.dashboard.session_build import (
    BUILT_KEY,
    LIFETIME,
    TOUCHED_KEY,
    clear_built,
    remaining,
    set_built,
    touch,
)
from src.dashboard.state import CORRECTIONS_KEY
from src.dashboard.welcome import (
    DEMO_KEY,
    EXPIRED_NOTE,
    PRIVACY,
    render_welcome,
    should_welcome,
)
from tests.test_welcome import WelcomeStreamlit

T0 = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
NETWORK = object()          # the clock never looks inside the build


def _held(at=T0, **extra) -> dict:
    store: dict = {}
    set_built(NETWORK, store, now=at)
    store.update(extra)
    return store


def _idle(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


# --- the clock ---------------------------------------------------------------


def test_remaining_is_none_with_no_build():
    assert remaining({}, now=T0) is None
    assert remaining({DEMO_KEY: True}, now=T0) is None


def test_remaining_is_the_full_lifetime_immediately_after_a_build():
    assert LIFETIME == timedelta(hours=1)
    assert remaining(_held(), now=T0) == LIFETIME


def test_touch_refreshes_the_clock():
    store = _held()
    touch(store, now=_idle(50))
    assert remaining(store, now=_idle(50)) == LIFETIME


def test_touch_does_nothing_with_no_build():
    store: dict = {DEMO_KEY: True}
    touch(store, now=T0)
    assert TOUCHED_KEY not in store


def test_leaving_the_network_stops_its_clock():
    store = _held()
    clear_built(store)
    assert TOUCHED_KEY not in store and remaining(store, now=T0) is None


# --- the drop ----------------------------------------------------------------


def test_expire_if_stale_drops_the_whole_session():
    store = _held(**{
        CORRECTIONS_KEY: {87: "13"},
        NOTES_KEY: {87: "met at the Kings Cross meetup"},
        SAVED_KEY: work_snapshot({}, {}),
        HISTORY_KEY: [("who works in finance?", "Priya Shah, ...")],
        USER_KEY_SLOT: "sk-ant-test",
        "some_widget_key": "anything",
    })
    assert expire_if_stale(store, now=_idle(60))
    assert store == {EXPIRED_KEY: True}


def test_expire_if_stale_leaves_a_live_session_alone():
    store = _held(**{CORRECTIONS_KEY: {87: "13"}})
    assert not expire_if_stale(store, now=_idle(59))
    assert store[BUILT_KEY] is NETWORK and store[CORRECTIONS_KEY] == {87: "13"}


def test_the_demo_never_expires():
    store: dict = {DEMO_KEY: True, CORRECTIONS_KEY: {3: "13"}}
    assert not expire_if_stale(store, now=T0 + timedelta(days=2))
    assert store == {DEMO_KEY: True, CORRECTIONS_KEY: {3: "13"}}


def test_an_expired_session_sets_expired_key():
    store = _held()
    expire_if_stale(store, now=_idle(61))
    assert store[EXPIRED_KEY] is True


def test_explored_the_example_then_uploaded_still_lands_on_the_welcome():
    """using_demo survives an upload. Left set after expiry, it would skip the
    welcome screen and the note, and drop the visitor into the demo."""
    store = _held(**{DEMO_KEY: True})
    expire_if_stale(store, now=_idle(61))
    assert should_welcome(None, store)


# --- the welcome note --------------------------------------------------------


class _Welcome(WelcomeStreamlit):
    def __init__(self):
        super().__init__()
        self.warnings_shown: list[str] = []

    def warning(self, text, **kw):
        self.warnings_shown.append(text)


def test_the_welcome_screen_shows_the_expired_note_once_and_clears_it():
    store = {EXPIRED_KEY: True}
    st = _Welcome()
    render_welcome(st=st, store=store)
    assert st.warnings_shown == [EXPIRED_NOTE]
    assert EXPIRED_KEY not in store

    again = _Welcome()
    render_welcome(st=again, store=store)
    assert again.warnings_shown == []


def test_the_note_names_what_went_and_does_not_assume_a_download():
    text = EXPIRED_NOTE.lower()
    for thing in ("corrections", "notes", "api key", "if you downloaded"):
        assert thing in text


def test_the_privacy_statement_states_the_hour():
    assert "dropped after an hour of inactivity" in PRIVACY


def test_take_expired_is_true_once():
    store = {EXPIRED_KEY: True}
    assert take_expired(store) and not take_expired(store)


# --- the countdown -----------------------------------------------------------


def test_minutes_warning_is_none_above_20_minutes():
    assert minutes_warning(_held(), now=_idle(39)) is None


def test_minutes_warning_buckets():
    for left, bucket in ((19, 20), (14, 15), (9, 10), (4, 5)):
        assert minutes_warning(_held(), now=_idle(60 - left)) == bucket, left


def test_minutes_warning_is_none_once_expired_or_without_a_build():
    assert minutes_warning(_held(), now=_idle(60)) is None
    assert minutes_warning({DEMO_KEY: True}, now=T0) is None


class _FakeStreamlit:
    """Records what a render would have drawn. Holds no session state of its
    own: every read in lifetime goes through the injected store."""

    def __init__(self, store: dict | None = None):
        self.session_state = store if store is not None else {}
        self.warnings: list[str] = []
        self.infos: list[str] = []
        self.downloads: list[dict] = []

    def warning(self, text, **kw):
        self.warnings.append(text)

    def info(self, text, **kw):
        self.infos.append(text)

    def download_button(self, label, **kw):
        self.downloads.append(kw)
        return False


def _df(n=10) -> pd.DataFrame:
    return pd.DataFrame({
        "person_index": range(n),
        "name": [f"Person {i}" for i in range(n)],
        "role": [f"Role {i}" for i in range(n)],
    })


def test_the_watch_warns_with_a_download_in_the_window():
    store = _held()
    st = _FakeStreamlit(store)
    assert not watch_session(_df(), st=st, store=store, now=_idle(41))
    assert len(st.warnings) == 1 and "about 20 minutes" in st.warnings[0]
    assert st.downloads[0]["on_click"] is record_download


def test_the_watch_never_touches_the_clock():
    """A timer rerun is not activity. If it were, nobody would ever expire."""
    store = _held()
    watch_session(_df(), st=_FakeStreamlit(store), store=store, now=_idle(41))
    assert store[TOUCHED_KEY] == T0


def test_the_watch_drops_an_idle_tab():
    store = _held()
    st = _FakeStreamlit(store)
    assert watch_session(_df(), st=st, store=store, now=_idle(60))
    assert store == {EXPIRED_KEY: True}
    assert st.warnings == []


def test_the_watch_is_silent_early_on():
    store = _held()
    st = _FakeStreamlit(store)
    assert not watch_session(_df(), st=st, store=store, now=_idle(10))
    assert st.warnings == [] and st.downloads == []


# --- the prompt --------------------------------------------------------------


def _work(n: int) -> dict:
    return {i: "13" for i in range(n)}


def test_unsaved_work_counts_the_enrichment_result():
    assert unsaved_work(work_snapshot({}, {}, enrichment=object()), None) == 1


def test_a_download_captures_the_work():
    now = work_snapshot({1: "13"}, {1: "a note"}, enrichment=None)
    assert unsaved_work(now, work_snapshot({1: "13"}, {1: "a note"})) == 0


def test_changing_a_saved_correction_is_unsaved_work():
    """What a count taken at download time would miss: same number of
    corrections, different content."""
    saved = work_snapshot({1: "13", 2: "15"}, {})
    assert unsaved_work(work_snapshot({1: "13", 2: "29"}, {}), saved) == 1


def test_clearing_one_and_making_another_is_two_changes_not_zero():
    saved = work_snapshot({1: "13"}, {})
    assert unsaved_work(work_snapshot({2: "15"}, {}), saved) == 2


def test_should_prompt_fires_at_the_threshold_and_not_below():
    assert not should_prompt(_held(**{CORRECTIONS_KEY: _work(PROMPT_THRESHOLD - 1)}))
    assert should_prompt(_held(**{CORRECTIONS_KEY: _work(PROMPT_THRESHOLD)}))


def test_the_prompt_renders_a_line_and_a_download():
    store = _held(**{CORRECTIONS_KEY: _work(PROMPT_THRESHOLD)})
    st = _FakeStreamlit(store)
    render_lifetime_notices(_df(), st=st, store=store)
    assert st.infos == [PROMPT]
    assert st.downloads[0]["on_click"] is record_download
    assert st.warnings == []           # the countdown is the watch's, not this


def test_the_prompt_asks_and_never_claims_the_work_is_unsaved():
    assert "unsaved" not in PROMPT.lower()
    assert PROMPT.lower().startswith("download")


def test_a_download_re_arms_the_prompt_at_the_new_count():
    store = _held(**{CORRECTIONS_KEY: _work(PROMPT_THRESHOLD)})
    record_download(store)
    assert not should_prompt(store)

    store[CORRECTIONS_KEY].update({i: "13" for i in range(100, 100 + PROMPT_THRESHOLD - 1)})
    assert not should_prompt(store)
    store[CORRECTIONS_KEY][999] = "13"
    assert should_prompt(store)


def test_a_download_from_any_button_counts_and_is_activity():
    """The sidebar's button, the prompt's and the warning's all call
    record_download. The prompt is not only watching its own."""
    store = _held(**{CORRECTIONS_KEY: _work(PROMPT_THRESHOLD)})
    record_download(store)          # as if from the sidebar
    assert SAVED_KEY in store
    assert not should_prompt(store)

    later = _held(**{CORRECTIONS_KEY: {}})
    record_download(later)
    assert later[TOUCHED_KEY] != T0     # saving is not idle


def test_the_saved_snapshot_goes_with_the_network():
    store = _held(**{SAVED_KEY: work_snapshot({1: "13"}, {})})
    clear_built(store)
    assert SAVED_KEY not in store
