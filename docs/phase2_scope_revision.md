# Scope revision — timelines dropped

**Project:** network-visualiser
**Status:** Phase 2, post-Gate-D, pre-deployment
**Supersedes:** the Day 19 locked sequencing table and its day targets

## Decision

Day counting and deadline targets are dropped. The earlier 19–21 day baseline, the
Day 24 Phase 2 checkpoint target and the Day 30–32 launch target are no longer in
force and are not to be used as pressure on scope or quality.

The priority is a sustainable, fully functional product.

**What this changes:** no end-dates on items, no framing of scope decisions as costs
against a schedule, and no trimming of work to reach a date. Estimates are retained
only where they help decide what to open in a given session.

**What this does not change:** the dependency order. P2.9b precedes P2.9, which
precedes the Phase 2 checkpoint, which precedes the API, which precedes the MCP
server. That is architecture, not schedule.

## Baseline state at the time of this revision

- 442 rows / 314 classified / 128 needing review (29.0%) / 19 SOC groups.
- Gates A, B, C and D all closed. 294 tests passing.
- P2.9a closed: synthetic demo ships at 21.9% grey against a real 29.0%.
- D-42 closed: adaptive thinking consumed the 2000-token `MAX_TOKENS` budget,
  batches truncated, `_parse_response` padded the missing slots as abstentions,
  and those abstentions were cached permanently. Roughly one in eight people were
  shown as unclassifiable for about a month.

## 1. Requirements and environment

| Item | Description | Origin |
|---|---|---|
| D-31 | Split build vs. runtime requirements, verified in a clean venv. Note the Day 19 partial reversal: torch, sentence-transformers and umap-learn are runtime, not build-only. `faker` stays build-only. | Existing |
| D-30 | matplotlib present in the environment but absent from `requirements.txt`. Folds into D-31. | Existing |
| — | Pin the full runtime set, not only the two known traps (`streamlit-keyup==0.4.0`, `streamlit==1.41.1`). A clean-venv install that resolves differently in six months is a sustainability problem. | **New** |

## 2. Documentation batch

Previously queued behind deployment to get something shippable sooner. Now moves in
front of P2.9b, because P2.9b changes the code these describe.

- D-29, D-21, D-22 dispositions.
- D-39 / D-40 dispositions.
- The 441/442 record.
- The untested mixed-kind restore path — logged.
- **New:** written record of the D-42 failure mode. A silent truncation that cached
  itself as an abstention for a month is the most instructive thing this project has
  produced, and it currently exists only in a commit message.

## 3. P2.9b — build a network from a raw export, in-app

The core of the remaining work. Turns the command-line chain into one function that
the app, the API and the MCP server all call.

### Already specified

- Loader accepts a raw LinkedIn `Connections.csv` directly.
- **Classification provenance.** The cache record gains a `model` field; existing 547
  entries backfilled as `claude-sonnet-5`. A session carries `model`,
  `prompt_version` and `source` (your key / the user's key / the client model over
  MCP). The app states it plainly on screen, not in a tooltip.
- **Paste-your-own-key.** Session-only: held in memory, never written to disk, never
  logged, redacted from error text, gone when the session ends. Validated with one
  cheap call before a build starts. The field is written to make clear what it is used
  for and that it is not stored.
- **Free tier.** A per-session limit plus a global daily budget on the project key.
  When spent, the app offers the key field and the synthetic demo.
- The user has no row in the node table; their About text reaches the chat as its own
  labelled block.
- Acceptance check carried over from P2.9a: confirm the About text actually reaches
  the chat.

### New under this item

- **Resource spike first.** A throwaway deploy that imports sentence-transformers and
  umap-learn and runs them on 442 rows. Now a gate rather than a risk check: if cold
  start cannot carry it, the design changes before any of the above is written.
- **Failure-mode test suite on the build function.** Malformed CSV, empty export,
  wrong columns, a key that dies mid-run, a 12-person network, a 4,000-person network,
  duplicate names, non-ASCII names. Three consumers depend on this function; it is
  tested at that level, not at the level the app alone needs.
- **Partial-failure semantics.** D-42 was a truncated batch silently becoming data.
  Decide explicitly what a build does when batch 19 of 23 fails: abort, or return a
  partial network that states what is missing. Either is acceptable; an accident is
  not.
- **Idempotency and cache keying.** The embeddings cache keys on row count alone, so
  rebuilds reuse stale vectors. Fix it rather than documenting it in the README.
- **Session lifetime and memory.** A raw export is real people's names held
  server-side. Explicit expiry, nothing written to disk, stated on screen.

## 4. P2.9 — deploy

- Clean Community Cloud deployment, no real personal data, verified runtime manifest.
- O*NET attribution (CC BY 4.0, USDOL/ETA) in README and dashboard footer.
- README documents the embeddings cache trap and the demo's 21.9% grey share against
  the real 29.0%.
- Demo recording; zero crashes.
- **New:** a first-run path that works with no key and no upload. The synthetic demo
  is the default landing experience, not a fallback.

## 5. Phase 2 checkpoint

Sign-off: a deployed app that renders a real network and lets someone correct a grey
node.

## 6. API over the shared build function

- FastAPI, session handling, limits.
- **New:** versioned endpoints and a written contract. The MCP server sits on this;
  changing it later breaks a client not under our control.
- **New:** rate limiting and abuse bounding done properly rather than best-effort. The
  Day 19 spec conceded that Community Cloud counters reset on redeploy and that
  IP-keyed limits are trivially bypassed — acceptable for a demo, not for something
  sustainable.

## 7. MCP server

- Thin over the API, with the classification round trip, so users spend their own
  Claude/ChatGPT subscription.
- **New:** tool descriptions and error messages written for a model to read, and
  tested against an actual client. An MCP server a model cannot drive is a server that
  does not work.

## 8. Hosting, auth, deploy

Hosting that carries torch, auth, launch.

## Explicitly not in scope

- **Re-tuning the P2.9a 21.9% calibration.** The stopping rule fired because both
  pre-registered re-tunings were spent. That was methodological discipline, not a time
  constraint. Re-tuning now would make the figure less trustworthy, not more. The
  honest remedies are the agreed README wording, or a fresh demo generated under a
  newly pre-registered procedure.
- **Re-tuning the classifier.** Config E sits at the human ceiling (63.5% precision on
  the blind 100).
- HDBSCAN clustering, the MiniLM embedding classification tier, company as a signal,
  and scraping others' profiles — all permanently ruled out.

## Deferred to Phase 3, unchanged

Team composition queries, serendipity suggestions, the network insights / centrality
chart, cluster skill matrices, P3.9 (SOC-tree zoom), P3.10 (user-supplied skills
field), P3.11 (quantity-surveying cluster), P3.12 (re-import correction churn).
