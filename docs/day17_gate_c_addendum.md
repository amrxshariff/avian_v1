---
title: "Network Visualiser — Day 17 Addendum"
subtitle: "Items logged during Gate C"
date: "9 September 2026"
---

> **Correction note — 21 September 2026 (D-42).** The needs-review figures here were inflated by a classifier defect: API batches cut off at the token limit were cached as if the model had declined to classify them. At 442 rows the corrected figure is **128 (29.0%), not 183 (41.4%)**. This addendum explains the rise from 168/430 (39.1%) to 183/442 (41.4%) as newer titles drifting toward less classifiable strings. **That explanation is withdrawn**: it was never tested, and the rise is at least partly the defect. The addendum below is left as written. See `docs/d42_failure_record.md` for the cause, the evidence and the fix.


# Day 17 addendum — items logged during Gate C

Logged 9 September 2026. Everything below existed only in conversation until
now. Gate C steps 1–3 passed before these were written; none of them block the
gate.

This document is intended to be appended to
`docs/project_state_decision_log.md`, which remains the canonical decision log.

---

# Open defects

## D-28b — graph artefact drift is undetected by design

`centrality.py` rebuilds the graph in memory via `graph.py`'s `load_nodes`,
`choose_threshold` and `build_graph`, then writes `network_nodes.csv` itself. It
never reads `graph.graphml`. So if `src.graph` is not re-run after an export
change, `graph.graphml`, `similarity.npy`, `network_preview.png` and the tracked
`graph_metrics.csv` silently describe a network that no longer exists, while
every consumer downstream continues to work correctly.

This was found on 8 September with `graph_metrics.csv` at 430 nodes against a
442-row table, and cured by re-running `src.graph`. D-28 is closed. D-28b is the
permanent fix: `centrality.py` should assert its node count against
`graph_metrics.csv` and fail loudly on disagreement. Recurs on every export
change until built.

**Phase:** P2.9.

## D-29 — FINAL_PARAMS duplicated across projection modules

`projection.py:51` and `projection_3d.py:44` each carry
`{"n_neighbors": 15, "min_dist": 0.1}`. Only `projection.py` runs the sweep, so
the constant governing the rendered 3D canvas has no evidence attached to it and
can drift from the one that does. Two-paths condition of the kind P2.8b exists
to eliminate.

**Phase:** P2.9.

**Related finding, not a defect.** On the 442-row sweep, `15 / 0.1` scores
0.9474 and ranks fifth of twelve, behind `10 / 0.0` at 0.9595. The constant is
retained deliberately. `min_dist=0.0` maximises trustworthiness by collapsing
points onto each other, which is good for the metric and bad for a canvas meant
to be read; `n_neighbors=10` buys local fidelity by discarding the global
structure the product sells. Choosing 0.9474 for legibility is the trade, and it
is stated here rather than left for a reviewer to find in the sweep file.

## D-30 — matplotlib is an undeclared dependency

Imported at module level by `graph.py` (lines 38, 41), `projection.py` (line 32)
and `clustering.py` (lines 138, 140), and absent from `requirements.txt`. A
fresh clone cannot run the rebuild chain. `app.py` and `canvas.py` do not import
it, so the deployed dashboard is unaffected. Resolved by D-31.

**Phase:** P2.9.

## D-31 — no build/runtime manifest split

`requirements.txt` is a development manifest. Deploying from it installs
`sentence-transformers` (and torch), `hdbscan`, `umap-learn`, `scikit-learn`,
`pyvis`, `faker` and `pytest`, none of which `app.py` or `canvas.py` import at
runtime — the dashboard reads `network_nodes.csv` and `projected_3d.csv`, and
the model stack is build-time only. Very heavy cold start against a Community
Cloud resource ceiling that has never been tested.

Fix: split into a build manifest and a runtime manifest, verified by importing
`app.py` in a clean venv containing only the runtime set. This also disposes of
D-30 cleanly — matplotlib goes in the build manifest and never reaches the
deployed app.

**Phase:** blocks P2.9.

## D-32 — the review queue is a fourth coverage surface

D-18 was scoped to three derivation sites: the summaries panel, the chat panel
and the header. The review queue panel was never enumerated and kept the old
phrasing. On a cold start it reads "183 of 183 still need review", the exact
stutter the header now suppresses when `n == m`; after a restore it correctly
reads "5 of 183", so only the equal-values branch is missing.

Fix after Gate C, together with a grep for any other `{n} of {m}` construction.

## D-33 — the embeddings cache is keyed on row count, not content

`compute_embeddings` returns the cached matrix whenever
`cached.shape[0] == len(people)`, and `main()` exposes no `recompute` flag. Edit
a title without changing the row count and the stale 384-dimension vectors are
reused through clustering, projection, graph and centrality, while the node
table displays the new titles. It fails silently and looks correct.

Current mitigation is procedural: delete `data/cache/embeddings.npy` before any
rebuild following an export change. The real fix is a content hash — noted in
the module docstring as a Stage 2 upgrade.

**Phase:** P2.9. The procedural step must be in the README before then.

## D-34 — stale comment block in app.py

`app.py:144–148` still narrates the pre-D-18 counter phrasing
("168 need review · 168 remaining", "167 of 168 · 1 resolved"), which no longer
matches the code shape below it. Cosmetic, but comment drift has caused at least
two misreadings in this codebase, which is why it gets a number rather than a
mention.

## Action — confirm D-26 and D-27

Both appear in the commit log but neither has a definition recoverable from
history. Confirm they are genuinely closed before any gate record claims a clean
board.

---

# Untested execution paths

Not defects. Recorded so the gate log is honest about what was never exercised.

**`MISS_TITLE_CHANGED` and the mixed-kind restore render.** Gate C step 2
exercised `MISS_NO_MATCH` on a note only, and step 13 cannot reach the other
branch because titles cannot move inside a single session. First real execution
will be a user's second upload against a changed export. Cheap pre-flight: a
copied session JSON with one entry's `role` altered — no rebuild, no API spend.

**`SidecarMismatch`.** Raised by the loader when the 3D sidecar disagrees with
the base table. Has never fired.

---

# Backlog

## P3.12 — re-import correction churn

Between the July and September exports, 114 of 430 people changed their
headline, several across SOC major group boundaries ("Head of Corporate
Communications" to "Sales Executive"; "Security Supervisor" to "Internship").
Corrections key on `name|role`, so every one of those returns as
`MISS_TITLE_CHANGED` and goes back to grey. That is correct — a verdict about
the old title has no authority over the new one — but it means a user pays the
review tax again on people they have already reviewed, every time they
re-upload.

The backlog also grew faster than the network: 168/430 (39.1%) became 183/442
(41.4%), because the new titles drift toward less classifiable strings —
"Internship", "Graduate Trainee", "Industrial Placement", "Ride Leader". Input
drift, not classifier decay; `reclassified: 0` rules out the latter.

Candidate mitigation: when a title changes but the person is the same, offer to
carry the prior correction forward as a *suggestion* the user confirms, never as
a silent re-application.

**Phase:** 3, alongside P3.10.

## P3.13 — chat history in the session file

Chat exchanges are lost on refresh. The session file persists corrections,
notes and About text but not the conversation, so a user who asks a good
question and closes the tab loses the answer.

Deferred to Phase 3 rather than built now: the mechanism is a P2.8c extension,
but its value depends on P3.1 team composition answers, which are the content
worth keeping. Building it against search-grade answers would under-specify it.

**Design question to resolve before implementation.** The session file currently
holds only what the user wrote. Chat history holds generated prose naming
connections, which changes the disclosure obligation on the download panel.
Preferred option: an explicit opt-in checkbox at download, keeping the default
file as honest as it is today. Alternatives are inclusion by default with an
expanded warning, or a separate file.

**Phase:** 3.

---

# Gate C — verdict

**Closed 9 September 2026 at 13 of 13.** One continuous browser session, no
restart, no crash, on the 442-row table.

| Step | Verdict |
|---|---|
| 1 Cold start — four surfaces agree | PASS |
| 2 Restore, banner reports by kind | PASS |
| 3 Live search on keystroke | PASS |
| 4 Search by SOC group name | PASS |
| 5 Zero-match empty state | PASS |
| 6 Clear via ✕ | PASS |
| 7 Needs-review card renders | PASS |
| 8 Assign a group, live update | PASS |
| 9 Review queue skip and assign | PASS |
| 10 Note, tagged and searchable | PASS |
| 11 About text and privacy note | PASS |
| 12 Grounded chat, caption still agrees | PASS |
| 13 Round trip, idempotent | PASS |

Gate B verified features in isolation. Gate C verified they compose across a
session carrying two corrections, a not-an-occupation, a skip, a note, About
text and a chat exchange, with all four coverage surfaces still agreeing at the
end.

Executed live for the first time in this gate: both branches of the D-18
counter wording, the D-12 nonce-bump clear, the D-23 bordered restore
container, `STATE_NOT_OCCUPATION` from the queue surface, the empty-set
`match_indices` sentinel, notes reaching `filter_nodes`, and a
restore-of-a-restore round trip.

**Caveat on step 2.** It was verified against a temporary 441-row table created
by removing one connection from the export to exercise `MISS_NO_MATCH`. The
export was subsequently restored and the chain rebuilt to 442, reproducing the
graph exactly. The step-2 state is not reproducible from the current artefacts.

---

# Methodology findings

Two claims the write-up makes that had never been tested, both evidenced on
9 September.

## End-to-end determinism

`projected_3d.csv` and a copy generated by a separate run of
`src.projection_3d` returned identical SHA-256 hashes, and `graph_metrics.csv`
came back byte-identical across a full delete-and-rebuild cycle (embeddings
deleted, whole chain re-run) at τ=0.6258, 1769 edges, 86 isolates.
`random_state=SEED` reproduces the layout across runs, not merely within one.

## Classification stability across rebuilds

`tools/diff_rebuild.py` compared the 430-row and 442-row tables keyed on
`(name, role)`: 316 people present in both with unchanged name and title, of
whom **0 were reclassified**. The drop from 262 to 259 classified is fully
explained by departures, not by non-determinism in the Claude classifier.
Corrections made against an earlier export remain trustworthy. Sampling
confirmed the 114 title moves are genuine headline edits, not whitespace, case
or truncation artefacts, so the instrument is sound.

## Graph metrics, 430 to 442

| Metric | 430 | 442 |
|---|---|---|
| n_edges | 1720 | 1769 |
| threshold_tau | 0.6205 | 0.6258 |
| mean_degree | 8.0 | 8.005 |
| n_isolates | 82 (19.1%) | 86 (19.5%) |
| n_components | 102 | 104 |
| modularity_hdbscan | 0.3352 | 0.3429 |
| modularity_greedy | 0.6731 | 0.7144 |

The isolate count is proportionally stable — the earlier 19.5% flag was not a
regression. Mean degree held to target. The eigenvector diagnostic reports
167/442 nodes collapsing to approximately zero, re-earning the PageRank decision
on the current table rather than inheriting it from Day 7.

---

*Data attribution: this project includes information from the O\*NET 30.3
Database by the U.S. Department of Labor, Employment and Training Administration
(USDOL/ETA), used under the CC BY 4.0 license. O\*NET® is a trademark of
USDOL/ETA.*
