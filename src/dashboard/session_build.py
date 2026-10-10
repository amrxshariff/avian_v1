"""
src/dashboard/session_build.py — where a built network lives between reruns.

Streamlit re-executes the whole script on every interaction, so a BuildResult
has to be held somewhere across those runs. This is that somewhere, and it is a
module rather than three lines in app.py for two reasons: the session-lifetime
item (P2.9b) attaches its expiry here, and a test can drive it with a plain
dict instead of a Streamlit runtime.

One network at a time, deliberately. A raw export is real people's names, and
442 of them cost 1.3 GB at peak during the spike — against a 3 GB ceiling on
Community Cloud. Replacing rather than accumulating is what keeps a second
upload from being the thing that takes the app down.

Nothing here is written to disk. When the session ends, the network is gone.

The clock lives here because the build does: set_built starts it, touch()
restarts it, clear_built stops it. What happens when it runs out — the drop,
the warning, the download prompt — is src/dashboard/lifetime.py.

Time is always passed in (`now`), never read inline, so tests can drive it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from src.dashboard.session import session_store

BUILT_KEY = "built_network"
TOUCHED_KEY = "built_touched_at"
CLASSIFICATION_CACHE_KEY = "classification_cache"

# An hour of INACTIVITY, not an hour from the build. Reviewing people,
# reading summaries and asking questions all refresh it, so the clock only
# runs down when nobody is here — which is when a stranger's names sitting in
# memory stops being something anyone is using.
LIFETIME = timedelta(hours=1)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def get_built(store: Optional[dict] = None):
    """The network built this session, or None for the demo."""
    return session_store(store).get(BUILT_KEY)


def set_built(result, store: Optional[dict] = None,
              now: Optional[datetime] = None) -> None:
    """Hold one network, replacing any previous one, and start its clock.

    The previous BuildResult goes out of scope here, which is what lets its
    frame be collected before the next build peaks.
    """
    held = session_store(store)
    held[BUILT_KEY] = result
    held[TOUCHED_KEY] = now or _now()


def classification_cache(store: Optional[dict] = None) -> dict:
    """The classification cache for this session (D-71).

    Held here rather than on disk so a visitor's job titles never reach a
    shared file. Scoped to the session so a retry, or a second build after
    Start over, does not pay again for a title already answered.

    clear_built leaves it alone on purpose: it is keyed by title, not by row,
    so unlike the corrections (D-65) it cannot attach to the wrong person.
    The expiry clears it with everything else.
    """
    return session_store(store).setdefault(CLASSIFICATION_CACHE_KEY, {})


def clear_built(store: Optional[dict] = None) -> None:
    """Drop the network and go back to the demo.

    The work done on it goes too (D-65). Whatever is on screen next — the
    demo, or a later upload — has different people at the same indices.
    """
    forget_network_work(store)
    session_store(store).pop(BUILT_KEY, None)
    session_store(store).pop(TOUCHED_KEY, None)


def forget_network_work(store: Optional[dict] = None) -> None:
    """Drop everything keyed to the network on screen, when it stops being on
    screen.

    D-65: corrections and notes are {person_index: ...}, and person_index is
    a row position. Kept across a change of network, a correction made to the
    demo's person 87 is shown on the visitor's own person 87 as a judgement
    they gave — a false claim about a real individual. Chat history, group
    summaries, skips, the selection and the restore report all name or point
    at people in the network that has gone.

    Kept, deliberately:
      * the API key and its check — they belong to the visitor, not the network;
      * chat_questions_asked — the free allowance is per session, and
        resetting it here would make "upload again" a way round it;
      * the self-enrichment inputs and result — about the visitor, not their
        connections;
      * session_io's applied-file marker — clearing it re-applies a restore
        file still in the uploader to a network nobody restored it into.

    A retry does not call this: it is the same network with more of it
    classified, and a correction made before it must survive it.
    """
    from src.dashboard.chat import HIGHLIGHT_KEY, HISTORY_KEY
    from src.dashboard.notes import NOTES_KEY
    from src.dashboard.people_list import PAGE_KEY, SELECTED_KEY, SKIPPED_KEY
    from src.dashboard.retry_offer import OFFER_SLOT
    from src.dashboard.lifetime import SAVED_KEY
    from src.dashboard.session_io import KEY_REPORT
    from src.dashboard.state import CORRECTIONS_KEY
    from src.dashboard.summaries import SUMMARIES_KEY

    held = session_store(store)
    for key in (CORRECTIONS_KEY, NOTES_KEY, HISTORY_KEY, HIGHLIGHT_KEY,
                SUMMARIES_KEY, SKIPPED_KEY, SELECTED_KEY, OFFER_SLOT,
                KEY_REPORT, SAVED_KEY):
        held.pop(key, None)
    # One page number per list mode, stored as f"{PAGE_KEY}_{mode}".
    for key in [k for k in held if str(k).startswith(f"{PAGE_KEY}_")]:
        held.pop(key, None)


# --- the clock ---------------------------------------------------------------


def touch(store: Optional[dict] = None, now: Optional[datetime] = None) -> None:
    """Mark the session as in use. Called on every full rerun; a no-op with
    nothing built."""
    held = session_store(store)
    if BUILT_KEY in held:
        held[TOUCHED_KEY] = now or _now()


def remaining(store: Optional[dict] = None,
              now: Optional[datetime] = None) -> Optional[timedelta]:
    """How long a built network has left, or None when there is nothing to lose.

    None rather than zero for "no network": a caller asking how long is left
    should not get an answer that reads as "about to expire".
    """
    held = session_store(store)
    if BUILT_KEY not in held:
        return None
    touched = held.get(TOUCHED_KEY)
    if touched is None:
        return LIFETIME
    return touched + LIFETIME - (now or _now())
