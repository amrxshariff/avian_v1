"""
src/dashboard/loader.py — Phase 2, P2.8b: the shared display-table loader.

DoD: one function is the only path to the frame the dashboard reads. app.py and
every tools/ script import it rather than assembling their own.

Why this exists
---------------
The display table is an ASSEMBLY, not a file:

    base CSV -> 3D sidecar merge -> corrections overlay -> notes overlay

That assembly lived inside app.py._display_with_3d(), where nothing else could
reach it, so every other caller reimplemented some subset. The drift was
predicted when DoD-9 was signed off and then arrived exactly as described:
check_chat_grounding.py composed corrections but NOT notes, so its "no name
reaches the payload" check ran against a frame with no notes in it while the
live app sent them. Not a wrong answer, but a weaker check than it looked.

The failure mode this guards is worse than a weak check. A short or partial
sidecar produces NaN coordinates, and the canvas renders a subset of the network
with no visible error — 430 people in, 400 dots out, and the cloud just looks
slightly sparser. merge_coordinates() raises instead.

Two layers, as in state.py and summaries.py:

  * PURE CORE — merge_coordinates(), compose(). Frames and dicts in, frame out.
    No Streamlit, no disk. The notes overlay is INJECTED as a callable rather
    than imported, so the core never needs a session and notes stay a separate
    overlay (the P2.2b decision that kept apply_corrections and its tests untouched).

  * GLUE — resolve_sidecar(), load_display_table(). Reads the CSVs, pulls
    corrections and notes from session state, delegates to the core.

Corrections and notes are read LIVE on every call, never captured at first call.
That already mattered for P2.1; at P2.8c it becomes load-bearing for a second
reason — restore writes into those same session dicts, so a restored file
appears on the next rerun with this module knowing nothing about files
(decision D5).

Version A holds: nothing here writes anything anywhere.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import pandas as pd

from src.dashboard.state import apply_corrections

# --- constants ---------------------------------------------------------------

NODES_CSV = Path("data/graph/network_nodes.csv")

# The shipped demo: synthetic people, classified once by tools/build_demo.py.
# It carries its own 3D coordinates, so it needs no sidecar — the build writes
# them into the table rather than beside it.
DEMO_NODES_CSV = Path("data/demo/network_nodes.csv")

# The sidecar has moved once already (data/graph -> data/cache) and cost a
# debugging session. It is resolved in ONE place now, and the resolution is
# reported rather than assumed.
SIDECAR_CANDIDATES: tuple[Path, ...] = (
    Path("data/cache/projected_3d.csv"),
    Path("data/graph/projected_3d.csv"),
)

COORD_COLUMNS: tuple[str, ...] = ("umap_3d_x", "umap_3d_y", "umap_3d_z")
INDEX_COLUMN = "person_index"


class SidecarMismatch(RuntimeError):
    """The sidecar does not correspond one-to-one with the node table.

    Fails loud by design (DoD criterion 3): the alternative is a canvas that
    renders fewer people than the network contains, with nothing on screen to
    say so.
    """


class SidecarMissing(FileNotFoundError):
    """No 3D sidecar found at any known path."""


# --- pure core ---------------------------------------------------------------


def merge_coordinates(base: pd.DataFrame, coords: pd.DataFrame) -> pd.DataFrame:
    """Join the 3D sidecar onto the node table, or raise.

    validate="one_to_one" catches a duplicated person_index. It does NOT catch a
    sidecar that is simply short — that yields NaN coordinates and a quietly
    sparser cloud — so the row count and the NaN count are checked explicitly.
    """
    missing = [c for c in (INDEX_COLUMN, *COORD_COLUMNS) if c not in coords.columns]
    if missing:
        raise SidecarMismatch(
            f"sidecar is missing {missing}; it has {list(coords.columns)}"
        )

    before = len(base)
    out = base.merge(coords, on=INDEX_COLUMN, how="left", validate="one_to_one")
    gaps = int(out[list(COORD_COLUMNS)].isna().any(axis=1).sum())

    if len(out) != before or gaps:
        raise SidecarMismatch(
            f"{before} rows in, {len(out)} out, {gaps} without coordinates. "
            "Nodes without coordinates do not render, and a silently sparser "
            "canvas is the failure this guard exists to prevent."
        )
    return out


def compose(
    base: pd.DataFrame,
    corrections: dict[int, str],
    notes_overlay: Callable[[pd.DataFrame], pd.DataFrame] | None = None,
) -> pd.DataFrame:
    """Apply the session overlays, in order: corrections, then notes.

    `notes_overlay` is injected rather than imported so the core stays pure and
    notes remain a SEPARATE overlay. Folding notes into apply_corrections would
    put a second concern inside a function whose tests (tests/test_state.py)
    are built around one.
    """
    out = apply_corrections(base, corrections)
    if notes_overlay is not None:
        out = notes_overlay(out)
    return out


# --- glue --------------------------------------------------------------------


def resolve_sidecar(path: Path | str | None = None) -> Path:
    """First existing sidecar path, or raise listing where it looked."""
    if path is not None:
        candidate = Path(path)
        if not candidate.exists():
            raise SidecarMissing(f"no 3D sidecar at {candidate}")
        return candidate

    for candidate in SIDECAR_CANDIDATES:
        if candidate.exists():
            return candidate
    raise SidecarMissing(
        "no 3D sidecar found. Looked in: "
        + ", ".join(str(c) for c in SIDECAR_CANDIDATES)
    )


def _read_csv_cached(path: str) -> pd.DataFrame:
    """Cached read inside a Streamlit runtime, plain read outside one.

    The base table and sidecar are static for a run, so caching executes once.
    Outside a runtime — every tools/ harness — @st.cache_data still works but
    emits a warning per call, and noise ahead of a checker's output is noise
    that will eventually hide a real failure. The COMPOSED frame is never
    cached either way: caching a derived frame is what produced the stale-cache
    debugging sessions.
    """
    try:
        from streamlit.runtime import exists as _runtime_exists
    except ImportError:
        return pd.read_csv(path)

    if not _runtime_exists():
        return pd.read_csv(path)

    import streamlit as st

    @st.cache_data
    def _read(p: str) -> pd.DataFrame:
        return pd.read_csv(p)

    return _read(path)


def load_base_frame(path: Path | str = NODES_CSV) -> pd.DataFrame:
    """The canonical node table, read once and cached. No corrections, no
    coordinates — this is the BASELINE review_counts() measures against.

    D-33: the only other reader of NODES_CSV was state.load_base_table(), a
    second cached frame from the same file. get_review_counts() defaulted to
    it and ignored the df assembled one line earlier in app.py, which agrees
    today only because both routes read the same demo file. They diverge the
    moment a real upload's frame differs from what is on disk, and the header
    would then report a stranger's counts. One reader closes that gap.
    """
    base = _read_csv_cached(str(path))
    base["soc_major"] = base["soc_major"].astype(str)
    return base


def load_display_table(
    frame: pd.DataFrame | None = None,
    *,
    path: Path | str = NODES_CSV,
    sidecar: Path | str | None = None,
    with_coords: bool = True,
    corrections: dict[int, str] | None = None,
    notes_overlay: Callable[[pd.DataFrame], pd.DataFrame] | None = None,
) -> pd.DataFrame:
    """The one frame the dashboard reads. Nothing else assembles it.

    `frame` is a FULLY ASSEMBLED node table — already classified, embedded and
    projected. This loader validates and composes; it does not build. At P2.9
    the upload flow hands over the output of its own pipeline, not a raw
    LinkedIn export: a raw export arrives without coordinates and the merge
    guard fires loudly, which is the correct outcome rather than a bug.

    `with_coords=False` gives a caller the same overlay composition without the
    sidecar dependency — for checkers and diagnostics that need the live table
    but never touch the canvas. It is an opt-out from the JOIN, never from the
    overlays: a caller that composed overlays differently is precisely the drift
    this module exists to end.

    `corrections` and `notes_overlay` are injectable for tests; left as None
    they are pulled LIVE from session state on every call, never captured.
    """
    base = frame if frame is not None else _read_csv_cached(str(path))

    if with_coords and not all(c in base.columns for c in COORD_COLUMNS):
        coords = pd.read_csv(resolve_sidecar(sidecar))
        base = merge_coordinates(base, coords)

    if corrections is None:
        from src.dashboard.state import get_corrections

        corrections = get_corrections()

    if notes_overlay is None:
        from src.dashboard.notes import apply_notes_from_session

        notes_overlay = apply_notes_from_session

    return compose(base, corrections, notes_overlay)