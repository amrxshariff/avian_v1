"""
src/dashboard/card.py — P2.5 profile card + P2.1 confirmation control.

The detail surface for one selected node. Delivered as one unit with P2.1's UI
half, because the confirmation control has no surface to live on until the card
exists.

Two layers, matching the discipline in state.py:

  * PURE CORE (no streamlit) — provenance_label(), group_label(), skills_note().
    Take primitives and a row, return strings. Unit-testable under plain pytest.
    Whether a node was user-corrected is passed IN as a bool rather than read
    from session state, so these stay pure (same dependency-injection pattern as
    the encoder in onet.py).

  * STREAMLIT GLUE — render_profile_card(). Reads corrections from session
    state, delegates to the core for every string, and writes assignments back
    via state.set_correction().

Attribution rule (Phases 2-3 Amendment 2, 18 Aug 2026)
-----------------------------------------------------
No taxonomy-derived skills are attributed to an individual. Config E returns a
2-digit SOC MAJOR GROUP; O*NET skills join on DETAILED O*NET-SOC codes, so any
route from a classification to a person's skills passes through a group-level
inference. Rendering "financial modelling, forecasting" against a named person
because their title landed in group 13 is the confidently-wrong-while-citing-
an-authoritative-taxonomy failure the abstention design exists to prevent.

The skills section therefore renders an honest empty state until user-supplied
enrichment (P2.2) or notes (P2.2b) populate it. Group-level occupational
profiles arrive at P3.6, worded as a property of the occupation.

The archetype enrichment sidecar (removed in P2.9a) must NOT be resurrected
here: its skills derived from the superseded synthetic generator and could only
invert our own assumptions.
"""

from __future__ import annotations

import pandas as pd

from src.dashboard.unclassified import (
    REASON_COLUMN,
    is_unknown_source_phrase,
    reason_phrase,
)
from src.dashboard.state import (
    NEEDS_REVIEW_NAME,
    NOT_CLASSIFIED_NAME,
    NOT_OCCUPATION,
    NOT_OCCUPATION_NAME,
    SOC_MAJOR_OPTIONS,
    STATE_CLASSIFIED,
    STATE_NEEDS_REVIEW,
    STATE_NOT_CLASSIFIED,
    STATE_NOT_OCCUPATION,
    require_known_state,
)

# --- provenance strings ------------------------------------------------------

# User action always outranks classifier provenance: if a human resolved the
# node, that is where the current value came from, whatever the tier says.
PROV_USER_CORRECTED = "Confirmed by you"
PROV_USER_NOT_OCCUPATION = "Marked by you as not an occupation"

# Base-table provenance, keyed by the classifier_tier column. Worded so the
# reader can tell a lexicon lookup from a model inference — they carry different
# amounts of trust and the card should not flatten them.
TIER_LABELS: dict[str, str] = {
    "claude": "Inferred from job title by the Claude classifier",
    "exact": "Matched verbatim to the O*NET title lexicon",
    "fuzzy": "Fuzzy-matched to the O*NET title lexicon",
    "embedding": "Matched by embedding similarity (superseded tier)",
    "abstain": "The classifier abstained — no occupation assigned",
}
PROV_UNKNOWN_TIER = "Provenance not recorded"

# P2.9b: the classifier never answered for this person. It must NOT borrow the
# abstain tier's wording — "the classifier abstained" would claim a decision
# nobody made (D-42). The reason and the retry control arrive with the build
# function; this line is the floor below which the card cannot mislead.
PROV_NOT_CLASSIFIED = "The classification did not complete for this person"

# The honest empty state. States the rule rather than apologising for the gap:
# the absence of skills here is a design decision, not a missing feature.
SKILLS_EMPTY_NOTE = (
    "No skills recorded. This tool attributes skills to a person only where "
    "that person's own words are the source. The occupation group above is an "
    "inference from their job title — it is not a claim about what they can do."
)

SKILLS_HEADING = "Skills"
UNCERTAIN_HELP = (
    "The classifier could not place this title with confidence. Assign a group "
    "below, or mark it as not an occupation. Leaving it unreviewed is also fine "
    "— a blank node is honest."
)

# Label used in the assignment dropdown for the sentinel.
NOT_OCCUPATION_LABEL = "— Not an occupation —"
UNCHANGED_LABEL = "— Select a group —"


# --- pure core ---------------------------------------------------------------

def group_label(row: pd.Series) -> str:
    """The occupation group line: a real group name, or the honest placeholder.

    Reads display_state rather than soc_major, so a corrected node and a base
    classified node render identically and an unreviewed abstain can never be
    mistaken for a classification (DoD-9).

    Exhaustive over ALL_STATES (D-54), including the blank-name case: a
    classified row with no group name is a broken table, and labelling it
    "Needs review" — which this did — tells the user the classifier declined
    when it did not. Raising is the honest outcome, and the same rule the
    sidecar guard in loader.py already follows.
    """
    state = require_known_state(row["display_state"])
    if state == STATE_NEEDS_REVIEW:
        return NEEDS_REVIEW_NAME
    if state == STATE_NOT_OCCUPATION:
        return NOT_OCCUPATION_NAME
    if state == STATE_NOT_CLASSIFIED:
        return NOT_CLASSIFIED_NAME
    name = row.get("soc_major_name")
    if name is None or (isinstance(name, float) and pd.isna(name)) or not str(name).strip():
        raise ValueError(
            f"person_index {row.get('person_index')!r} is {STATE_CLASSIFIED} "
            "with no soc_major_name. The table is malformed; the card will not "
            "invent a label for it."
        )
    return str(name)


def provenance_label(row: pd.Series, corrected: bool,
                     source: str | None = None) -> str:
    """Where the currently displayed group came from.

    `corrected` is passed in rather than looked up so this stays pure. A user
    action outranks the classifier tier: once a human has resolved the node, the
    tier describes a superseded attempt, not the value on screen.

    `source` is the build's recorded key source, passed through to
    reason_phrase so the card and the notice give the same explanation.
    """
    if corrected:
        if row["display_state"] == STATE_NOT_OCCUPATION:
            return PROV_USER_NOT_OCCUPATION
        return PROV_USER_CORRECTED

    if require_known_state(row["display_state"]) == STATE_NOT_CLASSIFIED:
        # Before the classifier tier is consulted: a failed call may well have
        # left a tier behind from an earlier attempt, and "abstained" is the
        # one thing this person definitely did not do.
        reason = row.get(REASON_COLUMN)
        if reason is None or (isinstance(reason, float) and pd.isna(reason)) \
                or not str(reason).strip():
            return PROV_NOT_CLASSIFIED
        phrase = reason_phrase(str(reason), source)
        # The unknown-source phrase restates PROV_NOT_CLASSIFIED; appending it
        # would say the same thing twice.
        if is_unknown_source_phrase(phrase):
            return PROV_NOT_CLASSIFIED
        return f"{PROV_NOT_CLASSIFIED}: {phrase}"

    tier = row.get("classifier_tier")
    if tier is None or (isinstance(tier, float) and pd.isna(tier)):
        return PROV_UNKNOWN_TIER
    return TIER_LABELS.get(str(tier).strip().lower(), PROV_UNKNOWN_TIER)


def confidence_note(row: pd.Series, corrected: bool = False) -> str | None:
    """A short confidence line for classifier-assigned nodes, or None to omit it.

    Omitted for uncertain nodes (a score on a value never asserted implies false
    certainty) and for user-corrected nodes (the score belongs to the classifier's
    superseded attempt, not to the value on screen).
    """
    if corrected or row["display_state"] != STATE_CLASSIFIED:
        return None
    raw = row.get("classifier_confidence")
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    try:
        score = float(raw)
    except (TypeError, ValueError):
        return None
    return f"Classifier confidence {score:.2f}"


def skills_note(user_enrichment: str | None = None) -> str:
    """The skills section body. Absent user-supplied text, states why (Amendment 2)."""
    if user_enrichment and str(user_enrichment).strip():
        return str(user_enrichment).strip()
    return SKILLS_EMPTY_NOTE


def assignment_options() -> list[str]:
    """Dropdown labels: placeholder, all 23 SOC groups, then the sentinel.

    All 23 are offered — never only the groups present in this network — so the
    user can assign a group nobody currently holds. SOC_MAJOR_OPTIONS is sorted
    by code in state.py, so the order is stable across users and renders.
    """
    return (
        [UNCHANGED_LABEL]
        + [f"{code} · {name}" for code, name in SOC_MAJOR_OPTIONS]
        + [NOT_OCCUPATION_LABEL]
    )


def parse_assignment(label: str) -> str | None:
    """Dropdown label -> a value for set_correction(), or None for the placeholder.

    Returns the sentinel for the not-an-occupation option and the 2-digit code
    otherwise. None means "the user has not chosen anything yet" and must not be
    written as a correction.
    """
    if not label or label == UNCHANGED_LABEL:
        return None
    if label == NOT_OCCUPATION_LABEL:
        return NOT_OCCUPATION
    return label.split(" · ", 1)[0].strip()


# --- streamlit glue ----------------------------------------------------------

def render_profile_card(row: pd.Series, source: str | None = None) -> None:
    """Render the detail card for one node, with the P2.1 control where relevant.

    Reads corrections from session state to decide provenance and to pre-fill
    the control, and writes assignments back through state.set_correction().
    Calls st.rerun() after a write so the canvas, the counter and the card all
    rebuild from the corrected table in one pass — a rerun, not a page reload.
    """
    import streamlit as st

    from src.dashboard.state import (
        clear_correction,
        get_corrections,
        set_correction,
    )

    person_index = int(row["person_index"])
    corrections = get_corrections()
    corrected = person_index in corrections
    state = require_known_state(row["display_state"])

    st.markdown(f"### {row['name']}")

    # The raw title, verbatim (DoD-1). Never normalised, never title-cased: the
    # user is being asked to judge THIS string, so it must be the string the
    # classifier saw.
    raw_title = str(row.get("role") or "").strip()
    st.markdown(f"**{raw_title}**" if raw_title else "_No job title in the export_")

    # --- occupation group + provenance ---
    label = group_label(row)
    if state == STATE_NEEDS_REVIEW:
        st.warning(f"**{label}**", icon="⚠️")
    elif state == STATE_NOT_OCCUPATION:
        st.info(f"**{label}**")
    elif state == STATE_NOT_CLASSIFIED:
        # Not a success box: nothing succeeded. Not the needs-review warning
        # either, which asks the user to act; the retry belongs to the app.
        st.info(f"**{label}**")
    else:
        st.success(f"**{label}**")

    st.caption(provenance_label(row, corrected, source))
    note = confidence_note(row, corrected)
    if note:
        st.caption(note)

    # --- confirmation control (P2.1) ---
    if state == STATE_NEEDS_REVIEW:
        st.caption(UNCERTAIN_HELP)
        _render_assignment(st, person_index, set_correction, key_prefix="assign")
    elif corrected:
        if st.button("Undo this correction", key=f"undo_{person_index}",
                     use_container_width=True):
            clear_correction(person_index)
            st.rerun()
    else:
        # Classified by the classifier, not by the user. The DoD does not require
        # an override here, but precision when it commits is ~63.5% on the blind
        # set, so a visible wrong group with no way to fix it would be the same
        # honesty failure in the opposite direction. Collapsed so it does not
        # compete with the primary review queue.
        with st.expander("Change this group"):
            _render_assignment(st, person_index, set_correction, key_prefix="override")

    # --- skills (Amendment 2) ---
    st.markdown(f"**{SKILLS_HEADING}**")
    st.caption(skills_note(None))  # P2.2 / P2.2b will pass user-supplied text here

    from src.dashboard.notes import render_notes
    render_notes(person_index)


def _render_assignment(st, person_index: int, setter, key_prefix: str) -> None:
    """The 23-group + not-an-occupation dropdown and its apply button."""
    choice = st.selectbox(
        "Assign an occupation group",
        assignment_options(),
        key=f"{key_prefix}_select_{person_index}",
        label_visibility="collapsed",
    )
    value = parse_assignment(choice)
    if st.button("Apply", key=f"{key_prefix}_apply_{person_index}",
                 disabled=value is None, use_container_width=True):
        setter(person_index, value)
        st.rerun()
