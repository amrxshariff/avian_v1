"""
src/dashboard/lifetime.py — how long a network lives, and asking in time.

A raw export is real people's names held in server memory. They go when the
tab closes, when the container recycles, and — this module — after an hour
with nobody here. Explicit, rather than "until something happens".

The clock itself (touch, remaining, LIFETIME) is session_build's, beside the
build it times. This is what happens as it runs down.

Two callers, because an idle tab does not rerun
-----------------------------------------------
app.py calls expire_if_stale() and touch() on every full rerun, which is
someone doing something. That alone would make "dropped after an hour" mean
"dropped whenever you come back", with the names in memory until then. So
app.py also runs watch_session() in a fragment on a timer. Fragment reruns do
not execute main(), so the watch checks the clock without touching it: it
drops an idle tab on time, and warns in the last twenty minutes someone who
is still there but has stopped clicking.

What this cannot do
-------------------
Reach a tab that has gone. A closed tab or a sleeping laptop stops the timer;
the session is then Streamlit's, cleaned up after
server.disconnectedSessionTTL.

Know that a download completed. on_click fires when the button is pressed,
before the browser saves anything, so a cancelled save dialog still counts.
That is why the prompt's wording asks someone to download and never claims
their work is unsaved: it stays true either way.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from src.dashboard.session import session_store
from src.dashboard.session_build import remaining

EXPIRED_KEY = "session_expired"
# What the last download held. Network work: forget_network_work drops it.
SAVED_KEY = "work_saved_snapshot"

# Five judgements is enough to represent real effort and early enough to ask
# before an hour of quiet can take it.
PROMPT_THRESHOLD = 5

# Bucketed so the line is stable across the watch's reruns rather than
# counting down a minute at a time.
WARN_BUCKETS = (20, 15, 10, 5)

PROMPT = "Download your work before the session ends."


# --- the drop ----------------------------------------------------------------


def expire_if_stale(
    store: Optional[dict] = None, now: Optional[datetime] = None
) -> bool:
    """Drop the whole session if its network has been idle for LIFETIME.
    True if dropped.

    The WHOLE session, not the build and its work. Chat history, summaries
    and the restore report name people from the export; the key is a secret
    held for someone who has walked away; and using_demo, left set, would
    send a visitor who explored the example before uploading silently into the
    demo instead of to the welcome screen that says what happened. Clearing
    only some of it makes "dropped" true of the network and false of the rest.
    """
    left = remaining(store, now)
    if left is None or left > timedelta(0):
        return False
    held = session_store(store)
    held.clear()
    held[EXPIRED_KEY] = True
    return True


def take_expired(store: Optional[dict] = None) -> bool:
    """True once after an expiry, so the note is shown once and not again."""
    return bool(session_store(store).pop(EXPIRED_KEY, False))


# --- the warning -------------------------------------------------------------


def minutes_warning(
    store: Optional[dict] = None, now: Optional[datetime] = None
) -> Optional[int]:
    """The bucket to warn at, or None when there is nothing to say yet."""
    left = remaining(store, now)
    if left is None or left <= timedelta(0):
        return None
    minutes = left.total_seconds() / 60
    warn = None
    for bucket in WARN_BUCKETS:
        if minutes <= bucket:
            warn = bucket
    return warn


def expiry_warning(bucket: int) -> str:
    return (
        f"This session ends in about {bucket} minutes without activity. Any "
        "click keeps it. Download your work to keep it either way."
    )


def watch_session(
    df,
    *,
    st=None,
    store: Optional[dict] = None,
    now: Optional[datetime] = None,
) -> bool:
    """The timer's body: drop an idle session, or warn before it goes.

    Returns True when it dropped, so the caller can rerun the whole app to the
    welcome screen. Never touches the clock — the timer is not activity. Its
    download button is, through record_download.
    """
    if st is None:
        import streamlit as st  # noqa: PLC0415 — lazy, as everywhere in dashboard/

    from src.dashboard.session_io import download_session_button

    if expire_if_stale(store, now):
        return True
    bucket = minutes_warning(store, now)
    if bucket is not None:
        st.warning(expiry_warning(bucket))
        download_session_button(st, df, key="download_expiring")
    return False


# --- the prompt --------------------------------------------------------------


def work_snapshot(corrections: dict, notes: dict, enrichment=None) -> dict:
    """The session's work, as a download would capture it."""
    return {
        "corrections": dict(corrections),
        "notes": dict(notes),
        "enrichment": enrichment,
    }


def unsaved_work(current: dict, saved: Optional[dict]) -> int:
    """How many judgements differ from what the last download captured.

    Compared against a snapshot, not a count taken at download time. A count
    reads zero after someone changes a correction they had already saved, or
    clears one and makes another, while the file no longer matches the screen.

    The self-enrichment result counts as one. It is not countable the way a
    correction is, but someone who has enriched their own profile has
    something to lose, and a threshold that ignored it would stay quiet for
    exactly that person.
    """
    saved = saved or {}
    n = (_differing(current["corrections"], saved.get("corrections", {}))
         + _differing(current["notes"], saved.get("notes", {})))
    if current.get("enrichment") is not saved.get("enrichment"):
        n += 1
    return n


def _differing(now: dict, then: dict) -> int:
    return sum(1 for k in set(now) | set(then) if now.get(k) != then.get(k))


def _current_work(held) -> dict:
    from src.dashboard.enrich import KEY_RESULT
    from src.dashboard.notes import NOTES_KEY
    from src.dashboard.state import CORRECTIONS_KEY

    return work_snapshot(held.get(CORRECTIONS_KEY) or {},
                         held.get(NOTES_KEY) or {},
                         held.get(KEY_RESULT))


def record_download(store: Optional[dict] = None) -> None:
    """on_click for every download button: this is what the file now holds.

    Every button, including the sidebar's — the prompt re-arms from whatever
    was downloaded last, wherever it was downloaded from. Also activity:
    someone saving their work is not idle, and the warning's own button is
    inside the watch's fragment, whose reruns never reach app.py's touch().
    """
    from src.dashboard.session_build import touch

    held = session_store(store)
    held[SAVED_KEY] = _current_work(held)
    touch(store)


def should_prompt(store: Optional[dict] = None) -> bool:
    """True once PROMPT_THRESHOLD judgements differ from the last download."""
    held = session_store(store)
    return unsaved_work(_current_work(held), held.get(SAVED_KEY)) >= PROMPT_THRESHOLD


def render_lifetime_notices(
    df,
    *,
    st=None,
    store: Optional[dict] = None,
) -> None:
    """The download prompt, in the main column.

    The countdown is not here: this runs on full reruns, which touch the
    clock first, so it would always read a full hour. watch_session shows it.
    """
    if st is None:
        import streamlit as st  # noqa: PLC0415 — lazy, as everywhere in dashboard/

    from src.dashboard.session_io import download_session_button

    if not should_prompt(store):
        return
    st.info(PROMPT)
    download_session_button(st, df, key="download_prompt")
