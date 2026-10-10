# Gate D — counter integrity

> **Correction note — 21 September 2026 (D-42).** This record's cold-start baseline, 442 / 259 / 183 / 0, was inflated by a classifier defect: API batches cut off at the token limit were cached as if the model had declined to classify them. The corrected figures for the same 442 people are **314 classified, 128 needing review (29.0%), 0 not-an-occupation**. The gate's verdicts stand: it tested that every surface derived the figure from one source and agreed through a correction sequence, and they did. What was wrong was the input to that derivation, which no consistency check can detect. The record below is left as written. See `docs/d42_failure_record.md` for the cause, the evidence and the fix.


**Day 18. Closed 14 of 14.** One continuous browser session, no restart, no
cache clear, no crash. No fixes applied inside the gate.

## Definition of done

The gate plan of 2 September defined Gate D in a single line: *the needs-review
figure verified live-derived at every surface it appears.* The surfaces were
never enumerated, so the enumeration below was proposed, agreed and then
produced by source-level sweep before the gate opened.

Full DoD as run: every surface rendering a population count is enumerated by
source-level sweep; each is verified live-derived from a single source with
corrections applied; all agree across a correction sequence; the three display
states close on the population at every step; a written verdict per surface;
no fixes inside the gate.

The distinction the gate turns on is **agreement versus derivation**. Two
surfaces computing the same number by different routes agree until one route
changes. That is the D-15 shape, and it is not visible in a screenshot — which
is why steps 1-4 are source-level and only step 14 tests the claim at runtime.

## Baseline

442 people · 259 classified · 183 needs review · 0 not-an-occupation.

## Verdicts

| # | Check | Result |
|---|---|---|
| 1 | `sweep_count_surfaces --ui-only --strict`: 26 count-bearing strings across 13 files, 0 unexempt | PASS |
| 2 | `check_single_loader`: 7/7 | PASS |
| 3 | `pytest`: 267 | PASS |
| 4 | Five count sources: 4x `coverage_counts`, 1x `review_counts` for the baseline M | PASS |
| 5 | Cold start, five surfaces, four suppression branches fire | PASS |
| 6 | 259 + 183 + 0 = 442; 240 + 19 = 259 | PASS |
| 7 | One assignment: 260 / 182, M held at 183 | PASS |
| 8-9 | Four assignments + one not-an-occupation: 263 / 178 / 1 | PASS |
| 10 | Two skips: queue view loses two, no count moves | PASS |
| 11 | Query narrows, clears, group filter — sidebar moves alone | PASS |
| 12 | Download and restore: identical counts, M = 183, report reads `5 of 5` | PASS |
| 13 | Second restore of the same file: idempotent | PASS |
| 14 | Sixth correction: 264 / 177 / 1, all surfaces move in ONE rerun | PASS |

## Surfaces enumerated

Seven. Six observed live.

| Surface | Site | Count source | Verdict |
|---|---|---|---|
| Header | `app.py:167/169` | `coverage_counts` (N), `review_counts` (M) | live-derived |
| Sidebar counter | `search.py:71/72` | `len(matches)` / `len(df)` — a filter counter, not a population count | correct by scope |
| Summaries caption | `summaries.py:282/285/288/298/301` | `coverage_counts` | live-derived |
| Chat caption | `assistant.py:503/506/508/510` | `coverage_counts` | live-derived |
| Review queue | `people_list.py:158/159` | `coverage_counts` | live-derived |
| Pager | `people_list.py:270` | page arithmetic | exempt, confirmed live |
| Restore report | `session_io.py:159/163` | restore result | exempt; L159 observed, **L163 not** |

N — the needs-review figure — now has exactly one derivation across the four
population surfaces. M is the session's fixed starting backlog and legitimately
takes the second route: it counts `is_uncertain` on the pre-correction base and
cannot be recovered from a frame that already has corrections applied.

## Exemptions

Eight `N of M` constructions carry inline `# count-exempt:` markers. The sweep
detects the *construction*, not the guard, so a correctly guarded site still
matches; the reason field states which of three cases applies.

| Site | Reason | Class |
|---|---|---|
| `app.py:169` | guarded, n != m | guarded |
| `people_list.py:159` | guarded at L154 (D-32) | guarded |
| `search.py:72` | guarded by `filtering`; the filtered-and-matching-all case is intended | guarded |
| `summaries.py:288` | guarded at L282/285 | guarded |
| `assistant.py:506` | guarded — equal case handled (D-34) | guarded |
| `people_list.py:270` | `_render_pager` returns early when `total_pages <= 1` | unreachable |
| `session_io.py:159` | equality is the reassurance — "5 of 5 corrections" is the point | intended |
| `session_io.py:163` | as above, for notes | intended |

Two were confirmed by observation rather than argument: the pager rendered
`11-20 of 442` on a non-first page, so its equal case genuinely cannot occur;
and the restore report rendered `5 of 5`, which is the reason working as
stated. `session_io.py:163` never rendered — this session carried no notes —
so its reason remains reasoned but unobserved.

## Defects closed before the gate

| | | Commit |
|---|---|---|
| D-32 | Review queue rendered "183 of 183" at cold start | `38d3a63` |
| D-34 | Chat caption would render "all 442 classified connections of 442" | `4769cfe` |
| — | Sidebar rendered "442 of 442 shown" at rest | `2cc7542` |
| D-33 | Header read the node table a second time off disk | `cb370e9`, `43e51b2` |
| D-35 | Review queue counted `display_state` inline — a third implementation | — |
| D-36 | Sidebar caption extracted to a pure `filter_caption()` | — |
| D-37 | Checker exemptions moved to the site, checked per line | — |
| D-38 | Double-encoded em-dashes in `check_single_loader` output | in `43e51b2` |

**D-33 is the one that mattered.** `app.py` called `get_review_counts()` with
no argument, which read `network_nodes.csv` off disk a second time through a
separate cached function, ignoring the frame `load_display_table()` had
assembled one line earlier. Every count agreed, so nothing on screen said so.
At P2.9 the upload flow hands the loader its own pipeline output — so the
moment a user uploaded their network, the four `display_state` surfaces would
have reported their counts while the header reported whatever sat in
`data/graph/network_nodes.csv` on the server. After P2.9a that is the synthetic
demo set. Not a crash: a confidently wrong number in the largest type on the
page, beside four correct ones.

`tests/test_review_count_equivalence.py` was written against unchanged code and
verified green at `ad7ef5a` with both routes live, then green after the
collapse. D-33 is therefore a proven refactor, not an assumed one. The
structural proof is that `check_single_loader`'s exemption for `state.py` —
"owns NODES_CSV as the base read" — could be deleted. That exemption *was* the
defect, and it hid it for exactly as long as it stood.

**D-34 was unreachable by observation.** Its trigger requires every person
classified, which no screenshot of the 442-row table can produce. It was found
by source-level sweep and closed by unit test on a synthetic frame.

## Instrumentation built for this gate

- `tools/sweep_count_surfaces.py` — AST enumeration of count-bearing strings,
  inline `# count-exempt:` markers read via `tokenize`, `--ui-only` and
  `--strict`. AST rather than grep for the reason `check_single_loader` learned:
  a docstring mention produces a false positive.
- `check_single_loader.py` criterion 1 — now per-line with site-local
  `# loader-exempt:` markers, replacing a file-level exemption dict.
- `tests/test_review_count_equivalence.py` — seven correction scenarios, four
  properties, pinning the two derivations against each other.

## Known limits

1. **`--strict` cannot catch a stale reason.** It fails on new unmarked
   constructions only. Delete a guard, leave the marker, and the check stays
   green. That is `check_single_loader`'s `state.py` exemption one level up.
   The mitigation is that every reason prints in the report and is read at the
   gate — a human step, not a guarantee. This fired once during D-35: an edit
   moved a guard and left the marker's line number stale, and only reading the
   reason caught it.
2. **Two exemption mechanisms, two matching rules.** `count-exempt` matches a
   span of `[lineno-1, end_lineno]`; `loader-exempt` requires an exact line
   match. Logged as D-39.
3. **`session_io.py:163` unobserved**, as above.
4. **Sidebar counter is scoped differently** from the other four. It counts
   filter matches, not display states, and does not exclude needs-review people.
   Correct, but it is not a population count and should not be read as one.

## Open at close of gate

D-11 (Phase 4), D-21, D-22, D-29 (docs), D-37 markers' wording, D-39
(reconcile the two marker rules), D-40 (both rebuild-diff tools fail on a clean
checkout because `.bak430` is gitignored; state it in their docstrings).

## Next

Phase 2 checkpoint: P2.9a (synthetic 442-row demo set, self-node identity),
D-31 (build/runtime manifest split, verified in a clean venv), P2.9 (deploy,
README, demo, zero-crash).
