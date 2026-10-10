# Document reconciliation — 6 October 2026

What records exist, which are current, and which are owed. Written because P2.9b closed
without a closure record and the project's own documentation had drifted behind the code
by about two weeks.

**Caveat on method:** this reconciliation is built from the working sessions, not from a
listing of `docs/`. Where a document is named here, it was named in a session. Where this
file says *unverified*, it means exactly that. Reconcile against the real tree before
treating this as authoritative:

```powershell
cd C:\dev\network-visualiser
Get-ChildItem docs\ -Recurse -File | Select-Object Name, Length, LastWriteTime | Sort-Object LastWriteTime
```

---

## 1. Written today

| Document | Covers |
|---|---|
| `docs/p2_9b_closure.md` | P2.9b, closed 29 Sep — what was delivered, every measured figure, D-52 to D-70, decisions locked |
| `docs/p2_9_deployment_plan.md` | P2.9 — the eight steps with acceptance criteria, the step 4 decision, open non-blockers |

Both follow the house convention: markdown in `docs/`, PDF generated and committed
alongside, the pair staged in one commit.

## 2. Records that exist and are current

| Record | State |
|---|---|
| `docs/defect_register.md` (+ PDF) | **Living document, authoritative.** D-01 to D-75 |
| `docs/p2_9b_upload_key_tier.md` | The free-tier design record. Cost figures replaced with the measured $0.00095/title; stale clauses swept |
| Partial-failure design record (option B) | Written during P2.9b |
| D-42 failure-mode record | Written 22 Sep |
| Gate A, B, C, D records | Markdown + PDF, committed. Closed Phase 2's QA sequence |
| `phase2_scope_revision` (22 Sep) | The record that retired day counting and fixed the dependency order |

## 3. Records that exist but carry a correction

| Record | Correction |
|---|---|
| `docs/p2_9a_record.md` | Dated note from D-69: the stopping rule fired on noise. The two pre-registered re-tunings moved a figure whose run-to-run spread (6.1pp: 27/442) is larger than the miss that stopped the process (2.1pp). The record itself stands — it is honest about what it did |
| Eight historical records | Dated correction notes added 22 Sep for D-42 (the classifier defect that cached failed batches as abstentions) |
| `docs/project_state_decision_log.md`, `docs/project_status_refined_p2.md` | D-69 correction notes added 29 Sep, as named in the register's D-69 entry |

**One wording sweep that may be incomplete.** D-69 established that
"measured three convergent ways" must now read "measured three convergent ways, **each a
single run**." That phrase may appear in more documents than the two that received notes.
Worth a grep before the public repo:

```powershell
Select-String -Path docs\*.md, README.md -Pattern "convergent|point estimate|21\.9|29\.0"
```

## 4. Owed, not yet written

| Document | When |
|---|---|
| **P2.9 gate record** | After step 7. Same form as Gates A–D: one continuous session, written verdict per step, no restart. The five checks are set out in `p2_9_deployment_plan.md` §2 step 7 |
| **Phase 2 checkpoint record** | After P2.9. Closes the phase formally — a deployed app rendering a real network with a correctable grey node |
| **D-70 measurement record** | After the CLI run. Short: the spread on the single-call enrichment path, and which of the two follow-ups it implies |

## 5. Gaps in this reconstruction

**D-54 and D-60.** Neither appears in the sessions I reconstructed from.
`docs/p2_9b_closure.md` §4 flags them and points at the register. Transcribe them into the
closure record from `docs/defect_register.md` rather than leaving the gap:

```powershell
Select-String -Path docs\defect_register.md -Pattern "D-54|D-60" -Context 2,6
```

## 6. The claude.ai project knowledge base is stale

The uploaded files in this project's knowledge base were last refreshed on **21 September**
and the source files on **21 September**. Everything in P2.9b — the key field, the free
tier, lifetime, provenance, the content-keyed cache, and all of D-53 to D-70 — postdates
them. So does the entire defect register.

That is why a status question answered from stored project context came back saying
"Day 18, Gate D" when the real state was P2.9b closed at 654 tests.

Worth refreshing before the next long session, and in particular:

- `docs/defect_register.pdf` — the single most useful file to have in context, and it is
  not there at all
- `docs/p2_9b_closure.pdf` and `docs/p2_9_deployment_plan.pdf` once generated
- `phase2_scope_revision.pdf` is present but predates P2.9b's close
- The source snapshot (`src/`, `tests/`, `tools/`) is two weeks and roughly 320 tests
  behind

The alternative is to keep answering status questions from the session log, which works
but is slow and gets slower as the log grows.
