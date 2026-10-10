"""
src/dashboard/state.py — Phase 2, P2.1: the correction-overlay accessor.

This is the single load-bearing abstraction of the dashboard. P2.1 (the review
UX), P2.5 (profile cards), P2.7 (cluster summaries) and P2.8 (chat) must ALL
read the network through one accessor that applies the user's session
corrections on top of the canonical base frame. If any module reads the
canonical CSV directly (D-33: that reader is loader.py alone now), it silently
ignores corrections and the P2.7 "regenerate on membership change" DoD becomes
unsatisfiable.

Two layers, deliberately separated:

  * PURE CORE (no streamlit import) — apply_corrections(), review_counts(),
    validation. Unit-testable under plain pytest, no Streamlit runtime. Takes the
    corrections dict as an argument (dependency injection, same pattern as the
    encoder in onet.py / the client in claude_classifier.py).

  * STREAMLIT GLUE — init_state(), set_correction() etc. Pulls the corrections
    dict from st.session_state and delegates to the core.
    streamlit is imported lazily inside these functions so importing this module
    for a test never requires it.

Design decisions (see the Phase 2 walkthrough):
  1. Overlay is a flat dict[int, str]: person_index -> SOC code "11".."55", or
     the sentinel NOT_OCCUPATION. Distinct from "99", which is the base table's
     code for an unreviewed abstain. Presence of a key == the user has resolved
     that node.
  2. Applied eagerly and uncached on every rerun; returns a COPY. At 430 rows a
     rebuild is trivial, so there is no cache-invalidation logic to get wrong.
  3. A single derived `display_state` in ALL_STATES drives colour, the counter,
     and the P2.5 confirmation control. `is_uncertain` in the output is
     RECOMPUTED from display_state, so a node can never be both corrected and
     still flagged uncertain (DoD-6), and a person whose classification never
     arrived is never counted as one the classifier declined.

Version A: corrections live only in st.session_state and are never written to
disk. Nothing here persists server-side.
"""

from __future__ import annotations

import pandas as pd

# MAJOR_GROUP_NAMES is the authoritative 23-entry SOC major-group table. Importing
# src.onet is cheap: its heavy deps (sentence-transformers) are lazy-loaded inside
# functions, so top-level import pulls only pandas/numpy/stdlib.
from src.onet import MAJOR_GROUP_NAMES

# --- constants ---------------------------------------------------------------

# The user's "this title names no occupation" verdict. MUST stay distinct from
# "99" (the base table's unreviewed-abstain code): "99" means the classifier
# abstained and nobody has looked; NOT_OCCUPATION means a human looked and
# confirmed there is no job here. The counter and the colouring both depend on
# telling these apart.
NOT_OCCUPATION = "NOT_OCCUPATION"
NOT_OCCUPATION_NAME = "Not an occupation"

# The base table's code/label for an abstained, not-yet-reviewed node.
UNREVIEWED_CODE = "99"
NEEDS_REVIEW_NAME = "Needs review"

# The classifier never answered for this person, because the call failed. A
# DIFFERENT claim from "99": there, the model looked and declined. Here nobody
# ever got an answer, so the honest thing is to say so and offer a retry. D-42
# was these two being stored as one.
NOT_CLASSIFIED = "NOT_CLASSIFIED"
NOT_CLASSIFIED_NAME = "Not classified yet"

# The four display states every UI branch reads. ALL_STATES is the list a
# consumer must handle exhaustively; it exists so that adding a fifth breaks
# the branching tests rather than falling through to an older state's colour
# or label (D-54).
STATE_CLASSIFIED = "classified"
STATE_NEEDS_REVIEW = "needs_review"
STATE_NOT_OCCUPATION = "not_occupation"
STATE_NOT_CLASSIFIED = "not_classified"
ALL_STATES: tuple[str, ...] = (
    STATE_CLASSIFIED,
    STATE_NEEDS_REVIEW,
    STATE_NOT_OCCUPATION,
    STATE_NOT_CLASSIFIED,
)

# What the CLASSIFIER did, as recorded in the base table. Distinct from the
# display state above, which also folds in the user's corrections:
#   assigned       -> a real SOC major group
#   abstained      -> the model declined; soc_major is "99"
#   not_classified -> the call never produced an answer (see NOT_CLASSIFIED)
STATUS_COLUMN = "classification_status"
STATUS_ASSIGNED = "assigned"
STATUS_ABSTAINED = "abstained"
STATUS_NOT_CLASSIFIED = "not_classified"
_VALID_STATUSES = frozenset(
    {STATUS_ASSIGNED, STATUS_ABSTAINED, STATUS_NOT_CLASSIFIED}
)

# Session-state key under which the corrections dict lives.
CORRECTIONS_KEY = "corrections"

# The set of values a correction may legitimately take.
_VALID_CORRECTION_VALUES = set(MAJOR_GROUP_NAMES) | {NOT_OCCUPATION}

# The full 23-option list a P2.1 dropdown must offer — ALL groups, not just the
# ~18 present in any one network, so the user can assign a group nobody holds yet.
SOC_MAJOR_OPTIONS: list[tuple[str, str]] = sorted(MAJOR_GROUP_NAMES.items())


# --- pure core (no streamlit) ------------------------------------------------

def validate_correction(value: str) -> None:
    """Raise ValueError if `value` is not a real SOC code or the sentinel.

    Fails loud: a bad correction value is a programming error in the caller, not
    user input to be silently swallowed (same philosophy as the alignment guards
    in ingestion.py / labelling.py).
    """
    if value not in _VALID_CORRECTION_VALUES:
        raise ValueError(
            f"Invalid correction value {value!r}. Expected one of the 23 SOC "
            f"major-group codes or {NOT_OCCUPATION!r}."
        )


def require_known_state(state: str) -> str:
    """Return `state`, or raise if no consumer would know how to render it.

    Every branch on display_state calls this instead of ending in an `else`
    that quietly means "one of the old states". D-54: a canvas point, a card
    label and a chat record each fell through to needs-review, so a state the
    code did not recognise would have been shown to the user as one it did —
    the same class of false claim as D-42.
    """
    value = str(state)
    if value not in ALL_STATES:
        raise ValueError(
            f"Unrecognised display_state {value!r}. Expected one of "
            f"{list(ALL_STATES)}. A new state must be handled everywhere it "
            "is rendered, not defaulted."
        )
    return value


def _row_state(person_index: int, base_uncertain: bool, status: str,
               corrections: dict[int, str]) -> tuple[str, str, str]:
    """Resolve one row to (display_state, soc_major, soc_major_name).

    Precedence, highest first:
      1. a correction      -> classified (real code) or not_occupation
      2. not_classified    -> the call failed; no answer exists to show
      3. the base flag     -> uncertain means needs_review
      4. otherwise         -> classified, keeping the base values

    A correction outranks a failed call on purpose: the user has supplied the
    answer the classifier never did, and making them wait for a retry to see
    their own verdict would be absurd.
    """
    if person_index in corrections:
        value = corrections[person_index]
        if value == NOT_OCCUPATION:
            return STATE_NOT_OCCUPATION, NOT_OCCUPATION, NOT_OCCUPATION_NAME
        return STATE_CLASSIFIED, value, MAJOR_GROUP_NAMES[value]
    if status == STATUS_NOT_CLASSIFIED:
        return STATE_NOT_CLASSIFIED, NOT_CLASSIFIED, NOT_CLASSIFIED_NAME
    if base_uncertain:
        return STATE_NEEDS_REVIEW, UNREVIEWED_CODE, NEEDS_REVIEW_NAME
    return STATE_CLASSIFIED, None, None  # sentinel: keep the base values


def _statuses(df: pd.DataFrame) -> list[str]:
    """One classifier status per row, validated.

    A table without the column predates P2.9b, and for those every row is
    exactly one of assigned or abstained — there was no third outcome a build
    could record. So the compatibility branch is a restatement of is_uncertain,
    not a guess. It can be deleted once no saved or tracked table lacks the
    column; nothing else depends on it.

    An unrecognised status RAISES rather than falling back to a display state,
    which is the D-54 rule: a state nobody recognises must never be rendered as
    a state somebody does.
    """
    uncertain = df["is_uncertain"].astype(bool)

    if STATUS_COLUMN not in df.columns:
        return [STATUS_ABSTAINED if u else STATUS_ASSIGNED for u in uncertain]

    statuses = df[STATUS_COLUMN].astype(str)
    unknown = sorted(set(statuses) - _VALID_STATUSES)
    if unknown:
        raise ValueError(
            f"Unrecognised {STATUS_COLUMN} value(s) {unknown}. Expected one of "
            f"{sorted(_VALID_STATUSES)}."
        )

    # is_uncertain means the model DECLINED. A row that is both not_classified
    # and uncertain would be counted in the review backlog (review_counts reads
    # is_uncertain) while displaying as not classified — the two numbers on
    # screen would then disagree, which is the D-18 shape.
    contradictory = statuses.eq(STATUS_NOT_CLASSIFIED) & uncertain
    if contradictory.any():
        rows = df.loc[contradictory, "person_index"].astype(int).tolist()[:8]
        raise ValueError(
            f"person_index {rows} are {STATUS_NOT_CLASSIFIED} AND is_uncertain. "
            "A failed call is not an abstention (D-42); is_uncertain must be "
            "False on a row the classifier never answered."
        )
    return statuses.tolist()


def apply_corrections(base_df: pd.DataFrame,
                      corrections: dict[int, str]) -> pd.DataFrame:
    """Return a COPY of `base_df` with session corrections applied.

    Adds/updates: soc_major, soc_major_name, display_state, is_uncertain.
    `is_uncertain` is recomputed as (display_state == needs_review), so the
    output can never present a corrected node as still-uncertain (DoD-6).

    Pure: no Streamlit, no disk, no mutation of `base_df`. Corrections keyed by a
    person_index absent from the table are ignored (a session can outlive a data
    reload); corrections with an invalid value raise via validate_correction.
    """
    for value in corrections.values():
        validate_correction(value)

    df = base_df.copy()
    # Normalise soc_major to str so joins against MAJOR_GROUP_NAMES (str keys)
    # and the "99" sentinel are type-safe even if the CSV parsed codes as int.
    df["soc_major"] = df["soc_major"].astype(str)

    statuses = _statuses(df)

    states, majors, names = [], [], []
    for (_, row), status in zip(df.iterrows(), statuses):
        pi = int(row["person_index"])
        state, major, name = _row_state(
            pi, bool(row["is_uncertain"]), status, corrections
        )
        states.append(state)
        majors.append(row["soc_major"] if major is None else major)
        names.append(row["soc_major_name"] if name is None else name)

    df["display_state"] = states
    df["soc_major"] = majors
    df["soc_major_name"] = names
    df["is_uncertain"] = df["display_state"] == STATE_NEEDS_REVIEW
    return df


def review_counts(base_df: pd.DataFrame,
                  corrections: dict[int, str]) -> tuple[int, int]:
    """Return (n_needs_review, m_total_uncertain) for the "N of M" counter.

    M = nodes uncertain in the BASE table (fixed for the session).
    N = those not yet resolved by a correction.
    A correction on an already-classified node touches neither number — it was
    never in the review queue — so the backlog stays honest.

    Unchanged by P2.9b, and deliberately: it reads is_uncertain, which stays
    True only where the model declined. People the classifier never answered
    for are NOT part of the review backlog, because nobody has asked the user
    to review them. A retry that turns one into an abstention enlarges M, and
    that is the one intended way M moves within a session.
    """
    base_uncertain_idx = set(
        base_df.loc[base_df["is_uncertain"], "person_index"].astype(int)
    )
    m = len(base_uncertain_idx)
    resolved = sum(1 for pi in corrections if pi in base_uncertain_idx)
    return m - resolved, m


# --- streamlit glue (lazy import) --------------------------------------------

def init_state() -> None:
    """Ensure the corrections dict exists in session state. Idempotent."""
    import streamlit as st

    if CORRECTIONS_KEY not in st.session_state:
        st.session_state[CORRECTIONS_KEY] = {}


def get_corrections() -> dict[int, str]:
    import streamlit as st

    init_state()
    return st.session_state[CORRECTIONS_KEY]


def set_correction(person_index: int, value: str) -> None:
    """Record a user assignment (a SOC code or NOT_OCCUPATION) for one node."""
    validate_correction(value)
    corrections = get_corrections()
    corrections[int(person_index)] = value


def clear_correction(person_index: int) -> None:
    """Undo a single correction, returning the node to its base state."""
    get_corrections().pop(int(person_index), None)


def clear_all_corrections() -> None:
    """Reset every correction (a documented session-reset control)."""
    get_corrections().clear()