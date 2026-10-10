"""
src/dashboard/retry_offer.py — P2.9b: the offer to classify after a key arrives.

A keyless build puts everyone in REASON_NO_KEY, which is correctly not
retryable: retrying with no key fails identically. Then a key is pasted, and
that reason becomes stale — it described the world at build time, and the world
changed.

This is a separate control from the notice's retry button, deliberately. The
notice offers a retry when a REASON is retryable; this offers one when a KEY
ARRIVES. Merging them would mean loosening _NOT_RETRYABLE, which would put a
button in front of people whose key is dead, where it can only fail.

Nothing here classifies. It renders a question and calls the same handler the
notice does.

The cost is quoted from provenance, not from the headcount. Someone is about to
spend their own money, and the number they are shown has to be the number they
will be charged for.
"""

from __future__ import annotations

from typing import Callable, Optional

from src.dashboard.session import session_store
from src.dashboard.unclassified import retry_targets

OFFER_SLOT = "retry_offer_pending"


def offer_retry(store: Optional[dict] = None) -> None:
    """Record that a key arrived while an unclassified build was on screen."""
    session_store(store)[OFFER_SLOT] = True


def clear_offer(store: Optional[dict] = None) -> None:
    """Forget the offer: accepted, declined, or overtaken by a new build."""
    session_store(store).pop(OFFER_SLOT, None)


def offered(store: Optional[dict] = None) -> bool:
    return bool(session_store(store).get(OFFER_SLOT))


def _cost_clause(built, pending: int) -> str:
    """What this will actually send, when the build recorded it.

    Falls back to saying nothing rather than guessing. An absent figure is a
    build from before this was stored; inventing one from the headcount would
    overstate the cost, which is the failure this clause exists to avoid.
    """
    uncached = (getattr(built, "provenance", None) or {}).get("uncached_titles")
    if uncached is None:
        return ""
    if uncached == 0:
        return " Every title is already cached, so this will not use your key."
    return (
        f" {uncached:,} title{'' if uncached == 1 else 's'} would be sent to "
        "the classifier; the rest are already cached."
    )


def take_offer(
    df,
    built,
    on_retry: Callable[[list[int]], None],
    *,
    st=None,
    store: Optional[dict] = None,
) -> bool:
    """Draw the offer if one is pending. True when a retry was started.

    Returns True so the caller can stop drawing: the retry reruns the script,
    and continuing to render a table that is about to be replaced wastes a
    pass and risks showing a half-updated screen.
    """
    if not offered(store):
        return False

    targets = retry_targets(df)
    if not targets:
        # The build was replaced, or a retry already succeeded. Nothing to
        # offer, and a stale prompt is worse than none.
        clear_offer(store)
        return False

    if st is None:
        import streamlit as st  # noqa: PLC0415 — lazy, as everywhere in dashboard/

    st.info(
        f"Your key is ready. {len(targets):,} people are not classified yet."
        + _cost_clause(built, len(targets))
    )
    accept, decline = st.columns(2)

    if accept.button("Classify them now", key="take_retry_offer"):
        clear_offer(store)
        on_retry(targets)
        return True

    if decline.button("Not now", key="decline_retry_offer"):
        clear_offer(store)

    return False
