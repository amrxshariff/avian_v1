"""
tests/test_state.py — unit tests for the P2.1 correction-overlay accessor.

Covers the pure core only (no Streamlit runtime needed). Each test pins one of
the forks from the design walkthrough, so a regression in the load-bearing
accessor fails here rather than three days later in P2.7.

Run from the repo root:
    python -m pytest tests/test_state.py -v
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.dashboard.state import (
    ALL_STATES,
    NOT_CLASSIFIED,
    NOT_CLASSIFIED_NAME,
    NOT_OCCUPATION,
    NOT_OCCUPATION_NAME,
    NEEDS_REVIEW_NAME,
    STATUS_ABSTAINED,
    STATUS_ASSIGNED,
    STATUS_COLUMN,
    STATUS_NOT_CLASSIFIED,
    UNREVIEWED_CODE,
    STATE_CLASSIFIED,
    STATE_NEEDS_REVIEW,
    STATE_NOT_CLASSIFIED,
    STATE_NOT_OCCUPATION,
    apply_corrections,
    review_counts,
    validate_correction,
)


@pytest.fixture
def base_df() -> pd.DataFrame:
    """A tiny stand-in for network_nodes.csv: 2 classified, 3 uncertain.

    Mirrors the real schema's relevant columns. soc_major deliberately parsed as
    a mix (int-like for classified, the "99" sentinel string for uncertain) to
    prove the accessor's str-coercion holds.
    """
    return pd.DataFrame(
        {
            "person_index": [0, 1, 2, 3, 4],
            "name": ["A", "B", "C", "D", "E"],
            "role": [
                "Financial Accountant", "Data Scientist",
                "Medical reviewer", "Site Experience & End User", "Member",
            ],
            "soc_major": [13, 15, 99, 99, 99],
            "soc_major_name": [
                "Business and Financial Operations", "Computer and Mathematical",
                "Needs review", "Needs review", "Needs review",
            ],
            "is_uncertain": [False, False, True, True, True],
        }
    )


def test_no_corrections_preserves_base(base_df):
    out = apply_corrections(base_df, {})
    # Classified rows keep their group; uncertain rows become needs_review.
    assert list(out["display_state"]) == [
        STATE_CLASSIFIED, STATE_CLASSIFIED,
        STATE_NEEDS_REVIEW, STATE_NEEDS_REVIEW, STATE_NEEDS_REVIEW,
    ]
    assert list(out["is_uncertain"]) == [False, False, True, True, True]
    assert out.loc[0, "soc_major"] == "13"  # coerced to str
    assert (out.loc[out["display_state"] == STATE_NEEDS_REVIEW,
                    "soc_major_name"] == NEEDS_REVIEW_NAME).all()


def test_assign_real_group_reclassifies_and_recolours(base_df):
    # User assigns person 2 (uncertain "Medical reviewer") to Healthcare (29).
    out = apply_corrections(base_df, {2: "29"})
    row = out.loc[out["person_index"] == 2].iloc[0]
    assert row["display_state"] == STATE_CLASSIFIED
    assert row["soc_major"] == "29"
    assert row["soc_major_name"] == "Healthcare Practitioners and Technical"
    assert row["is_uncertain"] is False or row["is_uncertain"] == False  # recoloured


def test_mark_not_occupation_is_distinct_third_state(base_df):
    # User marks person 4 ("Member") as not an occupation.
    out = apply_corrections(base_df, {4: NOT_OCCUPATION})
    row = out.loc[out["person_index"] == 4].iloc[0]
    assert row["display_state"] == STATE_NOT_OCCUPATION
    assert row["soc_major"] == NOT_OCCUPATION
    assert row["soc_major_name"] == NOT_OCCUPATION_NAME
    # Resolved: no longer needs review, but NOT given a group colour.
    assert bool(row["is_uncertain"]) is False


def test_counter_decrements_for_both_correction_kinds(base_df):
    # M is fixed at 3 (three uncertain in the base table).
    assert review_counts(base_df, {}) == (3, 3)
    # A real-group assignment resolves one.
    assert review_counts(base_df, {2: "29"}) == (2, 3)
    # not_occupation also resolves one.
    assert review_counts(base_df, {2: "29", 4: NOT_OCCUPATION}) == (1, 3)


def test_correction_on_classified_node_does_not_touch_backlog(base_df):
    # Overriding an already-classified node (person 0) must not change N or M.
    assert review_counts(base_df, {0: "11"}) == (3, 3)
    out = apply_corrections(base_df, {0: "11"})
    row = out.loc[out["person_index"] == 0].iloc[0]
    assert row["soc_major"] == "11"          # override applied
    assert row["display_state"] == STATE_CLASSIFIED


def test_all_uncertain_resolved_empties_queue(base_df):
    corrections = {2: "29", 3: "15", 4: NOT_OCCUPATION}
    assert review_counts(base_df, corrections) == (0, 3)
    out = apply_corrections(base_df, corrections)
    assert not out["is_uncertain"].any()


def test_invalid_correction_value_raises(base_df):
    with pytest.raises(ValueError):
        validate_correction("not-a-code")
    with pytest.raises(ValueError):
        apply_corrections(base_df, {2: "999"})


def test_unknown_person_index_is_ignored(base_df):
    # A correction for a person_index not in the table (e.g. session outlived a
    # data reload) must not crash and must not invent a row.
    out = apply_corrections(base_df, {99: "13"})
    assert len(out) == len(base_df)
    assert review_counts(base_df, {99: "13"}) == (3, 3)


def test_base_frame_is_not_mutated(base_df):
    before = base_df.copy(deep=True)
    _ = apply_corrections(base_df, {2: "29", 4: NOT_OCCUPATION})
    pd.testing.assert_frame_equal(base_df, before)


def test_needs_review_agrees_with_summaries_coverage_counts(base_df):
    """D-33: app.py derives its header's N from review_counts(base, corrections)
    and every other on-screen count from coverage_counts(display_table). They
    read different columns of different frames (is_uncertain vs display_state,
    base_df vs the corrected df) to reach "how many still need review" — this
    is the proof they agree, not just the reasoning that they should. Traced
    by hand for each sequence below, including a NOT_OCCUPATION resolution and
    a no-op correction on an already-classified node.
    """
    from src.dashboard.summaries import coverage_counts

    sequences = [
        {},
        {2: "29"},
        {2: "29", 3: "15"},
        {2: "29", 3: "15", 4: NOT_OCCUPATION},
        {0: "11"},                              # override on an already-classified node
        {2: "29", 4: NOT_OCCUPATION, 0: "11"},  # mixed: resolve, not_occupation, no-op
    ]
    for corrections in sequences:
        df = apply_corrections(base_df, corrections)
        n_state, _ = review_counts(base_df, corrections)
        n_summaries = coverage_counts(df).needs_review
        assert n_state == n_summaries, corrections
# --- P2.9b: the fourth state -------------------------------------------------


@pytest.fixture
def status_df(base_df) -> pd.DataFrame:
    """base_df plus the P2.9b column: rows 3 and 4 were never answered.

    is_uncertain is False on both, which is what a P2.9b build writes: a call
    that failed is not an abstention (D-42).
    """
    df = base_df.copy()
    df[STATUS_COLUMN] = [
        STATUS_ASSIGNED, STATUS_ASSIGNED, STATUS_ABSTAINED,
        STATUS_NOT_CLASSIFIED, STATUS_NOT_CLASSIFIED,
    ]
    df["is_uncertain"] = [False, False, True, False, False]
    return df


def test_all_states_lists_every_display_state():
    """The exhaustiveness list slice 2 branches over. Four, no duplicates."""
    assert set(ALL_STATES) == {
        STATE_CLASSIFIED, STATE_NEEDS_REVIEW,
        STATE_NOT_OCCUPATION, STATE_NOT_CLASSIFIED,
    }
    assert len(ALL_STATES) == len(set(ALL_STATES)) == 4


def test_not_classified_is_its_own_state(status_df):
    out = apply_corrections(status_df, {})
    assert list(out["display_state"]) == [
        STATE_CLASSIFIED, STATE_CLASSIFIED, STATE_NEEDS_REVIEW,
        STATE_NOT_CLASSIFIED, STATE_NOT_CLASSIFIED,
    ]
    failed = out[out["display_state"] == STATE_NOT_CLASSIFIED]
    assert set(failed["soc_major"]) == {NOT_CLASSIFIED}
    assert set(failed["soc_major_name"]) == {NOT_CLASSIFIED_NAME}


def test_not_classified_never_reads_as_needs_review(status_df):
    """D-42 in one assertion: a failed call is not an abstention.

    Not in is_uncertain, not in the "99" code, not in the review backlog.
    """
    out = apply_corrections(status_df, {})
    failed = out["display_state"] == STATE_NOT_CLASSIFIED

    assert not out.loc[failed, "is_uncertain"].any()
    assert UNREVIEWED_CODE not in set(out.loc[failed, "soc_major"])
    assert NEEDS_REVIEW_NAME not in set(out.loc[failed, "soc_major_name"])
    assert review_counts(status_df, {}) == (1, 1)   # row 2 only


def test_a_correction_outranks_a_failed_call(status_df):
    """The user's own verdict shows at once, without waiting for a retry."""
    out = apply_corrections(status_df, {3: "15", 4: NOT_OCCUPATION})
    assert out.loc[3, "display_state"] == STATE_CLASSIFIED
    assert out.loc[3, "soc_major"] == "15"
    assert out.loc[4, "display_state"] == STATE_NOT_OCCUPATION
    assert out.loc[4, "soc_major_name"] == NOT_OCCUPATION_NAME
    # The backlog is untouched: neither was ever in it.
    assert review_counts(status_df, {3: "15", 4: NOT_OCCUPATION}) == (1, 1)


def test_a_table_without_the_column_behaves_exactly_as_before(base_df):
    """The compatibility branch restates is_uncertain, it does not guess.

    Every table built before P2.9b — including the tracked demo — lacks the
    column, and for those the two outputs must be identical.
    """
    expected = base_df.copy()
    expected[STATUS_COLUMN] = [
        STATUS_ASSIGNED if not u else STATUS_ABSTAINED
        for u in base_df["is_uncertain"]
    ]
    for corrections in ({}, {2: "29"}, {0: "11", 4: NOT_OCCUPATION}):
        without = apply_corrections(base_df, corrections)
        with_col = apply_corrections(expected, corrections).drop(columns=[STATUS_COLUMN])
        pd.testing.assert_frame_equal(without, with_col)


def test_an_unrecognised_status_raises(base_df):
    """D-54: never render a state nobody recognises as one somebody does."""
    df = base_df.copy()
    df[STATUS_COLUMN] = [STATUS_ASSIGNED] * 4 + ["deferred"]
    with pytest.raises(ValueError, match="deferred"):
        apply_corrections(df, {})


def test_not_classified_and_uncertain_together_raise(base_df):
    """Two screens would disagree: the backlog counts it, the table does not."""
    df = base_df.copy()
    df[STATUS_COLUMN] = [STATUS_ASSIGNED, STATUS_ASSIGNED, STATUS_ABSTAINED,
                         STATUS_NOT_CLASSIFIED, STATUS_ABSTAINED]
    # row 3 keeps is_uncertain True from the fixture, contradicting its status
    with pytest.raises(ValueError, match="is not an abstention"):
        apply_corrections(df, {})


def test_retry_that_yields_abstentions_grows_the_backlog(status_df):
    """The one intended way M moves mid-session (see review_counts)."""
    before = review_counts(status_df, {})
    retried = status_df.copy()
    retried[STATUS_COLUMN] = [
        STATUS_ASSIGNED, STATUS_ASSIGNED, STATUS_ABSTAINED,
        STATUS_ABSTAINED, STATUS_ABSTAINED,
    ]
    retried["is_uncertain"] = [False, False, True, True, True]
    after = review_counts(retried, {})
    assert before == (1, 1)
    assert after == (3, 3)
