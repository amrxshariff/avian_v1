"""
tests/test_demo.py — the shipped demo contains no real person.

The demo used to be the real network table. It is now built from
src/synthetic.py, and this test is what keeps it that way: if anyone ever
regenerates the demo from a real export, every name in it will appear in a file
that no real name appears in, and this fails.

Skips when the demo has not been built yet (tools/build_demo.py).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.dashboard.loader import DEMO_NODES_CSV
from src.dashboard.provenance import load_demo_provenance
from src.dashboard.state import ALL_STATES, apply_corrections

SYNTHETIC_CSV = Path("data/synthetic/Connections.csv")

pytestmark = pytest.mark.skipif(
    not DEMO_NODES_CSV.exists(),
    reason="demo not built — run python -m tools.build_demo",
)


@pytest.fixture(scope="module")
def demo() -> pd.DataFrame:
    return pd.read_csv(DEMO_NODES_CSV)


def test_every_name_comes_from_the_synthetic_export(demo):
    if not SYNTHETIC_CSV.exists():
        pytest.skip("synthetic export not on disk")

    raw = pd.read_csv(SYNTHETIC_CSV, skiprows=3, dtype=str).fillna("")
    synthetic_names = {
        f"{f.strip()} {l.strip()}".strip()
        for f, l in zip(raw["First Name"], raw["Last Name"])
    }
    assert set(demo["name"]) <= synthetic_names


def test_the_demo_is_classified(demo):
    """A demo of an unclassified network showcases nothing."""
    shown = apply_corrections(demo, {})
    assert (shown["display_state"] == "classified").mean() > 0.5
    assert (shown["display_state"] == "not_classified").sum() == 0


def test_the_demo_carries_its_own_coordinates(demo):
    coords = ["umap_3d_x", "umap_3d_y", "umap_3d_z"]
    assert not demo[coords].isna().any().any()


def test_the_demo_uses_only_known_states(demo):
    assert set(apply_corrections(demo, {})["display_state"]) <= set(ALL_STATES)


def test_the_recorded_headcount_is_the_table_the_dashboard_counts(demo):
    """D-58: the welcome screen reads its figure from provenance.json, the
    dashboard header counts rows in the table. build_demo writes both in one
    run; this is what stops them drifting into two figures for one network."""
    assert load_demo_provenance()["people"] == len(demo)
