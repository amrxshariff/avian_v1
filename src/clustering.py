"""
Phase 1, Day 4 — Clustering.
 
Runs HDBSCAN (sklearn implementation) over the cached (N, 384) embeddings
matrix produced in Day 3, assigns a cluster label per person (outliers = -1),
and reports the first quotable  metric: the silhouette score.
 
Design decisions (see write-up):
  * sklearn.cluster.HDBSCAN is used over the standalone `hdbscan` package for
    build reproducibility (no C-extension build on Windows/OneDrive).
  * Silhouette is computed on CLUSTERED points only. HDBSCAN assigns noise to
    label -1; -1 is not a real cluster, so including it distorts the metric.
    We report the silhouette over non-noise points and the outlier count
    separately.
  * A hyperparameter sweep over (min_cluster_size, min_samples) is run so the
    final choice is justified with evidence rather than asserted.
 
Run from the repo root:
    python -m src.clustering
"""
 
from __future__ import annotations
 
from dataclasses import dataclass, asdict
from pathlib import Path
 
import numpy as np
import pandas as pd
from sklearn.cluster import HDBSCAN
from sklearn.metrics import silhouette_score
 
SEED = 42
 
# Repo-root-relative paths (module is run as `python -m src.clustering`).
ROOT = Path(__file__).resolve().parents[1]
EMBEDDINGS_PATH = ROOT / "data" / "cache" / "embeddings.npy"
CLUSTERED_PATH = ROOT / "data" / "cache" / "clustered.csv"
SWEEP_CSV_PATH = ROOT / "data" / "cache" / "sweep_results.csv"
SWEEP_PLOT_PATH = ROOT / "data" / "cache" / "sweep_silhouette.png"
 
# Factorial sweep. min_samples is always explicit (never None): sklearn resolves
# None to min_cluster_size, which would silently vary BOTH knobs per row and
# report min_samples=None for a run that actually used a real value — the table
# must be reproducible from what it prints.
# min_samples <= min_cluster_size by convention.
SWEEP_GRID: list[dict] = [
    {"min_cluster_size": mcs, "min_samples": ms}
    for mcs in (5, 10, 15, 20, 25)
    for ms in (3, 5, 10)
    if ms <= mcs
]
 
# Chosen configuration used for the persisted output. Update after inspecting
# the sweep table; kept explicit so the "final model" is unambiguous.
FINAL_PARAMS: dict = {"min_cluster_size": 5, "min_samples": 3}
 
 
@dataclass
class ClusterResult:
    """Outcome of one HDBSCAN fit."""
 
    min_cluster_size: int
    min_samples: int | None
    n_clusters: int
    n_outliers: int
    outlier_pct: float
    silhouette: float | None  # None when < 2 clusters remain after noise removal
 
 
def load_embeddings(path: Path = EMBEDDINGS_PATH) -> np.ndarray:
    """Load the cached (N, 384) embeddings matrix from Day 3."""
    if not path.exists():
        raise FileNotFoundError(
            f"Embeddings cache not found at {path}. "
            "Run `python -m src.embeddings` first (Day 3)."
        )
    X = np.load(path)
    if X.ndim != 2:
        raise ValueError(f"Expected a 2-D matrix, got shape {X.shape}.")
    return X
 
 
def _silhouette_no_noise(X: np.ndarray, labels: np.ndarray) -> float | None:
    """
    Silhouette over non-noise points only (labels != -1), metric='cosine'.
 
    Returns None if fewer than 2 clusters survive, since silhouette is
    undefined for a single cluster.
    """
    mask = labels != -1
    kept_labels = labels[mask]
    if len(set(kept_labels)) < 2:
        return None
    return float(silhouette_score(X[mask], kept_labels, metric="cosine"))
 
 
def run_hdbscan(X: np.ndarray, min_cluster_size: int,
                min_samples: int | None) -> tuple[np.ndarray, np.ndarray, ClusterResult]:
    """
    Fit sklearn HDBSCAN once. Returns (labels, probabilities, ClusterResult).
 
    Cosine distance is used to match the semantic geometry of sentence-
    transformer embeddings (magnitude carries little meaning; direction does).
    """
    model = HDBSCAN(
        min_cluster_size=min_cluster_size,
        min_samples=min_samples,
        metric="cosine",
        copy=True,
    )
    labels = model.fit_predict(X)
    probabilities = model.probabilities_
 
    n_clusters = len(set(labels) - {-1})
    n_outliers = int((labels == -1).sum())
    outlier_pct = 100.0 * n_outliers / len(labels)
    silhouette = _silhouette_no_noise(X, labels)
 
    result = ClusterResult(
        min_cluster_size=min_cluster_size,
        min_samples=min_samples,
        n_clusters=n_clusters,
        n_outliers=n_outliers,
        outlier_pct=round(outlier_pct, 1),
        silhouette=None if silhouette is None else round(silhouette, 4),
    )
    return labels, probabilities, result
 
 
def sweep(X: np.ndarray, grid: list[dict] = SWEEP_GRID) -> pd.DataFrame:
    """Run HDBSCAN across the grid and return a comparison dataframe."""
    rows = [asdict(run_hdbscan(X, **params)[2]) for params in grid]
    return pd.DataFrame(rows)
 
 
def save_sweep_plot(df: pd.DataFrame, path: Path = SWEEP_PLOT_PATH) -> None:
    """Silhouette vs min_cluster_size, one line per min_samples. Skips None rows."""
    import matplotlib
    matplotlib.use("Agg")  # headless-safe
    import matplotlib.pyplot as plt
 
    plott = df.dropna(subset=["silhouette"])
    fig, ax = plt.subplots(figsize=(6, 4))
    for ms, grp in plott.groupby("min_samples"):
        grp = grp.sort_values("min_cluster_size")
        ax.plot(grp["min_cluster_size"], grp["silhouette"],
                marker="o", label=f"min_samples={ms}")
    ax.legend(fontsize=8, title="min_samples")
    ax.set_xlabel("min_cluster_size")
    ax.set_ylabel("silhouette (cosine, noise excluded)")
    ax.set_title("HDBSCAN hyperparameter sweep")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
 
 
def build_clustered_frame(labels: np.ndarray,
                          probabilities: np.ndarray) -> pd.DataFrame:
    """
    Stable output contract for downstream stages (Day 5 UMAP, Day 7 graph).
 
    Row order matches the embeddings matrix, which matches the ingestion order,
    so `person_index` joins cleanly back to the Person objects.
    """
    return pd.DataFrame(
        {
            "person_index": np.arange(len(labels)),
            "cluster": labels,
            "is_outlier": labels == -1,
            "probability": probabilities,
        }
    )
 
 
def main() -> None:
    X = load_embeddings()
    print(f"Loaded embeddings: {X.shape}\n")
 
    # --- Hyperparameter sweep (UCL write-up evidence) -------------------------
    sweep_df = sweep(X)
    print("Hyperparameter sweep:")
    print(sweep_df.to_string(index=False))
    SWEEP_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    sweep_df.to_csv(SWEEP_CSV_PATH, index=False)
    try:
        save_sweep_plot(sweep_df)
        print(f"\nSweep plot saved -> {SWEEP_PLOT_PATH.relative_to(ROOT)}")
    except ImportError:
        print("\n(matplotlib not installed; skipped plot. `pip install matplotlib`)")
 
    # --- Final model + persisted output --------------------------------------
    labels, probs, result = run_hdbscan(X, **FINAL_PARAMS)
    print(f"\nFinal model {FINAL_PARAMS}:")
    print(f"  clusters : {result.n_clusters}")
    print(f"  outliers : {result.n_outliers} ({result.outlier_pct}%)")
    print(f"  silhouette (cosine, noise excluded): {result.silhouette}")
 
    frame = build_clustered_frame(labels, probs)
    frame.to_csv(CLUSTERED_PATH, index=False)
    print(f"\nClustered frame saved -> {CLUSTERED_PATH.relative_to(ROOT)}")
 
 
if __name__ == "__main__":
    main()