"""tests/test_review_progress.py — D-32: the suppression branch in
src.dashboard.people_list.review_progress.

review_progress is in the pure core and needs no Streamlit, so this is a real
unit test rather than a screenshot.
"""

from __future__ import annotations

import pandas as pd

from src.dashboard.people_list import review_progress
from src.dashboard.state import STATE_NEEDS_REVIEW, STATE_CLASSIFIED


def _frame(n_review: int, n_classified: int) -> pd.DataFrame:
    states = [STATE_NEEDS_REVIEW] * n_review + [STATE_CLASSIFIED] * n_classified
    return pd.DataFrame({"display_state": states})


def test_empty_backlog():
    assert review_progress(_frame(0, 10), 0) == "Nothing needed review in this network."


def test_all_resolved():
    assert review_progress(_frame(0, 10), 8) == "All 8 reviewed."


def test_no_progress_suppresses_the_baseline():
    # D-32: "8 of 8" restates itself and "still" claims progress not made.
    assert review_progress(_frame(8, 2), 8) == "8 need review."


def test_partial_progress_shows_both():
    assert review_progress(_frame(5, 5), 8) == "5 of 8 still need review."
