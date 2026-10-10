# Gate C — interaction pass

> **Correction note — 21 September 2026 (D-42).** This record quotes the needs-review figure as 183 of 442 (41.4%), with 259 classified. That figure was inflated by a classifier defect: API batches cut off at the token limit were cached as if the model had declined to classify them. The corrected figures for the same 442 people are **314 classified and 128 needing review (29.0%)**. The gate's thirteen steps tested interaction and stand as recorded; the counts quoted in them (183, 182 and so on) are the inflated ones. The record below is left as written. See `docs/d42_failure_record.md` for the cause, the evidence and the fix.


**Day 17–18. Closed 13 of 13.** One continuous browser session, no restart, no
crash. No fixes applied inside the gate.

> Reconstructed from the session transcript rather than written at the time.
> Items marked **[confirm]** could not be established from the record and need
> checking before this is treated as authoritative.

## Definition of done

The gate plan of 2 September defined Gate C in a single line: *interaction pass
— thirteen steps in one sitting, no crash.* Unlike Gates A and B the steps were
never enumerated, so thirteen were proposed and approved before the gate opened.

Full DoD as run: thirteen steps executed in one continuous browser session on
the 442-row table, in order, with a written verdict per step and no restart.

Gate B verified features in isolation. **Gate C verifies that they compose** —
which is why the later steps deliberately read surfaces that Gate B had only
ever seen on a fresh session.

## Preconditions

Four, all closed before the gate opened. The third produced a finding worth
keeping:

`projected_3d.csv.bak430` was **not** a pre-rebuild snapshot despite its name —
442 rows, written after `src.projection_3d` had already run on the new export.
`network_nodes.csv.bak430` (25 July, 430 rows) is genuine. Two files shared a
suffix meaning different things; the misleading one was renamed
`projected_3d.csv.bak442_pre_graph_rerun`.

## Baseline

452 raw rows · 442 kept · 259 classified · 183 needs review · 0 not-an-occupation.

Step 1's expected values were derived fresh from `network_nodes.csv` rather than
carried over from the pre-rebuild plan, which still said 291 + 148 + 3.

## Verdicts

| # | Step | Result |
|---|---|---|
| 1 | Cold start — header, summaries and chat agree; three parts sum to 442 | PASS |
| 2 | Restore the saved session — corrections and notes reported separately, dismisses cleanly | PASS |
| 3 | Live search a partial name — narrows without Enter | PASS |
| 4 | Search a SOC group name — matches on group, not title text | PASS |
| 5 | Search nonsense — clear empty state, canvas does not blank | PASS |
| 6 | Clear via ✕ — box present and empty, counter back to 442, filtering still live | PASS |
| 7 | Select a needs-review person — card renders all five elements, dropdown at 24 | PASS |
| 8 | Assign a group — recolour, counter 183→182, queue drops, correction marked user-supplied | PASS |
| 9 | Review queue — skip defers without resolving; `NOT_OCCUPATION` from the queue stays colourless | PASS |
| 10 | Write a note — reaches `filter_nodes`, stays out of the coverage arithmetic | PASS |
| 11 | Set About text — privacy note visible, `ABOUT_NOTE_IDLE`→`ACTIVE`, no coverage figure moves | PASS |
| 12 | Chat question — grounded, canvas highlights this answer, no raw handles, caption still agrees | PASS |
| 13 | Download and re-upload — reconciles, zero misses, counts hold; restore-of-a-restore idempotent | PASS |

End state: **181 needs review · 260 classified · 1 not-an-occupation** — 442.

**[confirm]** The correction count at step 13. The restore report reconciled
against what was done in steps 8–11, but the transcript describes it variously
as three corrections and as two corrections plus a not-an-occupation. Classified
moving 259 → 260 implies one group assignment, so two total. The end-state
figures are well attested; the tally is not.

## Paths exercised for the first time

Gate C's value is concentrated here. Six code paths had never executed against
real data before this session:

- **Both D-18 branches** — the suppressed and unsuppressed forms of the header
  counter, in one session.
- **The D-12 nonce pattern** — search cleared via ✕, box reinstantiated, filter
  still connected afterwards. Exercised in both directions.
- **The D-23 bordered container** — `st.container(border=True)` in
  `_render_report`, which had never fired because every prior restore matched
  100% of entries.
- **`STATE_NOT_OCCUPATION` from the queue surface.** Gate B verified it from the
  profile card only. If it had picked up a group hue here it would have appeared
  on the canvas indistinguishable from a genuine classification — the exact
  confidently-wrong failure the abstention design exists to prevent.
- **The notes search path.** Notes entered `filter_nodes`' field set at P2.2b,
  but search had only ever been exercised on name, role and group. Step 10 used
  a word appearing in no job title, so the hit could only have come from the
  note field.
- **Restore of a restore.** Step 13 re-uploaded a file into the live session it
  came from, then again. Idempotent.

Step 12 is the one placed deliberately. Gate B read the chat coverage caption on
a fresh session; step 12 read it after the session had accumulated corrections,
a not-an-occupation, a skip, a note and About text. The caption still agreed
with the header and summaries panel across all three surfaces.

Step 8 established that **every coverage surface derives from `display_state`**
rather than the base table: classified tracked 259 → 260 on the summaries
caption immediately after the assignment. That is what narrowed D-32 to wording
rather than derivation — and, in hindsight, what Gate D later proved was true of
three surfaces out of four.

## Findings

**D-32 — the review queue rendered "183 of 183 still need review"** at cold
start, a figure restating itself beside a header reading "183 need review".
D-18's fix had reworded three captions site by site rather than extracting the
convention, so this panel — written afterwards — never inherited the suppression
rule. Logged, not fixed: no fixes inside a gate. Closed before Gate D opened,
commit `38d3a63`. The same gap later produced D-34 in `assistant.py`.

**P3.13 — chat history in the session file.** Logged to Phase 3 with a privacy
question to resolve first: the file currently holds only what the user wrote,
and adding history would make it hold model-generated prose naming their
connections, which changes what the download warning has to cover.

**Determinism demonstrated end to end.** Step 2 required a `MISS_NO_MATCH`, so
one connection was removed from `Connections.csv` and the full chain re-run. The
connection was restored afterwards and the chain re-run again: 452 raw, 442 kept,
259 classified, 183 needs review, with `graph_metrics.csv` byte-identical to
commit `8468ed0` and the same τ to four decimal places. The methodology claims
reproducibility and had never actually shown it across two independent rebuilds.

**`compute_embeddings` keys its cache on row count alone.** `embeddings.npy` had
to be deleted before the rebuild or it would have reused stale vectors at a
matching row count. A live trap for anyone rebuilding after an export change —
belongs in the README's local-run section before P2.9.

## Left unexercised

The corrections-miss container and the mixed-kind restore render. Step 13
reported zero misses because nothing had departed and no title had moved, so
those branches could not be reached from a clean round trip. The cheap route is
a copy of the session JSON with one entry's `role` altered — no rebuild, no API
spend. Still open at the close of Gate D.

## Next

Gate D — counter integrity. Opened after D-32 and the rest of the pre-gate
defect queue closed.
