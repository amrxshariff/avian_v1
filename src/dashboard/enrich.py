"""
src/dashboard/enrich.py — Phase 2, P2.2: the "Your profile" panel.

The UI half of self_enrichment.py. Shows the user one reading of their own
entry: their title and their own words, read together, with the caveat that it
is one answer from a classifier that can answer differently when asked again.

It used to set that beside the title-only reading. The comparison is withdrawn
(D-84): on identical input the About-informed reading abstained in three of six
runs while the title-only one never moved, so a side-by-side made a claim about
the visitor's writing that the code could not support.

Scope, structurally enforced (DoD-2)
------------------------------------
This panel takes no person_index, reads no row from the node table, and writes
nothing through state.set_correction(). It cannot be pointed at a connection
even by accident, because it has no way to name one. That is the whole design:
the boundary between "your own words" and "someone else's data" is held by the
absence of an argument, not by a comment asking future-you to be careful.

Confidence wording
------------------
The classifier returns a confidence in whatever it concluded, INCLUDING when it
concluded nothing. A confident abstain arrives as tier="abstain", score=0.95 —
verified on real prose: a graduate self-description scored 0.95 with the reason
"Recent graduate seeking role; no current job function". Rendering that as
"confidence 0.95" next to "no group assigned" would read as 95% confident in a
classification, which is the inverse of the truth. reading_lines() therefore
words the two cases differently and never prints a bare number against a null.
Same principle as card.confidence_note(), which omits the score entirely rather
than attach it to a value that was never asserted.

Nothing here is written to disk. The text lives in st.session_state for the
session and is dropped when the user clears it or closes the tab.
"""

from __future__ import annotations

from src.onet import Classification, MAJOR_GROUP_NAMES
from src.claude_classifier import CONFIDENCE_SCORES, MIN_CONFIDENCE, ClassificationFailed
from src.self_enrichment import (
    MAX_ABOUT_CHARS,
    MIN_ABOUT_CHARS,
    TIER_SELF_ENRICHED,
    classify_from_about,
)

# Session keys. Deliberately few: the panel holds the last result and the two
# inputs, nothing else, so "clear" is a complete erasure rather than a partial one.
KEY_RESULT = "self_enrichment_result"
KEY_TITLE = "self_enrichment_title"
KEY_ABOUT = "self_enrichment_about"

READING_LABEL = "From your title and your own description"

# True and sufficient for one reading; never sufficient for a comparison (D-84).
SINGLE_READING_CAVEAT = (
    "One answer, from a classifier that can answer differently when asked again."
)

# Provenance wording for this path. Kept here rather than added to card.py's
# TIER_LABELS because no card renders a self_enriched node yet — you are not a
# row in the export. The entry belongs in card.py when the self-node arrives
# with P2.9's upload flow, and adding it before there is a consumer would be a
# dead line pretending to be a feature.
TIER_WORDING = {
    TIER_SELF_ENRICHED: "Inferred from your own description",
    "claude": "Inferred from your job title by the Claude classifier",
    "abstain": "No group assigned",
}

PRIVACY_NOTE = (
    "Your title and description are sent to the Anthropic API to be classified, "
    "then discarded. Nothing you type here is written to disk, added to the "
    "network, or kept after this session."
)

INTRO = (
    "The classifier sees two or three words per person. This is the one entry "
    "where you can give it more — your own. Paste your LinkedIn About section "
    "and see what the classifier makes of your title and your own words together."
)

NO_GROUP = "No group assigned"


# --- pure core ---------------------------------------------------------------

def _is_confident(c: Classification) -> bool:
    """Did the model back its conclusion — including a conclusion of 'none'?"""
    return c.score >= CONFIDENCE_SCORES[MIN_CONFIDENCE]


def reading_lines(c: Classification) -> tuple[str, str, str | None]:
    """(group line, provenance line, confidence line or None) for one reading.

    The confidence line is worded against WHAT was concluded. A high score on an
    abstain means the model is sure no occupation is named — a real and useful
    answer — and must not be printed in the same shape as a score backing an
    assigned group.
    """
    provenance = TIER_WORDING.get(c.tier, "Provenance not recorded")

    if c.soc_major is None:
        group = NO_GROUP
        confidence = (
            "The classifier is confident your entry names no current occupation."
            if _is_confident(c)
            else "The classifier could not tell either way."
        )
        return group, provenance, confidence

    group = f"{c.soc_major} · {MAJOR_GROUP_NAMES.get(c.soc_major, '')}"
    return group, provenance, f"Classifier confidence {c.score:.2f}"


def about_input_error(about: str) -> str | None:
    """Validation message for the About box, or None if it is usable."""
    text = (about or "").strip()
    if not text:
        return "Paste your About section to see what the classifier makes of it."
    if len(text) < MIN_ABOUT_CHARS:
        return (
            f"That is {len(text)} characters. At least {MIN_ABOUT_CHARS} are "
            "needed for this to say anything your title did not already."
        )
    return None


# --- streamlit glue ----------------------------------------------------------

def render_enrichment_panel() -> None:
    """The 'Your profile' expander. Collapsed by default — it is optional.

    The dashboard is fully functional with this never opened (DoD-1): nothing
    downstream reads its output, because there is no self-node to attach it to
    yet. Today it shows one reading and stops there.
    """
    import streamlit as st

    with st.expander("Your profile"):
        st.caption(INTRO)

        title = st.text_input(
            "Your job title",
            key=KEY_TITLE,
            placeholder="the title that would appear against your name",
        )
        about = st.text_area(
            "Your About section",
            key=KEY_ABOUT,
            height=160,
            max_chars=MAX_ABOUT_CHARS,
            placeholder="paste your own words here",
        )

        # Stated BEFORE the button, so it is read before anything is sent, not
        # after (DoD-5).
        st.caption(PRIVACY_NOTE)

        problem = about_input_error(about)
        if st.button("Read my title and description", use_container_width=True,
                     disabled=problem is not None):
            _run_reading(st, title, about)

        if problem and about:
            st.caption(problem)

        result = st.session_state.get(KEY_RESULT)
        if isinstance(result, Classification):
            _render_result(st, result)


def _run_reading(st, title: str, about: str) -> None:
    """One API call behind a spinner, with every failure surfaced in plain words.

    Exceptions are caught and shown rather than allowed to blank the app: a
    missing key or a network error is a normal condition on a deployed tool, and
    a Streamlit traceback is not an error message a user can act on.
    """
    # D-46: a new reading replaces the last one. If it fails, nothing is
    # shown, rather than the previous reading under the error as if current.
    st.session_state.pop(KEY_RESULT, None)
    # D-80: charged to the daily ledger on the project key.
    from src.claude_classifier import _default_client as classifier_client
    from src.dashboard.keys import key_source
    from src.dashboard.metering import BUDGET_SPENT_NOTE, metered_client
    from src.spend import BudgetExceeded

    client = metered_client(key_source(), None, classifier_client)
    try:
        with st.spinner("Reading your title and description…"):
            st.session_state[KEY_RESULT] = classify_from_about(title, about, client=client)
    except BudgetExceeded:             # D-80: a RuntimeError, so caught first
        st.warning(BUDGET_SPENT_NOTE)
    except ClassificationFailed:       # D-46: before RuntimeError, its base
        st.error(
            "The classifier returned an incomplete answer, so no reading is "
            "shown. Nothing was saved. Try again in a moment."
        )
    except ValueError as exc:          # input too short — the user can fix it
        st.warning(str(exc))
    except RuntimeError as exc:        # no API key configured — the operator can
        st.error(str(exc))
    except Exception as exc:           # noqa: BLE001 — network, rate limit, SDK
        st.error(
            f"The classifier could not be reached ({type(exc).__name__}). "
            "Nothing was saved. Try again in a moment."
        )


def _render_result(st, result: Classification) -> None:
    """The one reading, and the caveat that it is one answer (D-84)."""
    group, provenance, confidence = reading_lines(result)
    st.divider()
    st.caption(READING_LABEL)
    if result.soc_major is None:
        st.info(f"**{group}**")
    else:
        st.success(f"**{group}**")
    st.caption(provenance)
    if confidence:
        st.caption(confidence)
    st.caption(SINGLE_READING_CAVEAT)

    if st.button("Clear", use_container_width=True):
        for key in (KEY_RESULT, KEY_TITLE, KEY_ABOUT):
            st.session_state.pop(key, None)
        st.rerun()