"""D-33: the two derivations of "needs review" must agree.

Before D-33 the header counted `is_uncertain` plus the corrections dict, read
off a SECOND cached copy of network_nodes.csv, while every other surface
counted `display_state` on the composed display frame. Two routes, one number.
They agreed by construction rather than by contract, and nothing would have
said so on the day one of them changed — which is the D-15 shape, and the
reason Gate D asks about derivation rather than agreement.

This file is the contract. It runs unchanged on both sides of D-33: at
ad7ef5a both routes are live, and after the collapse `review_counts()` remains
as the pure baseline function while `coverage_counts()` serves every surface.
Passing on both sides is what makes D-33 a proven refactor rather than an
assumed one.

Deliberately NOT parameterised on Streamlit, disk, or the sidecar: both
functions under test are pure, so this is a real unit test rather than a
screenshot.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.dashboard.loader import compose
from src.dashboard.state import NOT_OCCUPATION, review_counts
from src.dashboard.summaries import coverage_counts

# Real SOC major-group codes: validate_correction() rejects anything else.
CODE_A, CODE_B, CODE_C = "13", "15", "17"

N_UNCERTAIN = 4
N_CERTAIN = 6


def _base(n_uncertain: int = N_UNCERTAIN, n_certain: int = N_CERTAIN) -> pd.DataFrame:
    """A base table in the shape apply_corrections() expects.

    person_index 0..n_uncertain-1 are uncertain; the rest are classified.
    """
    total = n_uncertain + n_certain
    return pd.DataFrame({
        "person_index": list(range(total)),
        "is_uncertain": [True] * n_uncertain + [False] * n_certain,
        "soc_major": ["99"] * n_uncertain + [CODE_A] * n_certain,
        "soc_major_name": ["Needs review"] * n_uncertain + ["Business"] * n_certain,
    })


CASES: dict[str, dict[int, str]] = {
    "no corrections": {},
    "one uncertain resolved": {0: CODE_A},
    "uncertain marked not an occupation": {1: NOT_OCCUPATION},
    "mixed group and not-an-occupation": {0: CODE_A, 1: NOT_OCCUPATION},
    # review_counts() only decrements for indices that were uncertain in the
    # BASE table; _row_state() reclassifies any corrected row. The two agree
    # here only because a already-classified row was never in needs_review.
    "already-classified node corrected": {N_UNCERTAIN + 1: CODE_B},
    # "a session can outlive a data reload": apply_corrections ignores an
    # unknown person_index, and review_counts' set-membership test misses it.
    "correction for someone not in the table": {9_999: CODE_C},
    "every uncertain resolved": {
        0: CODE_A, 1: CODE_B, 2: CODE_C, 3: NOT_OCCUPATION,
    },
}


@pytest.mark.parametrize("corrections", CASES.values(), ids=list(CASES))
def test_both_derivations_of_needs_review_agree(corrections: dict[int, str]) -> None:
    base = _base()
    df = compose(base, corrections, None)

    from_display = coverage_counts(df).needs_review   # every surface but the header
    from_base, _ = review_counts(base, corrections)   # the header's old route

    assert from_display == from_base


@pytest.mark.parametrize("corrections", CASES.values(), ids=list(CASES))
def test_the_three_display_states_close_on_the_population(
    corrections: dict[int, str],
) -> None:
    """classified + needs_review + not_occupation == total, at every step.

    Gate D's arithmetic criterion. A surface can be live-derived and still wrong
    if the buckets do not partition the table.
    """
    counts = coverage_counts(compose(_base(), corrections, None))
    assert (
        counts.classified + counts.needs_review + counts.not_occupation
        == counts.total
        == N_UNCERTAIN + N_CERTAIN
    )


def test_the_baseline_is_fixed_across_corrections() -> None:
    """M is the session's starting backlog and must never move.

    The header renders "N of M"; an M that drifted would make the counter
    describe a shrinking denominator as progress.
    """
    base = _base()
    assert {review_counts(base, c)[1] for c in CASES.values()} == {N_UNCERTAIN}


def test_compose_does_not_mutate_the_base_table() -> None:
    """The header's M reads `base` AFTER the loader has composed from it.

    If compose() mutated in place, M would be computed from a frame that
    already had corrections applied and the backlog would silently shrink.
    """
    base = _base()
    before = base["is_uncertain"].tolist()
    compose(base, {0: CODE_A, 1: NOT_OCCUPATION}, None)
    assert base["is_uncertain"].tolist() == before
