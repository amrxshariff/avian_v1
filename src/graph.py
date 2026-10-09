"""
src/graph.py — Phase 1, Day 7: build the weighted network graph.

Consumes the cached embeddings + the label table and builds a NetworkX graph
where nodes are people (carrying id/name/role/cluster/cluster_name/x/y) and edges
are weighted by cosine similarity, sparsified to a target average degree.

Design choices:
  - Cosine similarity end-to-end (consistent with HDBSCAN + UMAP).
  - A single global threshold τ, chosen to hit a target mean degree, so every
    surviving edge means "genuinely similar" and the knob is interpretable.
  - Isolates are preserved: a node with no edge above τ stays unconnected,
    because low affinity is signal (same philosophy as HDBSCAN keeping outliers).
  - The full similarity matrix is cached so the Phase-2 density slider can
    re-threshold instantly without recomputing.

Validation:
  - Modularity Q of the HDBSCAN partition on the weighted graph.
  - Bonus: NetworkX greedy community detection + Adjusted Rand Index vs HDBSCAN.

Run from the repo root:
    python -m src.graph

Outputs
-------
data/cache/graph.graphml     gitignored  -> the graph (recomputable)
data/cache/similarity.npy    gitignored  -> full cosine matrix (for the slider)
data/graph/graph_metrics.csv tracked     -> metric, value summary
data/graph/network_preview.png tracked   -> cluster-coloured layout
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import networkx as nx
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.metrics import adjusted_rand_score

from src.ingestion import load_profiles

# --- config -----------------------------------------------------------------
EMBEDDINGS_NPY = Path("data/cache/embeddings.npy")     # gitignored input
CLUSTERED_CSV = Path("data/cache/clustered.csv")       # gitignored input
LABELS_CSV = Path("data/labels/cluster_labels.csv")    # tracked input (Day 6)
PROJECTED_CSV = Path("data/cache/projected.csv")       # gitignored input (Day 5, optional)

GRAPH_OUT = Path("data/cache/graph.graphml")           # gitignored output
SIM_OUT = Path("data/cache/similarity.npy")            # gitignored output
METRICS_OUT = Path("data/graph/graph_metrics.csv")     # tracked output
PREVIEW_OUT = Path("data/graph/network_preview.png")   # tracked output

PERSON_INDEX_COL = "person_index"
CLUSTER_COL = "cluster"
OUTLIER_COL = "is_outlier"
NOISE_LABEL = -1
NOISE_NAME = "Needs review"

from src.config import GRAPH_TARGET_MEAN_DEGREE
TARGET_DEGREE = GRAPH_TARGET_MEAN_DEGREE      # desired average node degree -> drives threshold τ
MANUAL_TAU = None      # set a float in [0, 1] to override degree-targeting
SEED = 42

# coordinate column pairs we recognise in projected.csv (case-insensitive)
COORD_CANDIDATES = [
    ("x", "y"), ("umap_x", "umap_y"), ("umap_1", "umap_2"),
    ("umap0", "umap1"), ("dim0", "dim1"), ("comp1", "comp2"), ("0", "1"),
]


# --- data assembly ----------------------------------------------------------
def _detect_coords(proj: pd.DataFrame) -> tuple[str, str] | None:
    lower = {c.lower(): c for c in proj.columns}
    for a, b in COORD_CANDIDATES:
        if a in lower and b in lower:
            return lower[a], lower[b]
    return None


def load_nodes(n_people: int) -> pd.DataFrame:
    """Assemble a per-person node table keyed by person_index (0..N-1)."""
    people = load_profiles()
    if len(people) != n_people:
        raise ValueError(
            f"{len(people)} profiles from load_profiles() but embeddings has "
            f"{n_people} rows. Recompute embeddings from the current dataset."
        )

    nodes = pd.DataFrame(
        {
            PERSON_INDEX_COL: range(len(people)),
            "id": [str(p.id) for p in people],
            "name": [p.name for p in people],
            "role": [p.role for p in people],
        }
    )

    clustered = pd.read_csv(CLUSTERED_CSV)
    if set(clustered[PERSON_INDEX_COL]) != set(nodes[PERSON_INDEX_COL]):
        raise ValueError(
            "person_index in clustered.csv does not match range(len(profiles)). "
            "Recluster from the current profiles before building the graph."
        )
    nodes = nodes.merge(
        clustered[[PERSON_INDEX_COL, CLUSTER_COL, OUTLIER_COL]],
        on=PERSON_INDEX_COL, how="inner", validate="one_to_one",
    )

    labels = pd.read_csv(LABELS_CSV)
    name_map = dict(zip(labels["cluster_id"], labels["cluster_name"]))
    nodes["cluster_name"] = nodes[CLUSTER_COL].map(name_map).fillna(NOISE_NAME)

    # coordinates: optional, plot-only, schema auto-detected
    nodes["x"] = np.nan
    nodes["y"] = np.nan
    if PROJECTED_CSV.exists():
        proj = pd.read_csv(PROJECTED_CSV)
        pair = _detect_coords(proj)
        if pair is None:
            print(f"  ! projected.csv found but no known coord columns "
                  f"({list(proj.columns)}); using spring layout for the plot.")
        else:
            xcol, ycol = pair
            if PERSON_INDEX_COL in proj.columns:
                proj = proj.set_index(PERSON_INDEX_COL)
                nodes["x"] = nodes[PERSON_INDEX_COL].map(proj[xcol])
                nodes["y"] = nodes[PERSON_INDEX_COL].map(proj[ycol])
            elif len(proj) == len(nodes):
                nodes["x"] = proj[xcol].to_numpy()
                nodes["y"] = proj[ycol].to_numpy()
            print(f"  UMAP coords loaded from projected.csv ({xcol}, {ycol}).")
    else:
        print("  ! projected.csv not found; using spring layout for the plot.")

    return nodes.sort_values(PERSON_INDEX_COL).reset_index(drop=True)


# --- graph construction -----------------------------------------------------
def choose_threshold(sim: np.ndarray, target_degree: int) -> float:
    """τ = the (N·d/2)-th largest off-diagonal similarity (upper triangle)."""
    n = sim.shape[0]
    iu = np.triu_indices(n, k=1)
    vals = np.sort(sim[iu])[::-1]
    target_edges = int(round(n * target_degree / 2))
    target_edges = max(1, min(target_edges, len(vals)))
    return float(vals[target_edges - 1])


def build_graph(nodes: pd.DataFrame, sim: np.ndarray, tau: float) -> nx.Graph:
    """All people as nodes; edges where similarity ≥ τ, weighted by similarity."""
    ids = nodes["id"].tolist()
    G = nx.Graph()
    for _, r in nodes.iterrows():
        G.add_node(
            r["id"], name=r["name"], role=r["role"],
            cluster=int(r[CLUSTER_COL]), cluster_name=r["cluster_name"],
            is_outlier=bool(r[OUTLIER_COL]),
            x=float(r["x"]) if pd.notna(r["x"]) else 0.0,
            y=float(r["y"]) if pd.notna(r["y"]) else 0.0,
        )
    n = len(ids)
    for i in range(n):
        for j in range(i + 1, n):
            w = sim[i, j]
            if w >= tau:
                G.add_edge(ids[i], ids[j], weight=float(w))
    return G


# --- validation -------------------------------------------------------------
def hdbscan_communities(nodes: pd.DataFrame) -> list[set]:
    """Clusters as communities; each noise point as its own singleton."""
    communities: list[set] = []
    for cid, grp in nodes.groupby(CLUSTER_COL):
        if cid == NOISE_LABEL:
            communities.extend({rid} for rid in grp["id"])
        else:
            communities.append(set(grp["id"]))
    return communities


def compute_validation(G: nx.Graph, nodes: pd.DataFrame) -> dict:
    """Modularity of HDBSCAN partition + greedy-community ARI comparison."""
    out: dict = {}
    if G.number_of_edges() == 0:
        out["modularity_hdbscan"] = float("nan")
        return out

    comms = hdbscan_communities(nodes)
    out["modularity_hdbscan"] = round(
        nx.community.modularity(G, comms, weight="weight"), 4
    )

    greedy = list(nx.community.greedy_modularity_communities(G, weight="weight"))
    out["n_greedy_communities"] = len(greedy)
    out["modularity_greedy"] = round(
        nx.community.modularity(G, greedy, weight="weight"), 4
    )

    greedy_label = {nid: k for k, com in enumerate(greedy) for nid in com}
    order = nodes["id"].tolist()
    y_true = nodes[CLUSTER_COL].to_numpy()
    y_pred = np.array([greedy_label[nid] for nid in order])
    out["ari_greedy_vs_hdbscan"] = round(adjusted_rand_score(y_true, y_pred), 4)
    return out


# --- plotting ---------------------------------------------------------------
def plot_graph(G: nx.Graph, nodes: pd.DataFrame, out_path: Path) -> None:
    # matplotlib is imported here, not at module level: this module is on the
    # in-app build chain (via centrality.py), and the preview PNG is a
    # command-line artefact the app never draws. Keeps matplotlib out of the
    # runtime manifest (D-31).
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    have_coords = nodes[["x", "y"]].notna().all(axis=None) and \
        not (nodes["x"].eq(0).all() and nodes["y"].eq(0).all())
    if have_coords:
        pos = {r["id"]: (r["x"], r["y"]) for _, r in nodes.iterrows()}
    else:
        pos = nx.spring_layout(G, seed=SEED, weight="weight")

    clusters = sorted(nodes[CLUSTER_COL].unique())
    cmap = plt.cm.tab10
    colour = {
        cid: ("#bbbbbb" if cid == NOISE_LABEL else cmap(i % 10))
        for i, cid in enumerate(clusters)
    }
    node_colours = [colour[G.nodes[nid]["cluster"]] for nid in G.nodes]

    fig, ax = plt.subplots(figsize=(11, 8))
    nx.draw_networkx_edges(G, pos, alpha=0.15, width=0.7, ax=ax)
    nx.draw_networkx_nodes(G, pos, node_color=node_colours, node_size=90,
                           linewidths=0.4, edgecolors="white", ax=ax)
    name_of = dict(zip(nodes[CLUSTER_COL], nodes["cluster_name"]))
    handles = [
        plt.Line2D([0], [0], marker="o", linestyle="", markersize=8,
                   markerfacecolor=colour[c],
                   label=(NOISE_NAME if c == NOISE_LABEL else name_of[c]))
        for c in clusters
    ]
    ax.legend(handles=handles, fontsize=8, loc="best", framealpha=0.9)
    ax.set_title("Skill-clustered professional network "
                 "(cosine edges, coloured by HDBSCAN cluster)")
    ax.axis("off")
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


# --- orchestration ----------------------------------------------------------
def main() -> None:
    if not EMBEDDINGS_NPY.exists():
        raise FileNotFoundError(f"{EMBEDDINGS_NPY} not found. Run embeddings.py first.")
    emb = np.load(EMBEDDINGS_NPY)
    print(f"Embeddings: {emb.shape}")

    nodes = load_nodes(emb.shape[0])

    sim = cosine_similarity(emb)
    np.fill_diagonal(sim, 0.0)  # no self-loops
    tau = float(MANUAL_TAU) if MANUAL_TAU is not None else \
        choose_threshold(sim, TARGET_DEGREE)

    G = build_graph(nodes, sim, tau)

    n = G.number_of_nodes()
    m = G.number_of_edges()
    isolates = list(nx.isolates(G))
    metrics = {
        "n_nodes": n,
        "n_edges": m,
        "threshold_tau": round(tau, 4),
        "target_degree": TARGET_DEGREE,
        "mean_degree": round(2 * m / n, 3) if n else 0,
        "density": round(nx.density(G), 4),
        "n_isolates": len(isolates),
        "n_components": nx.number_connected_components(G),
    }
    metrics.update(compute_validation(G, nodes))

    print("\n--- graph metrics ---")
    for k, v in metrics.items():
        print(f"  {k:26s} {v}")
    q = metrics.get("modularity_hdbscan")
    if isinstance(q, float) and not np.isnan(q):
        verdict = "strong" if q > 0.3 else "weak"
        print(f"\n  Q={q} -> {verdict} community structure "
              f"under the HDBSCAN partition.")

    # persist
    SIM_OUT.parent.mkdir(parents=True, exist_ok=True)
    np.save(SIM_OUT, sim)
    GRAPH_OUT.parent.mkdir(parents=True, exist_ok=True)
    nx.write_graphml(G, GRAPH_OUT)
    METRICS_OUT.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(list(metrics.items()), columns=["metric", "value"]).to_csv(
        METRICS_OUT, index=False
    )
    plot_graph(G, nodes, PREVIEW_OUT)

    print(f"\nWrote {GRAPH_OUT}")
    print(f"Wrote {SIM_OUT}")
    print(f"Wrote {METRICS_OUT}")
    print(f"Wrote {PREVIEW_OUT}")


if __name__ == "__main__":
    main()
