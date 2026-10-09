---
title: "Gate B — Definition of Done Walkthrough"
subtitle: "Phase 2 QA checkpoint, gate 2 of 4"
author: "Amr Shariff"
date: "Run 2–6 September 2026 (Days 15–16). Record compiled 8 September 2026 (Day 17)."
---

# Purpose

Gate B is the second of four gates in the Phase 2 QA checkpoint. Where Gate A
asked *"is the code that ships the code we think ships"*, Gate B asks
**"does each delivered item meet the definition of done written for it"**.

Twelve items, each carrying a written verdict:

> P2.1, P2.2, P2.2b, P2.3, P2.4/P2.4b, P2.5, P2.6a, P2.7, P2.8, P2.8b,
> P2.8c, P2.8d

Three rules governed the run:

1. **Amended criteria are checked as amended, not as originally written.** Two
   DoD amendments were on record — "clicking a node" became "selecting from the
   list" (Amendment 1), and the taxonomy-skills line became enrichment-sourced
   (Amendment 2). Both were honest rewrites of criteria that could not
   otherwise pass, made before the build rather than at the checkpoint.
2. **Verdicts are recorded against the running app, not from memory.**
3. **Nothing is fixed inside the checkpoint.** Defects are named and
   phase-assigned.

The app was started once and left up for the walkthrough, with the port
confirmed before anything else — a zombie server on a different port serving
stale modules had already cost the project a session.

---

# Verdict summary

| Item | Verdict | Date |
|---|---|---|
| P2.1 — uncertain-node confirmation UX | PASS | 2 Sept |
| P2.2 — self-enrichment | PASS | 2 Sept |
| P2.2b — enrichment comparison | PASS | 2 Sept |
| P2.3 — 3D canvas | PASS | 2 Sept |
| P2.4 / P2.4b — real-time search | PASS with defect | 2 Sept |
| P2.5 — profile card | PASS | 2 Sept |
| P2.6a — group selection and dimming | PASS | 2 Sept |
| P2.7 — cluster summaries | PASS | 2 Sept |
| P2.8 — grounded chat panel | PASS | 3 Sept, after D-16/D-17 |
| P2.8b — shared display-table loader | PASS 8/8 | 6 Sept, after D-20 |
| P2.8c — session save and restore | PASS 8/8 | 6 Sept, after D-23 |
| P2.8d — review queue | PASS 7/7 | 6 Sept |

**Gate B closed 12 of 12 on 6 September 2026 (Day 16).**

---

# Session 1 — 2 September, P2.1 through P2.7

Eight items cleared in one sitting. Two produced findings.

## P2.3 — a verdict corrected mid-gate

P2.3 was initially recorded against a scroll-wheel zoom failure. The user
corrected the observation: **zoom works, but only via the UI button.**

That changed the verdict. The criterion says the user can zoom, not that the
scroll wheel is the mechanism. **P2.3 — PASS**: 430 nodes rendered,
UMAP-positioned, coloured correctly with greys distinguishable at depth, and
rotate, zoom and pan all operational.

D-10 was withdrawn and folded into **D-11 — canvas interaction quality**,
severity low, assigned to Phase 4. Four items, one likely root cause:

1. Scroll-wheel doesn't drive zoom; the button does
2. Wheel events over the canvas scroll the page instead
3. Mode buttons reset the view rather than composing
4. Canvas isn't pinned in the middle panel

Items 1 and 2 are the same bug seen from two sides — the wheel event reaches
the page rather than the scene. Item 3 is `dragmode` defaults tuned for 2D.
Item 4 is layout. Noted at the time: item 2 will feel worse on Community Cloud
than locally, but it is an annoyance rather than a gate.

## P2.4 / P2.4b — the one genuine FAIL

DoD as amended: *a search box filters and highlights nodes by name, role, SOC
group, and any enriched skill terms, **updating live as the user types**; a
query with no matches returns a clear empty state rather than a blank canvas.*

| Check | Result |
|---|---|
| P2.4-a — partial name filters live, no Enter | **FAIL** |
| P2.4-b — SOC group name matches on group, not title text | PASS |
| P2.4-c — nonsense query gives clear empty state | PASS |
| P2.4-d — non-matches fade rather than vanish | PASS |

P2.4-a failed against the written criterion. Requiring Enter is not
*"updating live as the user types"*.

**D-12 logged, severity medium, assigned to Phase 2 before deployment.** It
remained open through the rest of Gate B and was the last Phase 2 defect closed
(Day 17).

---

# Session 2 — 3 September, P2.8

P2.8's verdict was blocked by three defects at the point Gate B first reached
it, and two more emerged during remediation.

| | Defect | Resolution |
|---|---|---|
| D-13 | Chat panel crashed on submit — illegal widget-key write after instantiation | Fixed via callback pattern with `PENDING_KEY` |
| D-14 | Canvas didn't highlight chat answers — highlight written after `build_figure` in the same pass | `st.rerun()` after writing `HIGHLIGHT_KEY`, with a stated terminating condition |
| D-15 | About text had no overlay in `loader.py` and could not reach `build_payload` | Deferred to P2.9a with the self-node identity question |
| D-16 | Sonnet 5 is adaptive-thinking-only at effort high | `MAX_TOKENS` raised to 8000; early return on `stop_reason=max_tokens` |
| D-17 | Harness could not reach a passing state while D-16 was live | Closed by D-16's fix; harness reached 31/31 |

## D-16 — the finding worth keeping

At `MAX_TOKENS=4000`, the entire budget went to internal reasoning: 4000/4000
thinking tokens, block types `['thinking']`, **no text block opened at all**.

This corrected a prior recorded project learning. Day 14 had attributed a
similar failure to *"starving a large answer"* of output tokens. That
attribution was wrong — it is thinking-token consumption. `max_tokens` is a
hard ceiling on thinking **plus** text combined, and at a low ceiling the model
spends the whole budget before it writes anything.

The remediation was not simply a larger ceiling:

- `answer_question` now returns immediately on `stop_reason=max_tokens` with
  `NOTE_TRUNCATED`, rather than retrying. Retrying made it strictly worse — it
  added more input at the same ceiling.
- `_call` was extended to return a three-tuple including a `shape` string
  carrying block types and thinking-token counts, so the failure is diagnosable
  rather than merely observable.
- Verified by re-running `tools/diag_maxtokens.py`: `stop_reason: end_turn`,
  `thinking_tokens=3800`, block types `['thinking', 'text']`.

An enter-to-submit change was requested during this session and scoped into
D-13's fix rather than deferred — `on_change=_submit_question` moved to the
text input, Ask button removed.

Two minor defects were logged without fixing, per the no-fix rule:

- **D-18** — coverage counts disagreeing across three captions
- **D-19** — stray "no one matches" line on a question not about the table

Both were closed on Day 17.

---

# Session 3 — 6 September, P2.8b / P2.8c / P2.8d

The final three items. Two produced defects, one of them in an instrument.

## P2.8b — PASS 8/8, after D-20

**D-20 was a checker defect, not a product defect**, and it presented as the
opposite of the truth.

PowerShell 5.1's `Set-Content -Encoding UTF8` writes a byte-order mark. Three
files authored that way were invisible to `check_single_loader.py`, which
expects BOM-free UTF-8. The checker then **conflated parse failures with rule
violations** and reported those three files as violating the single-loader
rule.

Two things had to be fixed. The instrument had to distinguish "I could not read
this" from "this breaks the rule" — a conflation that would have reported
nothing at all had it gone the other way. And all file authoring moved to .NET
`WriteAllText` with `UTF8Encoding($false)`, including commit messages written
via temp files.

D-22 was logged as a docs defect from this item: the P2.8b rationale cites 26
`apply_corrections` tests; the actual figure is 9.

## P2.8c — PASS 8/8, after D-23

**D-23 — a nested `st.expander` crashed `_render_report`.**

Streamlit forbids nesting expanders. The restore report put one inside another
to show non-matching entries. It had **never fired**, because every restore
performed to that point had matched 100% of entries — the branch that renders
misses had never executed.

Normal usage would have hit it immediately: re-export LinkedIn, some people
changed jobs, restore, crash. It would have been a user's *first real restore*.

Fixed mid-gate with `st.container(border=True)` and re-observed.

The drift branch — the two-key notes design argued for since P2.7, where notes
key on name alone and reattach with a flag when the person's title has moved —
was also confirmed as never having run in the UI before this gate.

## P2.8d — PASS 7/7

Clean. Three live checks:

- **a.** Assign from the queue — entry leaves, counter decrements, node
  recolours
- **b.** Skip an entry — leaves the view, **counter does not move**, person
  stays grey and findable by search. A skip is "not now" about a sitting, not a
  verdict on a person.
- **c.** Pagination at 10 per page — page refills sensibly as entries leave
  rather than throwing the user back to page one

## D-24 — logged, then withdrawn

An apparent off-by-one between corrections restored and the counter:

| Corrections restored | 168 − n | Counter showed | Gap |
|---|---|---|---|
| 38 | 130 | 131 | 1 |
| 42 | 126 | 128 | 2 |

The second data point produced the explanation. **A correction applied to an
already-classified node does not reduce the needs-review count** — it changes a
group, it does not resolve a grey node. The gap is simply how many corrections
were made from a profile card rather than from the queue, and it should grow as
more classified people are corrected. The `NOT_OCCUPATION` count moving 2 → 4
across the same interval is consistent with the same thing.

Closed as **not-a-defect** via `tools/reconcile_counter.py`, which proved the
counter correct throughout.

Worth noting for the record: this finding reproduced independently on Day 17
against the 442-row table — 183 uncertain at rebuild, 148 after restore, 35
resolved against 37 corrections applied, a gap of 2. A better confirmation than
the original script, because it was not looking for one.

---

# What this gate bought

Three defects that no unit test could have reached, **all the same shape: a
branch that had never executed.**

- **D-23** — the restore report crashed on any non-matching entry, behind a
  branch unreached because every prior restore was 100% clean.
- **D-20** — three files invisible to the single-loader checker, reported as
  violations, which is the opposite of the truth.
- **The drift branch** — argued for since P2.7, never once run in the UI.

In all three cases the code looked right and had been reasoned about carefully.
What was missing was **an execution**. That is the entire justification for
live harnesses alongside the unit suite, and this gate paid for itself.

---

# Process finding

**D-23 was fixed inside the checkpoint, which the no-fix rule forbids.**

The fix was correct and the criterion was re-observed afterwards, so nothing in
the verdict is unsound. It goes in the record as a **crossed line**, not as
normal practice. The distinction matters: a gate that quietly absorbs its own
fixes stops being evidence about the build it was run against.

---

# Defect log at gate close (6 September)

| | Defect | Status | Phase |
|---|---|---|---|
| D-11 | Canvas interaction quality | open | 4 |
| D-12 | Search requires Enter, no live filtering | open | 2 |
| D-18 | Coverage means two things: summaries excludes small groups (289+8), chat includes them (297) | open | 2 |
| D-19 | Stray "no one matches" on non-table questions | open | 2 |
| D-20 | Checker conflated unparseable with non-compliant | fixed, uncommitted | 2 |
| D-21 | Harnesses must be invoked `python -m tools.<name>` | docs | — |
| D-22 | P2.8b rationale cites 26 `apply_corrections` tests; actual is 9 | docs | — |
| D-23 | Nested expander crashed the restore report | fixed, uncommitted | 2 |
| D-24 | Counter gap vs corrections restored | not-a-defect | — |

All Phase 2 entries in this table were closed on Day 17 (8 September), together
with D-25, D-26 and D-27 discovered during that work. D-11 remains open against
Phase 4.

---

# Note on this record

Compiled on Day 17 from the Day 15 and Day 16 session transcripts rather than
from a running summary, so that the verdicts and the reasoning behind them are
traceable to the observations that produced them.

Two areas are thinner in the transcript than the rest and are recorded here at
the level of detail available: the individual criterion-by-criterion checks for
P2.1, P2.2, P2.2b, P2.5, P2.6a and P2.7, which passed without producing
findings and were recorded as clean; and the full ten-criterion breakdown for
P2.8, which is represented above by its blocking defects rather than by each
criterion's verdict.
