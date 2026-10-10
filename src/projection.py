"""
src/projection.py — Phase 1, Stage 5: 2-D projection via UMAP.

Consumes the cached embeddings (data/cache/embeddings.npy) and the clustered
dataframe (data/cache/clustered.csv), reduces the 384-d semantic vectors to two
dimensions for plotting, and writes an augmented dataframe with (umap_x, umap_y)
columns alongside each person's cluster label.

Run from the repo root:
    python -m src.projection

Design notes (for write-up):
  * metric='cosine' matches the semantic geometry of the sentence-transformer
    embeddings and keeps the projection consistent with the similarity-based
    edges built later in the pipeline. NB: confirm this is consistent with the
    metric your HDBSCAN used on Day 4 (sklearn HDBSCAN defaults to euclidean);
    if the embeddings are not unit-normalised, document the choice.
  * random_state=SEED makes the layout reproducible. UMAP disables its parallel
    code path when a seed is set (single-threaded, slower, prints a warning) --
    this is expected and is the price of a deterministic figure.
  * trustworthiness is reported as the projection analogue of the silhouette
    score: it measures how faithfully local neighbourhoods survive the 384->2
    reduction, giving a defensible quantitative claim about layout quality.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from sklearn.manifold import trustworthiness
from umap import UMAP

from src.config import RANDOM_SEED, UMAP_PARAMS

SEED = RANDOM_SEED

CACHE_DIR = Path("data/cache")
EMBEDDINGS_PATH = CACHE_DIR / "embeddings.npy"
CLUSTERED_PATH = CACHE_DIR / "clustered.csv"

PROJECTED_PATH = CACHE_DIR / "projected.csv"          # gitignored (derived, like clustered.csv)
SWEEP_PATH = CACHE_DIR / "umap_sweep_results.csv"     # tracked (evidence for the write-up)
PLOT_PATH = CACHE_DIR / "umap_projection.png"         # tracked

METRIC = "cosine"
TRUST_K = 5          # neighbourhood size for the trustworthiness metric
CLUSTER_COL = "cluster"   # adjust if your Day-4 output names the label column differently

# Single source in src/config.py, shared with projection_3d.py (D-29); the
# rationale for the values is recorded there.
FINAL_PARAMS = UMAP_PARAMS

SWEEP_GRID = {
    "n_neighbors": [10, 15, 30, 50],
    "min_dist": [0.0, 0.1, 0.25],
}


def load_inputs() -> tuple[np.ndarray, pd.DataFrame]:
    """Load cached embeddings and the clustered dataframe, asserting row alignment."""
    embeddings = np.load(EMBEDDINGS_PATH)
    df = pd.read_csv(CLUSTERED_PATH)
    if len(embeddings) != len(df):
        raise ValueError(
            f"Row mismatch: {len(embeddings)} embeddings vs {len(df)} rows in "
            f"{CLUSTERED_PATH}. embeddings.npy and clustered.csv must share row order."
        )
    if CLUSTER_COL not in df.columns:
        raise KeyError(
            f"Expected a '{CLUSTER_COL}' column in {CLUSTERED_PATH}; found "
            f"{list(df.columns)}. Update CLUSTER_COL to match your Day-4 output."
        )
    return embeddings, df


def run_umap(embeddings: np.ndarray, n_neighbors: int, min_dist: float) -> np.ndarray:
    """Fit UMAP on the embeddings and return (n, 2) coordinates."""
    reducer = UMAP(
        n_components=2,
        n_neighbors=n_neighbors,
        min_dist=min_dist,
        metric=METRIC,
        random_state=SEED,
    )
    return reducer.fit_transform(embeddings)


def sweep_umap(embeddings: np.ndarray) -> pd.DataFrame:
    """Grid-search n_neighbors x min_dist, scoring each layout by trustworthiness."""
    rows = []
    for n_neighbors in SWEEP_GRID["n_neighbors"]:
        for min_dist in SWEEP_GRID["min_dist"]:
            coords = run_umap(embeddings, n_neighbors, min_dist)
            score = trustworthiness(
                embeddings, coords, n_neighbors=TRUST_K, metric=METRIC
            )
            rows.append(
                {
                    "n_neighbors": n_neighbors,
                    "min_dist": min_dist,
                    "trustworthiness": round(float(score), 4),
                }
            )
            print(
                f"  n_neighbors={n_neighbors:>2}  min_dist={min_dist:<4}  "
                f"trustworthiness={score:.4f}"
            )
    return pd.DataFrame(rows).sort_values("trustworthiness", ascending=False)


def plot_projection(df: pd.DataFrame) -> None:
    """Scatter the 2-D layout, coloured by cluster; noise (-1) rendered grey."""
    fig, ax = plt.subplots(figsize=(9, 7))
    for c in sorted(df[CLUSTER_COL].unique()):
        sub = df[df[CLUSTER_COL] == c]
        if c == -1:
            ax.scatter(
                sub["umap_x"], sub["umap_y"], c="lightgrey",
                s=40, label="noise", edgecolors="none",
            )
        else:
            ax.scatter(
                sub["umap_x"], sub["umap_y"], s=50,
                label=f"cluster {c}", edgecolors="white", linewidths=0.5,
            )
    ax.set_title(
        f"UMAP projection (n_neighbors={FINAL_PARAMS['n_neighbors']}, "
        f"min_dist={FINAL_PARAMS['min_dist']}, metric={METRIC})"
    )
    ax.set_xlabel("UMAP-1")
    ax.set_ylabel("UMAP-2")
    ax.legend(loc="best", fontsize=8, frameon=False)
    fig.tight_layout()
    fig.savefig(PLOT_PATH, dpi=150)
    plt.close(fig)


def main() -> None:
    embeddings, df = load_inputs()
    print(f"Loaded {len(df)} profiles / {embeddings.shape[1]}-d embeddings.")

    print("\nSweeping UMAP hyperparameters (trustworthiness):")
    sweep = sweep_umap(embeddings)
    sweep.to_csv(SWEEP_PATH, index=False)
    print(f"\nSweep written to {SWEEP_PATH}")
    print(sweep.to_string(index=False))

    print(f"\nFinal projection with {FINAL_PARAMS} ...")
    coords = run_umap(embeddings, **FINAL_PARAMS)
    df["umap_x"] = coords[:, 0]
    df["umap_y"] = coords[:, 1]

    final_trust = trustworthiness(
        embeddings, coords, n_neighbors=TRUST_K, metric=METRIC
    )
    print(f"Final trustworthiness (k={TRUST_K}): {final_trust:.4f}")

    df.to_csv(PROJECTED_PATH, index=False)
    plot_projection(df)
    print(f"\nWrote {PROJECTED_PATH} and {PLOT_PATH}")


if __name__ == "__main__":
    main()