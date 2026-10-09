"""
tests/test_search.py — unit tests for src/dashboard/search.filter_nodes.

Covers the P2.4 DoD cases: multi-field match, no-match empty state, empty-query
returns-all, case-insensitivity, NaN safety, and missing-field tolerance. Runs
under plain pytest with no Streamlit runtime:

    python -m pytest tests/test_search.py -v
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.dashboard.search import filter_caption, filter_nodes


@pytest.fixture
def df() -> pd.DataFrame:
    return pd.DataFrame({
        "person_index": [0, 1, 2, 3],
        "name": ["Aisha Khan", "Tom Smith", "Priya Patel", "James Jones"],
        "role": ["Data Scientist", "Investment Analyst", "UX Designer", "Data Analyst"],
        "soc_major_name": [
            "Computer and Mathematical",
            "Business and Financial Operations",
            "Arts, Design, Entertainment, Sports, and Media",
            "Computer and Mathematical",
        ],
    })


def test_empty_query_returns_all(df):
    assert len(filter_nodes(df, "")) == len(df)


def test_whitespace_query_returns_all(df):
    assert len(filter_nodes(df, "   ")) == len(df)


def test_name_substring_match(df):
    assert list(filter_nodes(df, "aisha")["person_index"]) == [0]


def test_role_substring_match(df):
    assert set(filter_nodes(df, "analyst")["person_index"]) == {1, 3}


def test_soc_group_match(df):
    assert set(filter_nodes(df, "computer")["person_index"]) == {0, 3}


def test_case_insensitive(df):
    assert set(filter_nodes(df, "DATA")["person_index"]) == {0, 3}


def test_no_match_returns_empty(df):
    assert filter_nodes(df, "zzz nonsense").empty


def test_or_across_fields(df):
    # "design" hits role (row 2); "financial" hits soc_major_name (row 1).
    assert set(filter_nodes(df, "design")["person_index"]) == {2}
    assert set(filter_nodes(df, "financial")["person_index"]) == {1}


def test_nan_field_does_not_crash(df):
    df2 = df.copy()
    df2.loc[2, "soc_major_name"] = None
    # still matches on role, and the NaN cell neither crashes nor matches
    assert set(filter_nodes(df2, "designer")["person_index"]) == {2}


def test_missing_optional_field_skipped(df):
    slim = df.drop(columns=["soc_major_name"])
    assert set(filter_nodes(slim, "analyst")["person_index"]) == {1, 3}


def test_order_preserved(df):
    assert list(filter_nodes(df, "data")["person_index"]) == [0, 3]


def test_at_rest_states_the_population():
    assert filter_caption(442, 442, filtering=False) == "442 people"


def test_filtered_shows_both():
    assert filter_caption(37, 442, filtering=True) == "37 of 442 shown"


def test_a_filter_matching_everyone_still_says_so():
    # Deliberate: the filter is active, and "442 of 442" is how the user knows.
    # Not the same case as at-rest, which is why the guard is `filtering`.
    assert filter_caption(442, 442, filtering=True) == "442 of 442 shown"


def test_empty_result():
    assert filter_caption(0, 442, filtering=True) == "0 of 442 shown"