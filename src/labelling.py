"""
src/labelling.py — Phase 1, Day 6: cluster labelling via TF-IDF top terms.

clustered.csv is a thin label table keyed by position:
    person_index, cluster, is_outlier, probability
The text to label from lives upstream, so we reload it via load_profiles() —
the SAME loader embeddings.py used — which guarantees identical row order, then
merge on person_index. A fail-fast alignment check guards against silent
mislabelling (clusters that still look fine but point at the wrong people).

TF-IDF is fit across all people (IDF = rarity within the network); each cluster
is summarised by the mean TF-IDF vector of its members, and its top terms form a
human-readable name.

Run from the repo root:
    python -m src.labelling

Outputs
-------
data/labels/cluster_labels.csv    tracked   -> cluster_id, name, size, top_terms
data/labels/cluster_top_terms.png tracked   -> small-multiples bar chart
data/cache/labelled.csv           gitignored -> per-person rows + `cluster_name`
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")  # headless: we only ever save the figure
import matplotlib.pyplot as plt
from sklearn.feature_extraction.text import TfidfVectorizer, ENGLISH_STOP_WORDS
DEGREE_STOPWORDS = {"ba", "bsc", "beng", "meng", "msc", "ma", "mba", "phd",
                    "education", "accredited", "degree", "university", "bachelor", "master"}
LABEL_STOPWORDS = list(ENGLISH_STOP_WORDS | DEGREE_STOPWORDS)

from src.ingestion import load_profiles

# --- config -----------------------------------------------------------------
CLUSTERED_CSV = Path("data/cache/clustered.csv")           # gitignored input
LABELS_CSV = Path("data/labels/cluster_labels.csv")        # tracked output
TERMS_PLOT = Path("data/labels/cluster_top_terms.png")     # tracked output
LABELLED_CSV = Path("data/cache/labelled.csv")             # gitignored output

# clustered.csv columns (confirmed against clustering.py output).
PERSON_INDEX_COL = "person_index"
CLUSTER_COL = "cluster"
OUTLIER_COL = "is_outlier"
PROB_COL = "probability"
TEXT_COL = "profile_text"   # reconstructed from load_profiles(), not from the CSV
NOISE_LABEL = -1

# labelling knobs
TOP_N_TERMS = 8    # terms inspected/stored per cluster
NAME_N_TERMS = 3   # terms that form the human-readable name
NOISE_NAME = "Needs review"

# Optional: weight each member's TF-IDF by its HDBSCAN soft-membership
# (`probability`) so marginal members contribute less to the label. Off by
# default; flip to True to compare — a clean line for the write-up.
WEIGHT_BY_PROBABILITY = False


def load_clustered() -> pd.DataFrame:
    """
    Rebuild a per-person frame carrying BOTH the cluster label and the text to
    label it with, joined on person_index.

    The text is reloaded through load_profiles() (identical order to the
    embeddings, by construction), never re-read independently — that is what
    keeps person_index meaningful.
    """
    if not CLUSTERED_CSV.exists():
        raise FileNotFoundError(
            f"{CLUSTERED_CSV} not found. Run clustering.py first."
        )

    labels = pd.read_csv(CLUSTERED_CSV)
    for col in (PERSON_INDEX_COL, CLUSTER_COL):
        if col not in labels.columns:
            raise KeyError(
                f"Expected '{col}' in {CLUSTERED_CSV}. "
                f"Found: {list(labels.columns)}."
            )

    people = load_profiles()
    text_df = pd.DataFrame(
        {
            PERSON_INDEX_COL: range(len(people)),
            TEXT_COL: [p.profile_text for p in people],
            "name": [p.name for p in people],
            "role": [p.role for p in people],
        }
    )

    # Fail-fast alignment guard: a mismatch here means the label table and the
    # profiles came from different data, and any merge would mislabel people.
    if len(labels) != len(text_df):
        raise ValueError(
            f"Row-count mismatch: {len(labels)} rows in clustered.csv vs "
            f"{len(text_df)} profiles from load_profiles(). Recluster from the "
            "current dataset before labelling."
        )
    if set(labels[PERSON_INDEX_COL]) != set(text_df[PERSON_INDEX_COL]):
        raise ValueError(
            "person_index in clustered.csv does not match range(len(profiles)). "
            "Alignment cannot be guaranteed — recluster from current profiles."
        )

    df = labels.merge(
        text_df, on=PERSON_INDEX_COL, how="inner", validate="one_to_one"
    )
    df[TEXT_COL] = df[TEXT_COL].fillna("").astype(str)
    return df.sort_values(PERSON_INDEX_COL).reset_index(drop=True)


def fit_tfidf(texts: list[str]) -> tuple[TfidfVectorizer, "np.ndarray"]:
    """Fit TF-IDF across all people (IDF = rarity within the network)."""
    vec = TfidfVectorizer(
        lowercase=True,
        stop_words=LABEL_STOPWORDS,
        ngram_range=(1, 2),   # keep bigrams like "data science" intact
        min_df=2,             # drop terms unique to a single person
        max_df=0.8,           # drop near-ubiquitous filler
        sublinear_tf=True,    # log-scale term frequency
    )
    matrix = vec.fit_transform(texts)
    return vec, matrix


def top_terms_per_cluster(
    df: pd.DataFrame, vec: TfidfVectorizer, matrix
) -> dict[int, list[tuple[str, float]]]:
    """Mean (or probability-weighted) TF-IDF vector per cluster -> top terms."""
    terms = np.array(vec.get_feature_names_out())
    results: dict[int, list[tuple[str, float]]] = {}
    for cid in sorted(df[CLUSTER_COL].unique()):
        if cid == NOISE_LABEL:
            continue
        mask = (df[CLUSTER_COL] == cid).to_numpy()
        sub = matrix[mask]

        if WEIGHT_BY_PROBABILITY and PROB_COL in df.columns:
            w = df.loc[mask, PROB_COL].to_numpy(dtype=float)
            w = w / w.sum() if w.sum() > 0 else np.full(len(w), 1 / len(w))
            centroid = np.asarray(sub.multiply(w[:, None]).sum(axis=0)).ravel()
        else:
            centroid = np.asarray(sub.mean(axis=0)).ravel()

        order = centroid.argsort()[::-1][:TOP_N_TERMS]
        results[int(cid)] = [
            (terms[i], float(centroid[i])) for i in order if centroid[i] > 0
        ]
    return results


def make_name(top_terms: list[tuple[str, float]]) -> str:
    words = [t for t, _ in top_terms[:NAME_N_TERMS]]
    return " / ".join(w.title() for w in words) if words else "Unlabelled"


def build_label_table(
    df: pd.DataFrame, cluster_terms: dict[int, list[tuple[str, float]]]
) -> pd.DataFrame:
    rows = []
    for cid, terms in cluster_terms.items():
        rows.append(
            {
                "cluster_id": cid,
                "cluster_name": make_name(terms),
                "size": int((df[CLUSTER_COL] == cid).sum()),
                "top_terms": ", ".join(t for t, _ in terms),
            }
        )
    return pd.DataFrame(rows).sort_values("cluster_id").reset_index(drop=True)


def plot_top_terms(
    cluster_terms: dict[int, list[tuple[str, float]]],
    labels: pd.DataFrame,
    out_path: Path,
    n: int = 6,
) -> None:
    ids = sorted(cluster_terms)
    k = len(ids)
    cols = min(3, k)
    rows = int(np.ceil(k / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(4.2 * cols, 3.0 * rows))
    axes = np.atleast_1d(axes).ravel()
    name_of = dict(zip(labels["cluster_id"], labels["cluster_name"]))
    for ax, cid in zip(axes, ids):
        terms = cluster_terms[cid][:n][::-1]  # ascending for barh
        ax.barh([t for t, _ in terms], [w for _, w in terms])
        ax.set_title(f"Cluster {cid}: {name_of[cid]}", fontsize=10)
        ax.tick_params(labelsize=8)
    for ax in axes[k:]:
        ax.axis("off")
    fig.suptitle("Top TF-IDF terms per cluster", fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def main() -> None:
    df = load_clustered()

    vec, matrix = fit_tfidf(df[TEXT_COL].tolist())
    cluster_terms = top_terms_per_cluster(df, vec, matrix)
    labels = build_label_table(df, cluster_terms)

    n_noise = int((df[CLUSTER_COL] == NOISE_LABEL).sum())
    print(f"Vocabulary size: {len(vec.get_feature_names_out())}")
    print(
        f"Clusters named: {len(labels)} "
        f"(noise excluded: {n_noise} point(s))"
        f"{'  [probability-weighted]' if WEIGHT_BY_PROBABILITY else ''}\n"
    )
    for _, r in labels.iterrows():
        print(f"  [{r.cluster_id}] n={r['size']:>2}  {r.cluster_name}")
        print(f"       {r.top_terms}")

    # tracked outputs
    LABELS_CSV.parent.mkdir(parents=True, exist_ok=True)
    labels.to_csv(LABELS_CSV, index=False)
    plot_top_terms(cluster_terms, labels, TERMS_PLOT)

    # gitignored per-person output for downstream stages
    name_map = dict(zip(labels["cluster_id"], labels["cluster_name"]))
    out = df.copy()
    out["cluster_name"] = out[CLUSTER_COL].map(name_map).fillna(NOISE_NAME)
    LABELLED_CSV.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(LABELLED_CSV, index=False)

    print(f"\nWrote {LABELS_CSV}")
    print(f"Wrote {TERMS_PLOT}")
    print(f"Wrote {LABELLED_CSV}")


if __name__ == "__main__":
    main()