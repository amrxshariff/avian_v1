"""
tests/test_canvas.py — unit tests for src/dashboard/canvas.build_figure.

Verifies trace composition without a Streamlit runtime: the plain view is one
node trace; a search match set splits into 'matches' + 'other'; a highlight adds
a 'selected' ring; an empty match set is treated as no filter.

    python -m pytest tests/test_canvas.py -v
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.dashboard.canvas import build_figure, FADED_OPACITY, FULL_OPACITY, SOC_COLOURS
from src.dashboard.state import STATE_CLASSIFIED


@pytest.fixture
def df() -> pd.DataFrame:
    return pd.DataFrame({
        "person_index": [0, 1, 2, 3],
        "name": ["A", "B", "C", "D"],
        "role": ["r0", "r1", "r2", "r3"],
        "soc_major": ["15", "13", "15", "27"],
        "soc_major_name": ["Computer and Mathematical",
                           "Business and Financial Operations",
                           "Computer and Mathematical",
                           "Arts, Design, Entertainment, Sports, and Media"],
        # Four classified people, coloured by soc_major. This used to hold SOC
        # CODES, which is not a display_state at all; the old _point_colour
        # treated anything unrecognised as classified, so the fixture passed
        # while describing a table that could never exist (D-54).
        "display_state": [STATE_CLASSIFIED] * 4,
        "umap_3d_x": [0.1, 0.2, 0.3, 0.4],
        "umap_3d_y": [0.1, 0.2, 0.3, 0.4],
        "umap_3d_z": [0.1, 0.2, 0.3, 0.4],
    })


def _names(fig):
    return [t.name for t in fig.data]


def test_plain_view_single_node_trace(df):
    fig = build_figure(df)
    assert "network" in _names(fig)
    assert "matches" not in _names(fig) and "other" not in _names(fig)


def test_match_set_splits_into_two_traces(df):
    fig = build_figure(df, match_indices={0, 2})
    assert "matches" in _names(fig) and "other" in _names(fig)
    matched = next(t for t in fig.data if t.name == "matches")
    other = next(t for t in fig.data if t.name == "other")
    assert len(matched.x) == 2
    assert len(other.x) == 2


def test_highlight_adds_selected_ring(df):
    fig = build_figure(df, highlight_index=1)
    assert "selected" in _names(fig)


def test_highlight_coexists_with_match_set(df):
    fig = build_figure(df, highlight_index=0, match_indices={0, 2})
    assert {"matches", "other", "selected"} <= set(_names(fig))


def test_empty_match_set_fades_everything(df):
    """An empty set means "a filter is active and nothing satisfies it".

    Previously this rendered the full network unfaded, so a zero-result search
    said "No matches" in the sidebar while the canvas stayed fully lit. Empty is
    now a filtered state: one faded trace, no match trace. The distinction only
    became reachable when group selection and search began to intersect, where
    an empty result is a normal outcome rather than a dead end.
    """
    fig = build_figure(df, match_indices=set())
    assert len(fig.data) == 1
    assert fig.data[0].name == "other"
    assert fig.data[0].marker.opacity == FADED_OPACITY
    assert fig.data[0].hoverinfo == "skip"


def test_none_match_set_is_no_filter(df):
    """None is the unfiltered sentinel — the contract the old test meant to pin."""
    fig = build_figure(df, match_indices=None)
    assert len(fig.data) == 1
    assert fig.data[0].name == "network"
    assert fig.data[0].marker.opacity == FULL_OPACITY


def test_missing_column_raises(df):
    with pytest.raises(KeyError):
        build_figure(df.drop(columns=["umap_3d_z"]))


def test_selected_groups_are_labelled(df):
    fig = build_figure(df, label_groups={"15"})
    labels = [a["text"] for a in fig.layout.scene.annotations]
    assert any("Computer" in t for t in labels)


def test_group_labels_come_from_the_full_frame_not_the_match_set(df):
    """DoD-2: a group stays labelled while a search narrows what is lit inside
    it. The centroid must not drift to the match set's centre."""
    everyone = build_figure(df, label_groups={"15"})
    narrowed = build_figure(df, match_indices={1}, label_groups={"15"})
    assert (everyone.layout.scene.annotations[0]["x"]
            == narrowed.layout.scene.annotations[0]["x"])


def test_group_nobody_holds_is_skipped_not_errored(df):
    """All 23 groups are always selectable, but your network holds 18. Choosing
    one of the other five must be a no-op, never a crash."""
    fig = build_figure(df, label_groups={"45"})   # Farming, Fishing, and Forestry
    assert fig.layout.scene.annotations == ()


def test_group_label_colour_matches_its_nodes(df):
    """A label in one hue over a cluster in another is worse than no label."""
    fig = build_figure(df, label_groups={"15"})
    assert fig.layout.scene.annotations[0]["font"]["color"] == SOC_COLOURS["15"]