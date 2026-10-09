"""
src/centrality.py — Phase 1, Day 8

Computes node-level centrality on the cosine-similarity graph from graph.py and
consolidates EVERY per-node Phase-1 attribute (cluster, cluster_name, outlier
flag, UMAP coordinates, centrality) into the single canonical table the Phase-2
dashboard will consume:  data/graph/network_nodes.csv


graph.py already owns graph construction and load_nodes() already assembles the
per-person identity/cluster/coordinate table. This module imports both, so the
threshold tau can never drift, and the canonical table is load_nodes()
plus five centrality columns. Graph nodes are keyed by string `id`; centrality
dicts are therefore id-keyed and joined back to person_index via the nodes table.

Methodological crux — similarity vs distance
--------------------------------------------
Edges store cosine SIMILARITY (higher = closer); NetworkX shortest-path routines
read `weight` as DISTANCE (lower = closer). So:
  * PageRank / strength     -> raw SIMILARITY   (stronger tie = followed more)
  * Betweenness / closeness -> d = 1 - similarity (stronger tie = SHORTER hop)

Disconnection (Day 7: 13 components, 4 isolates) drives two choices:
  * PageRank over eigenvector centrality — teleport (alpha=0.85) guarantees
    convergence and floors isolates at (1-alpha)/N; eigenvector collapses onto
    the giant component. eigenvector_diagnostic() prints the evidence.
  * Wasserman-Faust closeness (wf_improved=True) — rescales by reachable
    fraction so two-node islands stop out-ranking genuine hubs.

Run from repo root:
    python -m src.centrality
"""

from pathlib import Path

import numpy as np
import pandas as pd
import networkx as nx
from sklearn.metrics.pairwise import cosine_similarity

# Reuse graph.py's construction so tau is identical to Day 7 (single source of truth).
from src.graph import (
    load_nodes, choose_threshold, build_graph,
    EMBEDDINGS_NPY, MANUAL_TAU,
    PERSON_INDEX_COL, CLUSTER_COL, OUTLIER_COL,
)

# Import the ground-truth config constant
from src.config import GRAPH_TARGET_MEAN_DEGREE
TARGET_DEGREE = GRAPH_TARGET_MEAN_DEGREE

NODES_OUT = Path("data/graph/network_nodes.csv")   # tracked -> Phase-2 input
CLASSIFIED_CSV = Path("data/cache/classified.csv")  # Phase 1.5: is_uncertain source
PAGERANK_ALPHA = 0.85

CANONICAL_COLS = [
    PERSON_INDEX_COL, "id", "name", "role",
    "soc_major", "soc_major_name", OUTLIER_COL,
    "umap_x", "umap_y",
    "degree_centrality", "strength", "betweenness", "pagerank", "closeness_wf",
    "is_uncertain", "classifier_tier", "classifier_confidence",
]


def load_graph_and_nodes():
    """Rebuild exactly what graph.py main() builds, so tau matches Day 7."""
    emb = np.load(EMBEDDINGS_NPY)
    nodes = load_nodes(emb.shape[0])
    sim = cosine_similarity(emb)
    np.fill_diagonal(sim, 0.0)
    tau = float(MANUAL_TAU) if MANUAL_TAU is not None else choose_threshold(sim, TARGET_DEGREE)
    return build_graph(nodes, sim, tau), nodes, tau


def _attach_distance(G):
    """d = 1 - cosine_similarity on every edge, in place, for path metrics.

    Clipped at 0.0: identical titles (e.g. 5 people all "Sales Assistant") embed
    to identical vectors, so cosine can be 1.0 + floating-point epsilon, giving a
    tiny negative distance that makes Dijkstra raise "negative weights?". Real
    duplicate titles in the LinkedIn data surface this; synthetic data never did.
    A distance of exactly 0 is correct for a perfect-similarity edge.
    """
    for _, _, data in G.edges(data=True):
        data["distance"] = max(0.0, 1.0 - data["weight"])


def compute_centrality(G):
    """Four centralities + weighted degree, one row per node, keyed by string id."""
    _attach_distance(G)
    ids = list(G.nodes())

    degree_c    = nx.degree_centrality(G)                                   # structural
    strength    = dict(G.degree(weight="weight"))                          # weighted degree
    betweenness = nx.betweenness_centrality(G, weight="distance", normalized=True)
    pagerank    = nx.pagerank(G, alpha=PAGERANK_ALPHA, weight="weight")     # similarity
    closeness   = nx.closeness_centrality(G, distance="distance", wf_improved=True)  # WF

    return pd.DataFrame({
        "id":                ids,
        "degree_centrality": [degree_c[i]    for i in ids],
        "strength":          [strength[i]    for i in ids],
        "betweenness":       [betweenness[i] for i in ids],
        "pagerank":          [pagerank[i]    for i in ids],
        "closeness_wf":      [closeness[i]   for i in ids],
    })


def eigenvector_diagnostic(G):
    """Evidence for choosing PageRank: how does eigenvector centrality misbehave here?"""
    try:
        ev = nx.eigenvector_centrality(G, max_iter=1000, weight="weight")
        crushed = sum(1 for v in ev.values() if v < 1e-6)
        return (f"eigenvector converged but {crushed}/{G.number_of_nodes()} nodes "
                f"collapse to ~0 (mass concentrates on the giant component)")
    except nx.PowerIterationFailedConvergence:
        return "eigenvector centrality FAILED to converge on the disconnected graph"


def build_canonical_table(nodes, centrality_df):
    """load_nodes() output + centrality -> canonical network_nodes table.

    Phase 1.5: join is_uncertain/classifier_tier/classifier_confidence from
    classified.csv so the ~26% the classifier abstained on carry the flag (and
    its provenance) into the Phase-2 dashboard as grey review nodes. Falls back
    to is_outlier if classified.csv is absent (synthetic runs).

    cluster/cluster_name are graph.py's compatibility-shim names (shared with
    the HDBSCAN-shaped clustered.csv/cluster_labels.csv contract); renamed here,
    at the canonical-output boundary, to soc_major/soc_major_name since this is
    the classifier-facing table the Phase-2 dashboard actually reads.
    """
    canonical = (nodes.merge(centrality_df, on="id", how="left")
                      .rename(columns={
                          "x": "umap_x", "y": "umap_y",
                          CLUSTER_COL: "soc_major", "cluster_name": "soc_major_name",
                      }))
    if CLASSIFIED_CSV.exists():
        cl = pd.read_csv(CLASSIFIED_CSV)[
            [PERSON_INDEX_COL, "is_uncertain", "classifier_tier", "classifier_confidence"]
        ]
        canonical = canonical.merge(cl, on=PERSON_INDEX_COL, how="left")
        canonical["is_uncertain"] = canonical["is_uncertain"].fillna(False).astype(bool)
    else:
        canonical["is_uncertain"] = canonical[OUTLIER_COL]
        canonical["classifier_tier"] = None
        canonical["classifier_confidence"] = None
    return canonical[CANONICAL_COLS].sort_values(PERSON_INDEX_COL).reset_index(drop=True)


def main():
    G, nodes, tau = load_graph_and_nodes()
    print(f"graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges, "
          f"tau={tau:.4f}, {nx.number_connected_components(G)} components, "
          f"{len(list(nx.isolates(G)))} isolates")

    centrality_df = compute_centrality(G)
    canonical = build_canonical_table(nodes, centrality_df)

    print("\ntop 5 by PageRank (prestige):")
    print(canonical.sort_values("pagerank", ascending=False)
          [["name", "soc_major_name", "pagerank", "betweenness"]].head().to_string(index=False))
    print("\ntop 5 by betweenness (brokers between clusters):")
    print(canonical.sort_values("betweenness", ascending=False)
          [["name", "soc_major_name", "betweenness", "pagerank"]].head().to_string(index=False))
    print("\ndiagnostic:", eigenvector_diagnostic(G))

    NODES_OUT.parent.mkdir(parents=True, exist_ok=True)
    canonical.to_csv(NODES_OUT, index=False)
    print(f"\nwrote {NODES_OUT} ({len(canonical)} rows, {len(canonical.columns)} cols)")


if __name__ == "__main__":
    main()