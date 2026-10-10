---
title: "Network Visualiser — Status and Pipeline, Day 15"
subtitle: "Current board, runtime pipeline, and the Phase 2 QA checkpoint definition of done"
author: "Amr Shariff"
date: "30 August 2026"
---

> **Correction note — 21 September 2026 (D-42).** The needs-review figure in this document, 168 of 430 (39.1%), was measured while a classifier defect was caching failed API batches as abstentions. How many of the 168 were affected cannot be recovered, because the cache does not timestamp its entries, so read the figure as an upper bound. At 442 rows the corrected figure is **128 (29.0%)**. The document below is left as written. See `docs/d42_failure_record.md` for the cause, the evidence and the fix.

> **Correction note — 29 September 2026 (D-69).** Of the three convergent measurements of the classification ceiling, only the third — Config E's 63.5% precision on the blind 100 — involves the classifier, and it is a single run. The classifier is not deterministic: five builds of an identical 442-person synthetic file, cache cleared between each, gave needs-review shares from 21.9% to 28.1%, with about 15% of titles receiving a different group between the one pair diffed. The blind 100's own spread has not been measured and may be wider at a hundred titles. The first two measurements are human and are unaffected, and the convergence argument stands on them. The document below is left as written. See `docs/defect_register.md`, D-69.


# 1. Purpose and currency

This document records where the project stands on **Day 15** of the re-baselined
19–21 focused-day plan, and defines what "done" means for the current session.

**It supersedes Sections 3 and 9 of `project_state_decision_log.pdf`.** That
document remains authoritative on *decisions and reasoning* — the Phase 1.5
pivot, the classification ceiling, the approaches ruled out with evidence, the
privacy posture. It is **stale on status**: it records the board as of 17 August,
when P2.5 was the next task and 2.5 of 9 items were complete. Six items have
shipped since. Do not read the board from it.

Last committed working session: **28 August 2026 (Day 14)**. Nothing has been
committed since. Verify with `git --no-pager log --oneline -10` before trusting
this document from that date onward.

---

# 2. Position in the plan

| | |
|---|---|
| Plan | 19–21 focused days to public launch (re-baselined from the original 17) |
| Today | Day 15 |
| Phase | Phase 2 — MVP dashboard |
| Phase 2 build work | **Complete**. All build items shipped and committed. |
| Remaining in Phase 2 | QA checkpoint (today), P2.9a, P2.9 |
| Standing instruction from Day 14 | Run the QA checkpoint against every Phase 2 DoD **before** starting P2.9a and P2.9 |

---

# 3. The pipeline as it stands today

The system is now **two pipelines**, not one. That split is recent, is a
consequence of P2.8b, and matters directly to P2.9 — the runtime half is the
part that must survive an arbitrary user upload.

## 3.1 Build-time pipeline (offline batch)

Run once against a `Connections.csv`; produces the canonical node table.

| # | Stage | Module | Input | Output |
|---|-------|--------|-------|--------|
| 1 | Ingestion | `linkedin.py`, `ingestion.py` | `Connections.csv` | `Person` objects |
| 2 | Classification | `claude_classifier.py`, `onet.py` | Job titles | SOC major group or abstain |
| 3 | Embedding | `embeddings.py` | `profile_text` | 384-dim vectors |
| 4 | Projection | `projection.py`, `projection_3d.py` | Vectors | UMAP 2D in-table; 3D sidecar |
| 5 | Graph | `graph.py` | Vectors | Cosine-similarity graph, τ = 0.7710 |
| 6 | Centrality | `centrality.py` | Graph | Canonical node table |

**Canonical handoff:** `data/graph/network_nodes.csv` — 430 rows carrying
identity, SOC group, UMAP coordinates, centrality metrics, `classifier_tier`
provenance, and the `is_uncertain` flag. This file is the contract between the
engine and the interface. It is permanently gitignored following the
`git-filter-repo` history purge.

## 3.2 Runtime pipeline (every Streamlit rerun)

`src/dashboard/loader.py` is the **single assembly path** for the display table.
There is no second route, and that is enforced rather than asserted.

```
base CSV
   └─> 3D sidecar merge      (raises SidecarMismatch with counts;
   │                          never renders a silent subset)
   └─> corrections overlay   (state.py — flat dict[int, str] by person_index)
   └─> notes overlay         (notes.py — session-scoped)
   └─> display table         (derives display_state:
                              classified / needs_review / not_occupation)
```

Enforcement: `tools/check_single_loader.py` parses source with **AST**, not
grep — adopted after a docstring mention produced a false positive. Four callers
were migrated onto the loader: `app.py`, `check_chat_grounding.py`,
`check_uncertainty_honesty.py`, `check_summary_safety.py`.

## 3.3 Dashboard layer

Every module below reads the loader's display table. None of them re-reads the
base CSV.

| Module | Responsibility |
|---|---|
| `canvas.py` | Pure `build_figure(df, match_indices, highlight_index)`; `Scatter3d` only; fixed 23-colour SOC palette drawn from the taxonomy, never from the data; scene annotations for the selected-node label |
| `search.py` | Pure `filter_nodes(df, query)` across name, role, SOC group name, notes |
| `people_list.py` | One component, two modes: search results and the review queue. Skips are session-only and record no verdict |
| `card.py` | Profile card; provenance from `classifier_tier`; confirmation control (23 groups + "not an occupation") |
| `state.py` | Correction overlay; the only write path for an assignment |
| `notes.py` | Per-person free text; `on_change` callback; empty notes delete their key |
| `enrich.py` / `self_enrichment.py` | Self-enrichment via "About" text; two calls (title-only, title-plus-About) shown side by side; no company slot; no cache |
| `summaries.py` | Lazy group summaries on selection; cache keyed on sorted `person_index` hash; groups <5 show verbatim titles; no names or company sent outbound |
| `chat.py` / `assistant.py` | Two-layer grounded chat: pure core (table in, client injected) plus Streamlit glue; prefixed string handles (`"p87"`) |
| `session_io.py` | JSON save/restore keyed on identity, not `person_index` |

## 3.4 Key numbers

| Measure | Value |
|---|---|
| People in the network | 430 |
| Distinct job titles | ~371 |
| Classified | 262 (60.9%) |
| Flagged "Needs review" | 168 (39.1%) |
| SOC major groups in taxonomy / palette | 23 |
| SOC groups actually present in the data | 18 |
| Graph threshold τ | 0.7710 |
| Modularity Q | 0.5224 |
| Components / isolates | 13 / 4 |
| UMAP trustworthiness (k=5) | 0.9840 |

The 168 is derived live from the table at every surface. It is hardcoded
nowhere. Confirming that remains a checkpoint item.

---

# 4. Phase 2 board

## 4.1 Shipped and committed

| Item | Delivered |
|---|---|
| P2.1 | Correction overlay logic (`state.py`, 9 tests); UI half landed inside P2.5 |
| P2.2 | Self-enrichment via "About" text; `self_enriched` tier |
| P2.2b | Per-person notes, session-scoped and searchable |
| P2.3 | 3D render, visually verified |
| P2.4 / P2.4b | Search panel and match-set highlight with faded non-matches |
| P2.5 | Profile cards with the P2.1 confirmation control |
| P2.6a | Group multi-select with dimming; coloured centroid labels |
| P2.7 | Lazy, cached cluster summaries |
| P2.8 | Grounded chat panel |
| P2.8b | Shared display-table loader with AST enforcement |
| P2.8c | Session save and restore |
| P2.8d | Review queue, live result cards, three-column layout |

## 4.2 Deferred out of Phase 2 by amendment

| Item | Moved to | Reason |
|---|---|---|
| P2.6 SOC-tree zoom | P3.9 | Blocked behind detailed-code resolution |
| 2D / 3D canvas toggle | Phase 4 | Cheap, but a preference layer on a working canvas |
| Non-contiguous group centroid labels | Phase 4 | Known limitation: labels sit at the lobe mean |
| Taxonomy skills on profile cards | P3.6 (group-level only) | Amendment 2 — never attributed to an individual |

## 4.3 Remaining in Phase 2

| Item | Status | Estimate |
|---|---|---|
| Phase 2 QA checkpoint | **Today** | 0.5 day |
| P2.9a — synthetic 430-row demo table | Not started | 0.5 day |
| P2.9 — Community Cloud deploy, README, zero-crash gate | Not started | 1–1.5 days |

## 4.4 Health at last commit

| Check | Result |
|---|---|
| Full test suite | 223 passing |
| `check_uncertainty_honesty.py` | 9 / 9 |
| `check_summary_safety.py` | 11 / 11 |
| `check_chat_grounding.py` | 26 / 26 |
| `check_single_loader.py` | 6 / 6 |
| Git | Clean, pushed |

These are **last session's** numbers. Re-running them on current HEAD is
checkpoint item 2, not a formality.

---

# 5. Definition of done — Day 15 (Phase 2 QA checkpoint)

Today is a checkpoint, not build work. It is done when the following are true.

1. **Every Phase 2 DoD carries an explicit written verdict.** All items in
   `phase2_4_definitions_of_done.pdf`, plus the three recorded amendments,
   including the amended criteria: list-driven selection replacing click
   selection, the enrichment-sourced skills line, and the P2.6 split. Verdicts
   are recorded against the running app, not from memory or from last session's
   transcript.

2. **All four harnesses and the full suite re-run green on current HEAD.**
   Terminal output from Day 14 does not count.

3. **One manual pass through the core interactions, no crash:** load → search →
   select → correct from the card → correct from the queue → self-enrich → add a
   note → select a group → read a summary → ask the chat two questions → save →
   refresh → restore.

4. **The needs-review counter is verified live-derived** at every surface it
   appears: header, queue, card, coverage panel. Any hardcoded 168 is a defect.

5. **The not-an-occupation count is reconciled.** Two prior sessions report this
   differently. Establish the live figure from the table and record it.

6. **Failures are logged as named defects with a phase assignment, not fixed
   inline.** Fixing during a checkpoint is how a checkpoint stops being one.

## 5.1 Deliberately excluded from today's gate

Two clauses of the written Phase 2 QA checkpoint cannot be tested before a
deployment exists, and move to P2.9's own gate:

- "the deployed app renders a real network with grey nodes present and
  correctable"
- "no real personal data in the public deploy" — this is P2.9a's entire purpose

---

# 6. What follows the checkpoint

## 6.1 P2.9a — synthetic demo table

Generate a synthetic 430-row node table with roughly a 39% unclassifiable
cohort, matching the real network's grey-node proportion, and expanded name
pools to avoid collision across 430 draws. Scheduled deliberately for
immediately before deployment, not during development, so that development ran
against real data throughout.

## 6.2 P2.9 — deployment

Streamlit Community Cloud; boots cleanly from the repo with no real personal
data present; full render without crashing; README recording local setup with a
real export; O\*NET attribution in the README and the dashboard footer; a short
demo recording.

## 6.3 Phase 3 — team composition and network insight (8–10 focused days)

P3.1 team composition queries; P3.2 complementarity ranking; P3.3 serendipity
suggestions via graph traversal; P3.4 top-connector chart from betweenness; P3.5
cluster skill matrices; P3.6 group-level occupational profiles; P3.7
complementarity by occupational distance; P3.9 SOC-tree zoom behind
detailed-code resolution. P3.8 (query expansion over notes) is ruled out on
clustering, compliance, method, and density grounds.

## 6.4 Phase 4 — polish and public launch (4–5 days)

Team synergy narratives, UI animations, dark mode, PDF export, onboarding tour,
2D/3D toggle, centroid label fix, performance documentation, public GitHub
launch.

---

# 7. Rules carried forward

These were learned through failures and are not open for re-litigation.

**Classification.** The ceiling is the input, not the method. Two-word titles top
out at ~60–64% classifiability, measured three convergent ways. Config E is
locked: Claude, title-only, no deterministic tier in front, explicit abstention
over fabrication. Do not tune further.

**Honesty.** A blank or flagged node is honest; a confident wrong one is the
worst outcome. `NOT_OCCUPATION` is strictly distinct from the `"99"`
unreviewed-abstain code. No feature presents an uncertain classification, a
similarity edge, or a centrality score as stronger than it is. The graph is a
*similarity* graph; betweenness identifies bridges between skill areas, not
social popularity, and any surface showing it must say so.

**Eval discipline.** The 50-title dev set is contaminated — labels were revised
after seeing predictions. Never quote it. The blind 100 is the real number.

**Streamlit state.** A write to a widget key must happen in a callback or above
the widget. Any `st.rerun()` must have a stated terminating condition. Four bugs
across P2.8c and P2.8d were variants of exactly this.

**Live harnesses catch what unit tests cannot.** Three chat bugs — deprecated
`temperature=0` causing a hard 400, `max_tokens` starvation indistinguishable
from a parse error, and a handle leaking into prose — were invisible to the unit
suite and found only by `tools/check_chat_grounding.py`.

**Canvas ordering.** Read `highlight_index` from session state *above*
`build_figure`, never from the panel's return value, or the previous answer's
people light up beside the current answer's text.

**Architecture.** Two-layer module pattern throughout: a pure core with no
Streamlit, no API key and full unit coverage, plus thin Streamlit glue.
Established by `state.py`, `notes.py`, `summaries.py`, `assistant.py`.
Architectural rules are enforced by AST checkers, not by grep and not by
convention.

**Environment.** `python -m src.<module>` from repo root; `python -m pip`, never
bare `pip`; `git --no-pager diff`; PowerShell `Select-String` and
`Get-ChildItem -Recurse`, not `grep` and `find`.

---

# 8. Attribution

This system includes information from the O\*NET 30.3 Database by the U.S.
Department of Labor, Employment and Training Administration (USDOL/ETA), used
under the CC BY 4.0 license. O\*NET® is a trademark of USDOL/ETA. This project
has modified some of that information. USDOL/ETA has not approved, endorsed, or
tested these modifications.
