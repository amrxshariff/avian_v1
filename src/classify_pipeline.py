"""
src/classify_pipeline.py — Phase 1.5 close-out: SOC classification as the
grouping mechanism, replacing HDBSCAN.

Why this shape
--------------
HDBSCAN is dead for grouping (336/371 singletons, no density; see methodology
note). Config E — Claude, title-only — is the chosen classifier: 63.5% precision
/ 74% coverage / 0 fabrications on the blind 100, at the human ceiling.

But graph.py and centrality.py already consume two files with a fixed schema:
    data/cache/clustered.csv        person_index, cluster, is_outlier, probability
    data/labels/cluster_labels.csv  cluster_id, cluster_name, size, top_terms
Rather than rewrite three downstream modules, this module REGENERATES those two
files from SOC major groups instead of HDBSCAN. The contract is identical, so
graph.py / centrality.py run unchanged — the SOC major group IS the "cluster",
and its 2-digit code IS the cluster id.

The one addition to the contract: an `is_uncertain` column. Titles the
classifier abstains on (~26%) are the product's grey "needs review" nodes —
visible uncertainty, not hidden guesses. They are placed in a single
"Unclassified" group (id 99) and flagged, so the dashboard can render and let
the user confirm them.

`cluster` is the integer form of the 2-digit SOC code (11, 13, 15, ...);
abstains are 99. This keeps the column integer-typed as graph.py expects while
remaining human-decodable.

Run from the repo root (needs ANTHROPIC_API_KEY):
    python -m src.classify_pipeline
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from src.claude_classifier import classify_claude, classify_claude_outcome
from src.dashboard.state import (
    NOT_CLASSIFIED,
    NOT_CLASSIFIED_NAME,
    STATUS_ABSTAINED,
    STATUS_ASSIGNED,
    STATUS_COLUMN,
    STATUS_NOT_CLASSIFIED,
)
from src.dashboard.unclassified import REASON_COLUMN
from src.ingestion import load_profiles
from src.onet import MAJOR_GROUP_NAMES

# Same paths graph.py / centrality.py already read — this is a drop-in.
CLUSTERED_CSV = Path("data/cache/clustered.csv")
LABELS_CSV = Path("data/labels/cluster_labels.csv")
CLASSIFIED_CSV = Path("data/cache/classified.csv")  # richer per-person record

UNCLASSIFIED_CODE = "99"
UNCLASSIFIED_INT = 99
UNCLASSIFIED_NAME = "Needs review"

# config E: title only, no company. Company hurt precision in 4 runs.
USE_COMPANY = False


def classify_people(people, *, partial: bool = False, client=None,
                    cache_path=None, unclassified_reason=None,
                    meters=None) -> pd.DataFrame:
    """Classify every person's title once (deduped), return a per-person frame
    aligned to load_profiles() order (so person_index joins downstream).

    partial=False (the command-line chain): a title nobody can answer raises,
    because a file written from a run with holes in it is a file that lies.

    partial=True (the P2.9b build function): failures come back as rows in the
    fourth state instead, carrying the reason. The frame is otherwise identical,
    so everything downstream reads one schema either way.

    Three columns say what the classifier did, and they must agree, because
    state.py raises if they do not:
      classification_status  assigned | abstained | not_classified
      unclassified_reason    set only when not_classified
      is_uncertain           True ONLY for abstained — never for a failed call
    """
    # Dedup: 430 people over ~371 titles — classify each distinct title once.
    distinct = list(dict.fromkeys(p.role.strip() for p in people if p.role.strip()))
    items = [(t, "") for t in distinct]  # USE_COMPANY False -> empty company

    kwargs = {}
    if client is not None:
        kwargs["client"] = client
    if cache_path is not None:
        # Not coerced if it is already a cache (D-71). Path() on a mapping
        # raises TypeError, so coercing here would fail every session build.
        kwargs["cache_path"] = (
            cache_path if isinstance(cache_path, dict) else Path(cache_path)
        )

    reason_by_title: dict[str, str] = {}
    if unclassified_reason is not None:
        # No classifier at all: the same frame, with everyone in the fourth
        # state. Built through this function rather than beside it so the row
        # assembly has one implementation — a second one would agree until the
        # day the schema changed.
        by_title: dict = {}
        reason_by_title = {t: unclassified_reason for t in distinct}
    elif partial:
        # meters is scoped to this branch, not the shared kwargs: classify_claude
        # (the raising, non-partial chain below) has no meters parameter, and
        # nothing metered should ever call it.
        if meters is not None:
            kwargs["meters"] = meters
        outcome = classify_claude_outcome(items, **kwargs)
        by_title = dict(zip(distinct, outcome.answers))
        reason_by_title = {distinct[i]: r for i, r in outcome.failures.items()}
    else:
        by_title = dict(zip(distinct, classify_claude(items, **kwargs)))

    rows = []
    for i, p in enumerate(people):
        title = p.role.strip()
        c = by_title.get(title)
        reason = reason_by_title.get(title)

        if reason is not None:
            # Nobody judged this title. Not "99", which means the model looked
            # and declined, and not is_uncertain, which would put this person
            # in a review backlog they were never part of (D-42).
            soc, name = NOT_CLASSIFIED, NOT_CLASSIFIED_NAME
            status, uncertain = STATUS_NOT_CLASSIFIED, False
            tier, confidence = "", 0.0
        else:
            assigned = (
                c is not None and c.tier == "claude" and c.soc_major is not None
            )
            soc = c.soc_major if assigned else UNCLASSIFIED_CODE
            name = MAJOR_GROUP_NAMES.get(soc, UNCLASSIFIED_NAME)
            status = STATUS_ASSIGNED if assigned else STATUS_ABSTAINED
            uncertain = not assigned
            tier = c.tier if c is not None else "abstain"
            confidence = c.score if c is not None else 0.0

        rows.append({
            "person_index": i,
            "id": p.id,
            "name": p.name,
            "role": p.role,
            "company": p.company,
            "soc_major": soc,
            "soc_name": name,
            "is_uncertain": uncertain,
            "classifier_tier": tier,
            "classifier_confidence": confidence,
            STATUS_COLUMN: status,
            REASON_COLUMN: reason or "",
        })
    return pd.DataFrame(rows)


def write_cluster_files(classified: pd.DataFrame) -> None:
    """Emit the two HDBSCAN-shaped files graph.py / centrality.py consume.

    cluster       = int(soc_major)  (99 for unclassified)
    is_outlier    = is_uncertain    (unclassified nodes behave like old noise:
                                     kept, rendered, but not part of a real group)
    cluster_name  = SOC major group name
    """
    pending = classified[classified[STATUS_COLUMN] == STATUS_NOT_CLASSIFIED] \
        if STATUS_COLUMN in classified.columns else classified.iloc[0:0]
    if len(pending):
        # These files carry an integer cluster per person, so there is nowhere
        # to put "never answered" without it becoming 99 — the abstain code —
        # on disk. A partial build belongs in memory (P2.9b), not here.
        raise ValueError(
            f"{len(pending)} people are {STATUS_NOT_CLASSIFIED}; the cluster "
            "files cannot represent that state. Re-run the chain until the "
            "classification completes."
        )

    clustered = pd.DataFrame({
        "person_index": classified["person_index"],
        "cluster": classified["soc_major"].astype(int),
        "is_outlier": classified["is_uncertain"],
        "probability": classified["classifier_confidence"],
    })
    CLUSTERED_CSV.parent.mkdir(parents=True, exist_ok=True)
    clustered.to_csv(CLUSTERED_CSV, index=False)

    # cluster_labels.csv: one row per SOC group present.
    present = classified[~classified["is_uncertain"]]
    labels = (present.groupby(["soc_major", "soc_name"])
              .size().reset_index(name="size")
              .rename(columns={"soc_major": "cluster_id", "soc_name": "cluster_name"}))
    labels["cluster_id"] = labels["cluster_id"].astype(int)
    labels["top_terms"] = labels["cluster_name"]  # schema parity; SOC name is the label
    labels = labels[["cluster_id", "cluster_name", "size", "top_terms"]] \
        .sort_values("cluster_id").reset_index(drop=True)
    LABELS_CSV.parent.mkdir(parents=True, exist_ok=True)
    labels.to_csv(LABELS_CSV, index=False)

    # Rich per-person record (Phase-2 dashboard reads is_uncertain from here).
    CLASSIFIED_CSV.parent.mkdir(parents=True, exist_ok=True)
    classified.to_csv(CLASSIFIED_CSV, index=False)


def main() -> None:
    people = load_profiles()
    print(f"Classifying {len(people)} people "
          f"({'title+company' if USE_COMPANY else 'title only'}, config E)...\n")

    classified = classify_people(people)

    n = len(classified)
    n_uncertain = int(classified["is_uncertain"].sum())
    n_classified = n - n_uncertain
    print(f"  classified : {n_classified}/{n} ({100 * n_classified / n:.1f}%)")
    print(f"  uncertain  : {n_uncertain} ({100 * n_uncertain / n:.1f}%) "
          f"-> grey 'needs review' nodes\n")

    dist = (classified[~classified["is_uncertain"]]
            .groupby(["soc_major", "soc_name"]).size()
            .sort_values(ascending=False))
    print("  SOC major groups found:")
    for (code, name), size in dist.items():
        print(f"    {code}  {name[:44]:<46} {size:>3}")

    write_cluster_files(classified)
    print(f"\nWrote {CLUSTERED_CSV}")
    print(f"Wrote {LABELS_CSV}")
    print(f"Wrote {CLASSIFIED_CSV}")
    print("\ngraph.py and centrality.py now run unchanged on SOC groups.")


if __name__ == "__main__":
    main()