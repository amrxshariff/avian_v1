"""
src/projection_3d.py — standalone 3-D UMAP projection.

projection.py's 2-D layout (data/cache/projected.csv, data/cache/umap_projection.png)
is committed evidence backing network_preview.png and stays untouched. UMAP at
n_components=3 is a DIFFERENT optimisation, not the 2-D layout with an axis
bolted on — its x and y are not projection.py's x and y, so the two must not be
mixed into one coordinate set. This module runs its own independent
n_components=3 fit (same n_neighbors/min_dist/metric/seed as the 2-D run) and
writes a self-contained (umap_3d_x, umap_3d_y, umap_3d_z) triple, all three
from the same fit.

This is a sidecar, not a second copy of the canonical table: it carries only
person_index (the join key) and the 3-D coordinates. Group membership
(soc_major) already lives in network_nodes.csv — joining back to it is the
caller's job, not this module's.

Run from the repo root:
    python -m src.projection_3d
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.manifold import trustworthiness
from umap import UMAP

from src.config import RANDOM_SEED, UMAP_PARAMS

SEED = RANDOM_SEED

CACHE_DIR = Path("data/cache")
EMBEDDINGS_PATH = CACHE_DIR / "embeddings.npy"
CLUSTERED_PATH = CACHE_DIR / "clustered.csv"

PROJECTED_3D_PATH = CACHE_DIR / "projected_3d.csv"   # gitignored, like projected.csv

METRIC = "cosine"
TRUST_K = 5
PERSON_INDEX_COL = "person_index"

# Single source in src/config.py, shared with projection.py (D-29); only
# n_components differs between the two fits.
FINAL_PARAMS = UMAP_PARAMS


def load_inputs() -> tuple[np.ndarray, pd.Series]:
    """Load cached embeddings and clustered.csv's person_index, asserting row alignment.

    clustered.csv is read only for the join key -- group membership (cluster/
    soc_major) is not this module's concern; it already lives in
    network_nodes.csv.
    """
    embeddings = np.load(EMBEDDINGS_PATH)
    df = pd.read_csv(CLUSTERED_PATH)
    if len(embeddings) != len(df):
        raise ValueError(
            f"Row mismatch: {len(embeddings)} embeddings vs {len(df)} rows in "
            f"{CLUSTERED_PATH}. embeddings.npy and clustered.csv must share row order."
        )
    if PERSON_INDEX_COL not in df.columns:
        raise KeyError(
            f"Expected a '{PERSON_INDEX_COL}' column in {CLUSTERED_PATH}; found "
            f"{list(df.columns)}."
        )
    return embeddings, df[PERSON_INDEX_COL]


def run_umap_3d(embeddings: np.ndarray, n_neighbors: int, min_dist: float) -> np.ndarray:
    """Fit UMAP at n_components=3 and return (n, 3) coordinates."""
    reducer = UMAP(
        n_components=3,
        n_neighbors=n_neighbors,
        min_dist=min_dist,
        metric=METRIC,
        random_state=SEED,
    )
    return reducer.fit_transform(embeddings)


def main() -> None:
    embeddings, person_index = load_inputs()
    print(f"Loaded {len(person_index)} profiles / {embeddings.shape[1]}-d embeddings.")

    print(f"\n3D projection with {FINAL_PARAMS} (n_components=3) ...")
    coords = run_umap_3d(embeddings, **FINAL_PARAMS)

    trust = trustworthiness(embeddings, coords, n_neighbors=TRUST_K, metric=METRIC)
    print(f"3D trustworthiness (k={TRUST_K}): {trust:.4f}")

    out = pd.DataFrame({
        "person_index": person_index,
        "umap_3d_x": coords[:, 0],
        "umap_3d_y": coords[:, 1],
        "umap_3d_z": coords[:, 2],
    })
    out.to_csv(PROJECTED_3D_PATH, index=False)
    print(f"\nWrote {PROJECTED_3D_PATH} ({len(out)} rows, {len(out.columns)} cols)")


if __name__ == "__main__":
    main()
