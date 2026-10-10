"""
tests/test_card.py — P2.5 card pure-core tests.

Covers only the Streamlit-free layer of src/dashboard/card.py: the string
builders and the dropdown round-trip. render_profile_card() needs a Streamlit
runtime and is verified manually against the DoD.

The load-bearing assertions are the honesty ones:
  * an unreviewed abstain never renders a group name (DoD-9);
  * a user correction outranks the classifier tier in provenance (DoD-2);
  * the skills section states the attribution rule rather than inventing skills
    (Amendment 2).
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.dashboard.card import (
    NOT_OCCUPATION_LABEL,
    PROV_UNKNOWN_TIER,
    PROV_USER_CORRECTED,
    PROV_USER_NOT_OCCUPATION,
    SKILLS_EMPTY_NOTE,
    TIER_LABELS,
    UNCHANGED_LABEL,
    assignment_options,
    confidence_note,
    group_label,
    parse_assignment,
    provenance_label,
    skills_note,
)
from src.dashboard.state import (
    MAJOR_GROUP_NAMES,
    NEEDS_REVIEW_NAME,
    NOT_OCCUPATION,
    NOT_OCCUPATION_NAME,
    STATE_CLASSIFIED,
    STATE_NEEDS_REVIEW,
    STATE_NOT_OCCUPATION,
)


def _row(**overrides) -> pd.Series:
    """A classified row by default; override any field per test."""
    base = {
        "person_index": 7,
        "name": "Test Person",
        "role": "Investment Analyst",
        "soc_major": "13",
        "soc_major_name": "Business and Financial Operations",
        "display_state": STATE_CLASSIFIED,
        "classifier_tier": "claude",
        "classifier_confidence": 0.95,
    }
    base.update(overrides)
    return pd.Series(base)


# --- group_label -------------------------------------------------------------

def test_group_label_classified_shows_group_name():
    assert group_label(_row()) == "Business and Financial Operations"


def test_group_label_needs_review_never_shows_a_group():
    """DoD-9: an unreviewed abstain must not render as confidently classified."""
    row = _row(display_state=STATE_NEEDS_REVIEW, soc_major="99",
               soc_major_name=NEEDS_REVIEW_NAME)
    assert group_label(row) == NEEDS_REVIEW_NAME


def test_group_label_reads_state_not_the_stale_name():
    """Even if soc_major_name still holds a real group, state wins."""
    row = _row(display_state=STATE_NEEDS_REVIEW,
               soc_major_name="Business and Financial Operations")
    assert group_label(row) == NEEDS_REVIEW_NAME


def test_group_label_not_occupation():
    row = _row(display_state=STATE_NOT_OCCUPATION, soc_major=NOT_OCCUPATION,
               soc_major_name=NOT_OCCUPATION_NAME)
    assert group_label(row) == NOT_OCCUPATION_NAME


def test_group_label_refuses_a_classified_row_with_no_group_name():
    """D-54: this used to read "Needs review", which is a claim about the
    classifier — that it declined — when in fact the table is malformed. A
    label the card cannot source is not a label it may invent.
    """
    for missing in (None, "   "):
        with pytest.raises(ValueError, match="malformed"):
            group_label(_row(soc_major_name=missing))


# --- provenance_label --------------------------------------------------------

def test_provenance_uses_tier_when_not_corrected():
    assert provenance_label(_row(), corrected=False) == TIER_LABELS["claude"]
    assert provenance_label(_row(classifier_tier="exact"), corrected=False) == \
        TIER_LABELS["exact"]


def test_provenance_user_correction_outranks_tier():
    """A human resolved it; the tier describes a superseded attempt."""
    row = _row(display_state=STATE_CLASSIFIED, classifier_tier="abstain")
    assert provenance_label(row, corrected=True) == PROV_USER_CORRECTED


def test_provenance_user_not_occupation():
    row = _row(display_state=STATE_NOT_OCCUPATION, soc_major=NOT_OCCUPATION)
    assert provenance_label(row, corrected=True) == PROV_USER_NOT_OCCUPATION


def test_provenance_unknown_tier_is_named_not_guessed():
    assert provenance_label(_row(classifier_tier=None), corrected=False) == \
        PROV_UNKNOWN_TIER
    assert provenance_label(_row(classifier_tier="wat"), corrected=False) == \
        PROV_UNKNOWN_TIER


# --- confidence_note ---------------------------------------------------------

def test_confidence_shown_for_classified():
    assert confidence_note(_row()) == "Classifier confidence 0.95"


def test_confidence_omitted_for_uncertain_states():
    """A score on a node the classifier declined to place implies false certainty."""
    assert confidence_note(_row(display_state=STATE_NEEDS_REVIEW)) is None
    assert confidence_note(_row(display_state=STATE_NOT_OCCUPATION)) is None


def test_confidence_omitted_when_missing_or_unparseable():
    assert confidence_note(_row(classifier_confidence=None)) is None
    assert confidence_note(_row(classifier_confidence="n/a")) is None


def test_confidence_omitted_when_user_corrected():
    """The score belongs to the classifier's superseded attempt, not the user's."""
    assert confidence_note(_row(classifier_confidence=0.40), corrected=True) is None


# --- skills_note (Amendment 2) ----------------------------------------------

def test_skills_note_empty_states_the_attribution_rule():
    note = skills_note(None)
    assert note == SKILLS_EMPTY_NOTE
    assert "own words" in note


def test_skills_note_returns_user_supplied_text():
    assert skills_note("  Python, SQL, forecasting  ") == "Python, SQL, forecasting"


def test_skills_note_blank_string_is_treated_as_absent():
    assert skills_note("   ") == SKILLS_EMPTY_NOTE


# --- dropdown round-trip -----------------------------------------------------

def test_assignment_options_offers_all_23_groups_plus_controls():
    opts = assignment_options()
    assert len(opts) == len(MAJOR_GROUP_NAMES) + 2
    assert opts[0] == UNCHANGED_LABEL
    assert opts[-1] == NOT_OCCUPATION_LABEL


def test_every_group_option_parses_back_to_its_code():
    for label in assignment_options()[1:-1]:
        code = parse_assignment(label)
        assert code in MAJOR_GROUP_NAMES


def test_parse_placeholder_returns_none():
    assert parse_assignment(UNCHANGED_LABEL) is None
    assert parse_assignment("") is None


def test_parse_not_occupation_returns_sentinel():
    assert parse_assignment(NOT_OCCUPATION_LABEL) == NOT_OCCUPATION


@pytest.mark.parametrize("code", ["11", "15", "29", "55"])
def test_specific_codes_round_trip(code):
    label = f"{code} · {MAJOR_GROUP_NAMES[code]}"
    assert parse_assignment(label) == code
