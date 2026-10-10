"""
tests/test_loader.py — P2.8b shared display-table loader.

No Streamlit, no disk, no session. Frames, dicts and the notes overlay are all
injected, so every branch is reachable under plain pytest.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.dashboard.loader import (
    COORD_COLUMNS,
    SIDECAR_CANDIDATES,
    SidecarMissing,
    SidecarMismatch,
    compose,
    load_display_table,
    merge_coordinates,
    resolve_sidecar,
)


def make_base() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"person_index": 0, "name": "Ada Lovelace", "role": "Data Analyst",
             "soc_major": "15", "soc_major_name": "Computer and Mathematical",
             "is_uncertain": False},
            {"person_index": 1, "name": "Grace Hopper", "role": "Finance Intern",
             "soc_major": "99", "soc_major_name": "Needs review",
             "is_uncertain": True},
            {"person_index": 2, "name": "Alan Turing", "role": "Student Ambassador",
             "soc_major": "99", "soc_major_name": "Needs review",
             "is_uncertain": True},
        ]
    )


def make_coords(indices=(0, 1, 2)) -> pd.DataFrame:
    return pd.DataFrame(
        [{"person_index": i, "umap_3d_x": float(i), "umap_3d_y": float(i),
          "umap_3d_z": float(i)} for i in indices]
    )


def tag_notes(df: pd.DataFrame) -> pd.DataFrame:
    """Stand-in for apply_notes_from_session — a separate overlay, injected."""
    out = df.copy()
    out["note"] = ["kings cross meetup", "", ""]
    return out


# --- merge -------------------------------------------------------------------


def test_merge_preserves_rows_and_adds_coordinates():
    out = merge_coordinates(make_base(), make_coords())
    assert len(out) == 3
    assert all(c in out.columns for c in COORD_COLUMNS)
    assert out["umap_3d_x"].tolist() == [0.0, 1.0, 2.0]


def test_short_sidecar_raises_with_the_counts():
    """The case validate='one_to_one' does NOT catch: a sidecar that is simply
    short yields NaN coordinates and a quietly sparser canvas."""
    with pytest.raises(SidecarMismatch) as exc:
        merge_coordinates(make_base(), make_coords(indices=(0, 1)))
    message = str(exc.value)
    assert "3 rows in" in message and "1 without coordinates" in message


def test_duplicated_person_index_raises():
    coords = pd.concat([make_coords(), make_coords(indices=(1,))], ignore_index=True)
    with pytest.raises(Exception):
        merge_coordinates(make_base(), coords)


def test_sidecar_missing_columns_raises_listing_what_it_has():
    coords = make_coords().rename(columns={"umap_3d_z": "z"})
    with pytest.raises(SidecarMismatch) as exc:
        merge_coordinates(make_base(), coords)
    assert "umap_3d_z" in str(exc.value)


# --- compose -----------------------------------------------------------------


def test_compose_applies_corrections():
    out = compose(make_base(), {1: "13"})
    row = out.loc[out["person_index"] == 1].iloc[0]
    assert row["display_state"] == "classified"
    assert row["soc_major"] == "13"
    assert bool(row["is_uncertain"]) is False


def test_compose_applies_the_notes_overlay():
    out = compose(make_base(), {}, notes_overlay=tag_notes)
    assert out.loc[0, "note"] == "kings cross meetup"


def test_corrections_and_notes_compose_independently():
    """Neither overlay clobbers the other — the P2.2b separation, asserted."""
    out = compose(make_base(), {1: "13"}, notes_overlay=tag_notes)
    assert out.loc[out["person_index"] == 1, "soc_major"].iloc[0] == "13"
    assert out.loc[0, "note"] == "kings cross meetup"


def test_compose_does_not_mutate_the_base_frame():
    base = make_base()
    compose(base, {1: "13"}, notes_overlay=tag_notes)
    assert "display_state" not in base.columns
    assert "note" not in base.columns


# --- load_display_table ------------------------------------------------------


def test_passed_frame_bypasses_disk_entirely():
    """The P2.9 upload seam: a fully assembled frame goes straight through."""
    frame = make_base().merge(make_coords(), on="person_index")
    out = load_display_table(frame, corrections={1: "13"}, notes_overlay=tag_notes)
    assert len(out) == 3
    assert out.loc[out["person_index"] == 1, "display_state"].iloc[0] == "classified"
    assert out.loc[0, "note"] == "kings cross meetup"


def test_with_coords_false_skips_the_join_but_keeps_the_overlays():
    """The flag that would have made check_chat_grounding's frame identical to
    the app's rather than merely similar. An opt-out from the JOIN, never from
    the overlays."""
    out = load_display_table(
        make_base(), with_coords=False, corrections={1: "13"}, notes_overlay=tag_notes
    )
    assert not any(c in out.columns for c in COORD_COLUMNS)
    assert out.loc[out["person_index"] == 1, "display_state"].iloc[0] == "classified"
    assert out.loc[0, "note"] == "kings cross meetup"


def test_a_frame_that_already_has_coordinates_is_not_rejoined():
    frame = make_base().merge(make_coords(), on="person_index")
    out = load_display_table(frame, corrections={}, notes_overlay=tag_notes)
    assert out["umap_3d_x"].tolist() == [0.0, 1.0, 2.0]


def test_frame_without_coordinates_raises_rather_than_rendering_a_subset(tmp_path):
    """A raw export reaching the loader is caught loudly, not silently sparsened."""
    missing = tmp_path / "nope.csv"
    with pytest.raises(SidecarMissing):
        load_display_table(
            make_base(), sidecar=missing, corrections={}, notes_overlay=tag_notes
        )


# --- sidecar resolution ------------------------------------------------------


def test_resolve_sidecar_prefers_cache_then_graph(tmp_path, monkeypatch):
    cache = tmp_path / "cache" / "projected_3d.csv"
    graph = tmp_path / "graph" / "projected_3d.csv"
    for p in (cache, graph):
        p.parent.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr("src.dashboard.loader.SIDECAR_CANDIDATES", (cache, graph))

    graph.write_text("x")
    assert resolve_sidecar() == graph      # falls back when cache is absent

    cache.write_text("x")
    assert resolve_sidecar() == cache      # prefers cache when both exist


def test_resolve_sidecar_reports_where_it_looked(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "src.dashboard.loader.SIDECAR_CANDIDATES", (tmp_path / "a.csv",)
    )
    with pytest.raises(SidecarMissing) as exc:
        resolve_sidecar()
    assert "a.csv" in str(exc.value)


def test_explicit_sidecar_path_that_does_not_exist_raises(tmp_path):
    with pytest.raises(SidecarMissing):
        resolve_sidecar(tmp_path / "absent.csv")


def test_sidecar_candidates_are_the_two_known_paths():
    """The path moved once (data/graph -> data/cache) and cost a session. Pin
    it as Path parts, not str: str(Path(...)) is backslash-separated on Windows
    and forward-slash on Linux, so a string assertion here passes on one
    platform and fails on the other."""
    assert [p.parts for p in SIDECAR_CANDIDATES] == [
        ("data", "cache", "projected_3d.csv"),
        ("data", "graph", "projected_3d.csv"),
    ]