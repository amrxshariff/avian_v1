"""
src/dashboard/unclassified.py — P2.9b: the vocabulary for a build that lost
some of its classifications, and the one notice that reports it.

Why this is its own module
--------------------------
The fourth display state lives in state.py, with the overlay it belongs to.
The REASON a person is in it — the service was busy, the key died, the free
allowance ran out — is a different fact: it comes from the build, not from the
user's corrections, and it is wording rather than state. Putting it here keeps
state.py about the overlay, and gives the app, the card and (later) the API one
place to read the same phrasing from.

Wording rules, fixed here so no surface invents its own:

  * Never "needs review", never "uncertain", never "unclassifiable". Nobody has
    judged these people. Saying otherwise is the D-42 failure in prose.
  * Say what happened and what the user can do. A reason the user cannot act on
    ("an internal error occurred") is noise on a screen that already tells them
    the count.

Retry is NOT offered for every reason. A busy service and an unanswerable title
are worth retrying immediately; an exhausted allowance and a dead key are not —
retrying those simply fails again, and the app offers the key field or the demo
instead (the free-tier decision). can_retry() encodes that.

Version A holds: nothing here reads or writes anything outside the frame it is
given.
"""

from __future__ import annotations

from typing import Callable, Iterable, Sequence

import pandas as pd

from src.dashboard.state import STATE_NOT_CLASSIFIED
from src.dashboard.keys import KEY_USER
from src.failure_reasons import (   # noqa: F401 - re-exported vocabulary
    ALL_REASONS,
    REASON_BUDGET_REACHED,
    REASON_KEY_FAILED,
    REASON_NO_KEY,
    REASON_SERVICE_BUSY,
    REASON_UNANSWERABLE,
)

# The base table's column, written by the build function (P2.9b slice 4).
REASON_COLUMN = "unclassified_reason"

# Retrying these fails the same way until something changes outside the app.
_NOT_RETRYABLE = frozenset({
    REASON_KEY_FAILED, REASON_BUDGET_REACHED, REASON_NO_KEY,
})

# reason -> phrase. Written to complete "… not classified yet, because <phrase>".
_PHRASES: dict[str, str] = {
    REASON_SERVICE_BUSY: "the classification service was busy",
    REASON_BUDGET_REACHED: "today's free allowance ran out",
    REASON_UNANSWERABLE: "no usable answer came back for the title",
    # Not an apology. The network is built and on screen; this says what is
    # missing and what would fix it.
    REASON_NO_KEY: "no API key has been added yet",
}

BUDGET_KEY_POINTER = "Add your own key to classify them now."

# key_failed reads differently depending on whose key it was. Telling a user
# that THEIR key was rejected when the build ran on the project's key is a
# false claim about their account, so the two are never merged.
_PHRASE_KEY_FAILED_OWN = "your API key was rejected or ran out of credit"
_PHRASE_KEY_FAILED_PROJECT = "the classification service was unavailable"

# A build that recorded no source. Both phrases above are claims, and a claim
# nobody supplied the evidence for is the D-42 failure in prose: saying more
# than is known, on a screen the user cannot check. This says only what is
# certain (D-63).
_PHRASE_KEY_FAILED_UNKNOWN = "the classification did not complete"

MIXED_REASONS = "for more than one reason"


def reason_phrase(reason: str, source: str | None = None) -> str:
    """The user-facing phrase for one reason.

    `source` is whose key the BUILD used, from provenance — not whose key is
    in the session now. Someone can fail on the project key and then paste
    their own, and the explanation belongs to the failure, not to the present.
    None means the build recorded nothing, and the wording claims nothing.

    Raises on an unrecognised reason, for the same purpose as
    require_known_state: a reason nobody wrote wording for must not be shown
    to the user as one somebody did.
    """
    value = str(reason)
    if value == REASON_KEY_FAILED:
        if source is None:
            return _PHRASE_KEY_FAILED_UNKNOWN
        return (
            _PHRASE_KEY_FAILED_OWN if source == KEY_USER
            else _PHRASE_KEY_FAILED_PROJECT
        )
    if value not in _PHRASES:
        raise ValueError(
            f"Unrecognised {REASON_COLUMN} {value!r}. Expected one of "
            f"{list(ALL_REASONS)}."
        )
    return _PHRASES[value]


def is_unknown_source_phrase(phrase: str) -> bool:
    """True for the phrase that claims nothing, so callers can avoid
    restating what their own sentence already says."""
    return phrase == _PHRASE_KEY_FAILED_UNKNOWN


def can_retry(reasons: Iterable[str]) -> bool:
    """True when retrying could plausibly succeed without the user acting.

    A mixed set counts as retryable: the busy-service people would come back,
    and the rest stay where they are. Offering nothing because one person's
    reason is a dead key would strand the others.
    """
    values = {str(r) for r in reasons}
    if not values:
        return False
    return bool(values - _NOT_RETRYABLE)


def pending(df: pd.DataFrame) -> pd.DataFrame:
    """Rows the classifier never answered for, per the live display table."""
    if "display_state" not in df.columns:
        return df.iloc[0:0]
    return df.loc[df["display_state"].astype(str) == STATE_NOT_CLASSIFIED]


def reasons_in(df: pd.DataFrame) -> list[str]:
    """Distinct reasons present among the pending rows, in a stable order."""
    rows = pending(df)
    if rows.empty or REASON_COLUMN not in rows.columns:
        return []
    values = {str(r) for r in rows[REASON_COLUMN].dropna() if str(r).strip()}
    return [r for r in ALL_REASONS if r in values]


def retry_targets(df: pd.DataFrame) -> list[int]:
    """person_index values a retry would send again, lowest first."""
    return sorted(int(i) for i in pending(df)["person_index"])


def pending_clause(
    count: int, reasons: Sequence[str], source: str | None = None,
) -> str:
    """The count phrase used in the header and the captions.

    One reason is named. Several are not enumerated: the header is a one-line
    summary, and four clauses in it would bury the number the user came for.
    """
    if count <= 0:
        return ""
    lead = f"{count} not classified yet"
    if not reasons:
        return lead
    if len(reasons) == 1:
        return f"{lead} ({reason_phrase(reasons[0], source)})"
    return f"{lead} ({MIXED_REASONS})"


def render_notice(
    df: pd.DataFrame,
    on_retry: Callable[[list[int]], None] | None = None,
    *,
    st=None,
    source: str | None = None,
) -> list[int] | None:
    """Report the pending people and, where a retry could help, offer one.

    `on_retry` is INJECTED rather than imported: the real one is the build
    function (slice 4), which does not exist yet, and a control wired to
    nothing is worse than no control. Passing None renders the sentence
    without a button, which is what the app does until slice 4 supplies it.
    The same seam makes this testable now with a fake.

    Returns the indices a retry was requested for, or None. Nothing is
    rendered at all when no one is pending, so a healthy build shows no trace
    of this machinery.
    """
    rows = pending(df)
    if rows.empty:
        return None

    if st is None:
        import streamlit as st  # noqa: PLC0415 — lazy, as everywhere in dashboard/

    reasons = reasons_in(df)
    targets = retry_targets(df)

    # The COUNT belongs to the header, which already carries every other
    # figure on this screen. This line carries what the header cannot: why,
    # and what it does not mean.
    why = ""
    if len(reasons) == 1:
        phrase = reason_phrase(reasons[0], source)
        # The unknown-source phrase IS this sentence's lead; "because" it
        # would be a tautology.
        why = " The classification did not complete" + (
            "." if is_unknown_source_phrase(phrase) else f", because {phrase}."
        )
    elif reasons:
        why = f" The classification did not complete, {MIXED_REASONS}."
    if REASON_BUDGET_REACHED in reasons:
        # A spent day is not worth retrying (can_retry says so), so the notice
        # says what is: the visitor's own key (D-80, design item 6).
        why += " " + BUDGET_KEY_POINTER
    st.caption(
        f"Nobody has judged these titles, so they belong to no group.{why}"
    )

    if on_retry is None or not can_retry(reasons):
        return None

    if st.button(f"Retry {len(targets)}", key="retry_unclassified"):
        on_retry(targets)
        return targets
    return None
