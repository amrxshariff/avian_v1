"""
tests/test_people_list.py — P2.8d review queue and shared people list.

No Streamlit, no disk. Only the pure core is tested; the glue is widgets.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.dashboard.people_list import (
    PAGE_SIZE,
    PICKER_PLACEHOLDER,
    option_to_code,
    paginate,
    person_label,
    picker_options,
    queue_frame,
    review_progress,
)
from src.dashboard.state import NOT_OCCUPATION, NOT_OCCUPATION_NAME


def make_df(n_review: int = 5, n_classified: int = 3) -> pd.DataFrame:
    rows = []
    index = 0
    for _ in range(n_review):
        rows.append({"person_index": index, "name": f"R{index}", "role": "Analyst",
                     "soc_major_name": "Needs review", "display_state": "needs_review"})
        index += 1
    for _ in range(n_classified):
        rows.append({"person_index": index, "name": f"C{index}", "role": "Engineer",
                     "soc_major_name": "Architecture and Engineering",
                     "display_state": "classified"})
        index += 1
    return pd.DataFrame(rows)


# --- pagination --------------------------------------------------------------


def test_page_slices_and_reports_position():
    df = make_df(n_review=25, n_classified=0)
    page = paginate(df, 2)
    assert len(page.rows) == PAGE_SIZE
    assert (page.first, page.last, page.total_pages) == (11, 20, 3)


def test_last_page_is_short_not_padded():
    page = paginate(make_df(n_review=25, n_classified=0), 3)
    assert len(page.rows) == 5
    assert (page.first, page.last) == (21, 25)


@pytest.mark.parametrize("requested", [0, -4, 99])
def test_page_number_is_clamped(requested):
    """The list shrinks as people are reviewed; a stale page number must land
    somewhere real rather than on an empty page."""
    page = paginate(make_df(n_review=12, n_classified=0), requested)
    assert 1 <= page.number <= page.total_pages
    assert not page.rows.empty


def test_empty_frame_gives_one_empty_page():
    page = paginate(make_df(0, 0))
    assert page.rows.empty and page.total_pages == 1 and page.first == 0


# --- queue -------------------------------------------------------------------


def test_queue_holds_only_needs_review():
    queue = queue_frame(make_df())
    assert len(queue) == 5
    assert set(queue["display_state"]) == {"needs_review"}


def test_skipped_people_leave_the_view_but_not_the_count():
    """A skip is 'not now', never a verdict."""
    df = make_df()
    queue = queue_frame(df, skipped={0, 1})
    assert len(queue) == 3
    # still unreviewed everywhere else — the progress line is unmoved. D-32:
    # remaining == base_needing_review suppresses the "of 5" restatement.
    assert "5 need review." == review_progress(df, 5)


def test_a_correction_removes_someone_from_the_queue():
    """Derived from display_state, so a correction made anywhere shrinks it —
    including one restored from a P2.8c save file."""
    df = make_df()
    df.loc[df["person_index"] == 0, "display_state"] = "classified"
    assert len(queue_frame(df)) == 4


def test_not_an_occupation_also_leaves_the_queue():
    df = make_df()
    df.loc[df["person_index"] == 0, "display_state"] = "not_occupation"
    assert len(queue_frame(df)) == 4


# --- progress ----------------------------------------------------------------


def test_progress_counts_down_in_the_headers_vocabulary():
    df = make_df()
    df.loc[df["person_index"] == 0, "display_state"] = "classified"
    assert review_progress(df, 5) == "4 of 5 still need review."


def test_progress_when_everything_is_reviewed():
    df = make_df(n_review=0, n_classified=3)
    assert review_progress(df, 5) == "All 5 reviewed."


def test_progress_when_nothing_ever_needed_review():
    assert review_progress(make_df(0, 3), 0) == "Nothing needed review in this network."


# --- picker ------------------------------------------------------------------


def test_options_come_from_the_taxonomy_not_the_data():
    """Identical for every user's network — the same rule as the palette."""
    options = picker_options()
    assert options[-1] == NOT_OCCUPATION_NAME
    assert len(options) == 24          # 23 SOC major groups + not-an-occupation
    assert any(o.startswith("15 ·") for o in options)


def test_option_maps_back_to_a_correction_value():
    assert option_to_code("15 · Computer and Mathematical") == "15"
    assert option_to_code(NOT_OCCUPATION_NAME) == NOT_OCCUPATION


@pytest.mark.parametrize("value", [None, "", PICKER_PLACEHOLDER, "99 · nonsense", "abc"])
def test_invalid_options_yield_no_correction(value):
    """A bad option must write nothing rather than write a wrong group."""
    assert option_to_code(value) is None


# --- labels ------------------------------------------------------------------


def test_person_label_handles_a_missing_title():
    assert person_label({"name": "Ada", "role": ""}) == "Ada"
    assert person_label({"name": "Ada", "role": "Analyst"}) == "Ada · Analyst"
    assert person_label({"name": "", "role": ""}) == "(unnamed)"