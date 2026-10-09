"""
src/build.py — P2.9b: one function that turns a raw LinkedIn export into a
network, in memory.

Why this exists
---------------
The command-line chain is seven modules writing eight files to disk, in an
order only the README knows. Three consumers now need the same result — the
app, the API (item 6) and the MCP server (item 7) — and three copies of that
sequence would drift apart within a week. This is the one place that knows it.

What it does NOT do
-------------------
Write anything. A raw export is real people's names, so the build holds one
network in memory and hands it back; nothing is persisted, and nothing is left
behind when the session ends. The classification cache is the single exception,
and it stores only (title -> group), never a person.

Order matters, and not for the reason it looks like
---------------------------------------------------
    parse -> embed -> project -> graph -> centrality -> classify

Classification is LAST because the layout does not depend on it. Edges come
from cosine similarity over the embeddings, and the 3D coordinates from UMAP
over the same matrix; the classifier only colours what is already there. That
is what makes a partial result honest rather than a half-drawn picture: when
the classifier fails for 12 people, those 12 still have positions, still have
edges, and still appear on the canvas — as themselves, not as a gap.

The chain reads clustered.csv in projection_3d.load_inputs() purely to align
person_index. That ordering dependency does not exist here.

Partial results
---------------
See docs/p2_9b_partial_failure.md. The short version: a build that loses some
classifications returns the whole network, says so, and says who is missing and
why. Only bad input raises.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

from src.classify_pipeline import classify_people
from src.config import GRAPH_TARGET_MEAN_DEGREE, UMAP_PARAMS
from src.dashboard.keys import KEY_NONE
from src.dashboard.state import STATUS_COLUMN, STATUS_NOT_CLASSIFIED
from src.dashboard.unclassified import REASON_COLUMN
from src.failure_reasons import REASON_BUDGET_REACHED, REASON_NO_KEY
from src.claude_classifier import MODEL, count_uncached_titles
from src.spend import BudgetExceeded, Meters, estimate_titles

# The dashboard reads these. umap_x/umap_y from the canonical CSV are absent by
# design: nothing in the dashboard reads them, and computing a second UMAP to
# fill columns no one looks at would cost a fit for nothing.
NODE_COLUMNS: tuple[str, ...] = (
    "person_index", "id", "name", "role",
    "soc_major", "soc_major_name",
    "umap_3d_x", "umap_3d_y", "umap_3d_z",
    "degree_centrality", "strength", "betweenness", "pagerank", "closeness_wf",
    "is_uncertain", "classifier_tier", "classifier_confidence",
    STATUS_COLUMN, REASON_COLUMN,
)

# UMAP needs neighbours to have neighbours. Below this there is no structure to
# find and the fit is meaningless rather than merely noisy.
MIN_PEOPLE = 5

# No hard cap (decided 24 September). MAX_PEOPLE is None, so an export of any
# size is attempted.
#
# The risk this accepts, stated once here rather than rediscovered later: the
# only measured point is 442 people at 1,332 MB peak against Community Cloud's
# 3,072 MB, and UMAP's memory is not linear in the row count. A build that
# exceeds the ceiling does not fail politely — the container is killed, which
# takes the app down for everyone using it, not just the person who uploaded.
#
# WARN_PEOPLE is the size above which the upload panel says so before
# starting. Set MAX_PEOPLE to a number once the spike has measured one.
MAX_PEOPLE = None
WARN_PEOPLE = 1500

# Degree targeting picks the threshold that gives the average node the desired
# number of edges. On a small or a scattered network that target can fall below
# zero similarity, which would join people the embedding says are actively
# UNLIKE each other, and hand networkx negative edge weights — pagerank then
# fails to converge and closeness raises. A floor of zero says the obvious
# thing: no edge is better than a meaningless one.
MIN_TAU = 0.0

PROMPT_VERSION = "config-e"


class InvalidExport(ValueError):
    """The upload is not a usable LinkedIn export.

    The one failure that raises. Everything else — a dead key, a busy service,
    an exhausted budget — is reported in the result, because by then there is a
    real network to show. Here there is nothing.
    """


@dataclass(frozen=True)
class BuildResult:
    """One network, plus an honest account of what is missing from it.

    `unclassified` maps person_index to a reason, and is empty exactly when
    `complete` is True. Every person in `nodes` has coordinates whether or not
    they have a group.
    """

    nodes: pd.DataFrame
    complete: bool
    unclassified: dict[int, str] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)

    @property
    def people(self) -> int:
        return len(self.nodes)

    @property
    def reasons(self) -> set[str]:
        return set(self.unclassified.values())


# --- input -------------------------------------------------------------------


def _load_people(export: Path | str | None, people=None,
                 stats: Optional[dict] = None) -> list:
    """Parse the export, or accept already-parsed people (tests, the demo).

    Every parse failure becomes InvalidExport with a sentence the user can act
    on. The underlying errors — FileNotFoundError, KeyError on a column,
    UnicodeDecodeError — are accurate but describe the file to a programmer.
    """
    if people is not None:
        parsed = list(people)
    else:
        if export is None:
            raise InvalidExport("No export was provided.")
        from src.linkedin import load_linkedin_profiles

        try:
            parsed = load_linkedin_profiles(export, stats=stats)
        except FileNotFoundError as exc:
            raise InvalidExport(f"That file could not be found: {exc}") from exc
        except KeyError as exc:
            raise InvalidExport(
                "That CSV does not look like a LinkedIn connections export. "
                "It should have First Name, Last Name, Company and Position "
                "columns. Export yours from LinkedIn under Settings > Data "
                "privacy > Get a copy of your data."
            ) from exc
        except (UnicodeDecodeError, pd.errors.ParserError, ValueError) as exc:
            raise InvalidExport(
                f"That file could not be read as a CSV: {exc}"
            ) from exc

    if not parsed:
        raise InvalidExport(
            "That export has no usable rows. Every row needs a name and either "
            "a position or a company."
        )
    if len(parsed) < MIN_PEOPLE:
        raise InvalidExport(
            f"That export has {len(parsed)} people. At least {MIN_PEOPLE} are "
            "needed to place a network: below that there is no structure to "
            "find."
        )
    if MAX_PEOPLE is not None and len(parsed) > MAX_PEOPLE:
        raise InvalidExport(
            f"That export has {len(parsed)} people, and the limit is "
            f"{MAX_PEOPLE}. Larger networks have not been measured on this "
            "host yet, and a build that runs out of memory takes the app down "
            "for everyone."
        )
    if not any(p.role.strip() for p in parsed):
        raise InvalidExport(
            "No one in that export has a position, so there is nothing to "
            "classify or to group by."
        )
    return parsed


# --- layout ------------------------------------------------------------------


def _umap_params(n_people: int) -> dict:
    """UMAP settings for a network of this size.

    n_neighbors is clamped to n-1: the configured 15 is meaningless on a
    12-person network and umap raises on it. Clamping is honest — a small
    network genuinely has fewer neighbours — where padding the matrix would not
    be.
    """
    params = dict(UMAP_PARAMS)
    params["n_neighbors"] = max(2, min(params["n_neighbors"], n_people - 1))
    return params


def _default_embed(people: list, cache_path: Path | str | None) -> np.ndarray:
    """The real encoder. Imported here so the module loads without torch."""
    from src.embeddings import compute_embeddings

    return compute_embeddings(people, cache_path=cache_path)


def _default_project(embeddings: np.ndarray, **params) -> np.ndarray:
    """The real 3D projection. Imported here so the module loads without umap."""
    from src.projection_3d import run_umap_3d

    return run_umap_3d(embeddings, **params)


def _layout(people: list, embeddings_cache: Path | str | None,
            embed=None, project=None):
    """Embeddings, 3D coordinates, the similarity matrix and the graph.

    Nothing here consults the classifier, which is the property that makes a
    partial build renderable.

    `embed` and `project` are injected for the same reason the notes overlay
    is: the two heavyweight steps cost 36 s and 1.1 GB to import, and a test
    about what happens when a KEY dies should not need torch to find out.
    """
    from sklearn.metrics.pairwise import cosine_similarity

    from src.graph import build_graph, choose_threshold

    emb = (embed or _default_embed)(people, embeddings_cache)
    coords = (project or _default_project)(emb, **_umap_params(len(people)))

    sim = cosine_similarity(emb)
    np.fill_diagonal(sim, 0.0)
    tau = max(MIN_TAU, choose_threshold(sim, GRAPH_TARGET_MEAN_DEGREE))

    skeleton = pd.DataFrame({
        "person_index": range(len(people)),
        "id": [str(p.id) for p in people],
        "name": [p.name for p in people],
        "role": [p.role for p in people],
        # graph.build_graph reads these; they carry no classification here and
        # are replaced by the real values below.
        "cluster": 0,
        "cluster_name": "",
        "is_outlier": False,
        "x": coords[:, 0],
        "y": coords[:, 1],
    })
    graph = build_graph(skeleton, sim, tau)
    return emb, coords, graph, tau


# --- the build ---------------------------------------------------------------


def build_network(
    export: Path | str | None = None,
    *,
    people=None,
    client=None,
    cache_path: Path | str | dict | None = None,
    embeddings_cache: Path | str | None = None,
    model: str = MODEL,
    # No default (D-63): KEY_PROJECT here recorded a specific, checkable claim
    # about whose credit paid for a classification, for every caller that
    # forgot to say. retry_unclassified has always taken None; these now
    # agree.
    source: Optional[str] = None,
    classify: bool = True,
    embed=None,
    project=None,
    meters: Meters | None = None,
) -> BuildResult:
    """Build one network from a raw export.

    Raises InvalidExport, and nothing else, for input that cannot make a
    network. A classification that fails part-way returns a complete network
    with `complete=False` and the people it could not place.

    `classify=False` skips the classifier entirely and returns everyone in
    the fourth state, reason `no_key`. The network is complete and on screen;
    only the groups are missing, and a later retry fills them in without
    moving anybody.

    `meters`, injected, is the free-tier gate on the project key. Checked here
    ONCE before classification starts (the pre-flight estimate) and again per
    batch inside classify_claude_outcome (the mid-build stop) — refusing up
    front means nobody is classified rather than spending most of a cap on a
    build that was going to be stopped partway anyway. None (a keyless build,
    or a build on the visitor's own key) means unmetered.

    `embeddings_cache` defaults to None, which computes in memory and writes
    nothing: a raw export is real people's names, and the session build does
    not leave their vectors on a shared disk. A path is safe to pass — the
    cache is keyed on content, so two networks never share a file.

    `cache_path` defaults the same way and for the same reason: a mapping
    private to this build, classified once and then discarded. Pass a path to
    use the shared file — tools/build_demo.py does, because the demo ships its
    cache. A caller that passes a session-scoped mapping gets the saving
    across builds within that session, which is what the upload panel does.

    A classify=False build (tools/diag_canvas.py) reads this cache through
    count_uncached_titles and never writes it. With the default it reads an
    empty mapping, so the uncached figure counts every title; that build does
    not use the figure, and a caller that needs it should pass a cache.
    """
    from src.centrality import compute_centrality

    # None means a cache private to this build (D-71), matching
    # embeddings_cache above it. These two sat adjacent with the same type and
    # the same default and opposite meanings for it, and the classification
    # one wrote 365 real titles to a tracked file before anyone noticed.
    #
    # A fresh dict here rather than a default argument: a mutable default is
    # bound once at import and shared by every call, which is the same class
    # of mistake D-64 fixed one module over.
    cache_path = {} if cache_path is None else cache_path

    intake: dict = {}
    parsed = _load_people(export, people, stats=intake)
    _, coords, graph, tau = _layout(parsed, embeddings_cache, embed, project)

    # classify=False builds the whole network with no classifier at all:
    # everyone placed, every edge drawn, nobody grouped. Possible only because
    # of option B — the fourth state already means "no answer yet", and every
    # surface already knows how to show it. It is what lets someone see their
    # own network before deciding whether to spend anything on it.
    unclassified_reason = None if classify else REASON_NO_KEY

    # Hoisted out of the meters branch: a cache read over a few hundred rows
    # costs nothing next to the build that follows, and the figure is needed
    # whether or not a meter is watching. A keyless build is exactly the one
    # whose number gets quoted later, when a key arrives.
    uncached = count_uncached_titles(parsed, cache_path)

    if meters is not None and unclassified_reason is None:
        # Mandatory pre-flight on the project key: an automatic classification
        # means a stranger's export starts spending the moment it lands, so the
        # estimate refuses the build rather than starting it. Uncached titles
        # only — a cached title costs nothing.
        try:
            meters.check(estimate_titles(uncached))
        except BudgetExceeded:
            unclassified_reason = REASON_BUDGET_REACHED

    classified = classify_people(
        parsed, partial=True, client=client, cache_path=cache_path,
        unclassified_reason=unclassified_reason, meters=meters,
    )
    if meters is not None and unclassified_reason is None:
        # The ledger's network tally — design §6.4's "free networks a day".
        # Counted only when classification ran: a build refused at the
        # pre-flight cost nothing.
        meters.daily.record_network()

    # One row per person, in both frames, joined on person_index. The old chain
    # filled a missing is_uncertain with False here, which turned a person
    # absent from the classifier's output into a CLASSIFIED one (D-54). An
    # in-memory build has no reason to tolerate that: validate and fail.
    centrality = compute_centrality(graph)
    nodes = (
        pd.DataFrame({
            "person_index": range(len(parsed)),
            "id": [str(p.id) for p in parsed],
            "name": [p.name for p in parsed],
            "role": [p.role for p in parsed],
            "umap_3d_x": coords[:, 0],
            "umap_3d_y": coords[:, 1],
            "umap_3d_z": coords[:, 2],
        })
        .merge(centrality, on="id", how="left", validate="one_to_one")
        .merge(
            classified[[
                "person_index", "soc_major", "soc_name", "is_uncertain",
                "classifier_tier", "classifier_confidence",
                STATUS_COLUMN, REASON_COLUMN,
            ]].rename(columns={"soc_name": "soc_major_name"}),
            on="person_index", how="inner", validate="one_to_one",
        )
    )
    if len(nodes) != len(parsed):
        raise RuntimeError(
            f"{len(parsed)} people in, {len(nodes)} out of the join. A person "
            "lost between the layout and the classification would render as a "
            "gap with nothing on screen to explain it."
        )

    pending = nodes[nodes[STATUS_COLUMN] == STATUS_NOT_CLASSIFIED]
    unclassified = {
        int(i): str(r)
        for i, r in zip(pending["person_index"], pending[REASON_COLUMN])
    }

    return BuildResult(
        nodes=nodes[list(NODE_COLUMNS)].sort_values("person_index")
                                       .reset_index(drop=True),
        complete=not unclassified,
        unclassified=unclassified,
        provenance={
            "model": model,
            "prompt_version": PROMPT_VERSION,
            "source": source,
            "tau": tau,
            # What a later classification would actually pay for. Computed
            # here because `parsed` is gone by the time the offer needs the
            # figure, and the offer must quote what will be charged rather
            # than the headcount: a rebuild of a cached export is free, and
            # "442 people will use your key" when twelve will is the
            # dishonesty this module's neighbours exist to prevent.
            "uncached_titles": uncached,
            # What the file contained versus what was used. The upload panel
            # reports it, because "442 placed" from a 456-row file invites the
            # question of where the other 14 went.
            "intake": intake,
        },
    )


# --- retry -------------------------------------------------------------------


@dataclass(frozen=True)
class _Shim:
    """The three fields classify_people needs from a person.

    A retry works from the built table, not from the export, which may be long
    gone: the user uploaded it, the session holds the network, and nothing kept
    the file.
    """

    id: str
    name: str
    role: str
    company: str = ""


def retry_unclassified(
    result: BuildResult,
    person_indices=None,
    *,
    client=None,
    cache_path: Path | str | dict | None = None,
    model: str = MODEL,
    source: Optional[str] = None,
    meters: Meters | None = None,
) -> BuildResult:
    """Classify the people a build could not, and return the updated network.

    Only the classification is redone. The embeddings, the coordinates, the
    edges and every centrality number are carried across untouched, so a retry
    can never move anybody — which is why it is safe to offer a retry at all.
    Re-running the layout would rearrange the canvas under someone who is
    mid-review, and UMAP is not guaranteed to land in the same place twice.

    Titles that succeeded first time are in the cache, so a retry pays only for
    the people it is retrying.

    `cache_path` defaults as build_network's does (D-71): None is a mapping
    private to this call, never the shared file. The app passes the session's
    mapping, the same one its builds use.

    `meters`, as for build_network: the free-tier caps on the project key,
    checked at each batch boundary (D-81). None means unmetered.
    """
    cache_path = {} if cache_path is None else cache_path
    pending = result.nodes[result.nodes[STATUS_COLUMN] == STATUS_NOT_CLASSIFIED]
    targets = [int(i) for i in pending["person_index"]]
    if person_indices is not None:
        wanted = {int(i) for i in person_indices}
        targets = [i for i in targets if i in wanted]
    if not targets:
        return result

    rows = result.nodes[result.nodes["person_index"].isin(targets)]
    shims = [
        _Shim(id=str(r["id"]), name=str(r["name"]), role=str(r["role"]))
        for _, r in rows.iterrows()
    ]
    retried = classify_people(
        shims, partial=True, client=client,
        cache_path=cache_path, meters=meters,
    )

    updated = result.nodes.copy()
    carried = [
        "soc_major", "is_uncertain", "classifier_tier",
        "classifier_confidence", STATUS_COLUMN, REASON_COLUMN,
    ]
    by_position = dict(zip(targets, range(len(retried))))
    for person_index, position in by_position.items():
        row = retried.iloc[position]
        mask = updated["person_index"] == person_index
        for column in carried:
            updated.loc[mask, column] = row[column]
        updated.loc[mask, "soc_major_name"] = row["soc_name"]

    still = updated[updated[STATUS_COLUMN] == STATUS_NOT_CLASSIFIED]
    unclassified = {
        int(i): str(r) for i, r in zip(still["person_index"], still[REASON_COLUMN])
    }
    provenance = dict(result.provenance)
    provenance["model"] = model
    if source is not None:
        previous = provenance.get("source")
        # KEY_NONE paid for nobody — a keyless build classifies no one — so
        # the offer after a key arrives is one payer, not two. An unrecorded
        # source is different: someone paid for the earlier people and
        # nothing says who.
        if previous != KEY_NONE and previous != source:
            # Whose key paid is no longer one answer. source keeps meaning
            # the most recent attempt, because that is whose key the
            # remaining failures belong to; this records that the earlier
            # people were paid for by someone else, so no surface claims a
            # single payer for the whole network (D-63's shape).
            provenance["mixed_sources"] = True
        provenance["source"] = source

    return BuildResult(
        nodes=updated,
        complete=not unclassified,
        unclassified=unclassified,
        provenance=provenance,
    )
