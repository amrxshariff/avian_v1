# P2.9b — upload, key, and the free tier

**Project:** network-visualiser
**Status:** agreed, and ready to build. Section 5 (classification is automatic), section 6.4 ($5 per generation, $30 per day), 6.6 (10 free chat questions), 6.7 (ship the title cache) and section 9 supersede the 24 September decisions on caps and on the project key.
**Written against:** HEAD after D-55 (473 tests)
**Scope:** the path from "here is my Connections.csv" to a network on screen — where the API key comes from, how it is held, and what the free tier allows.

> **Correction note — 7 October 2026 (D-80, D-81).** Three amendments, made
> before the free tier's metering was first wired in. None of the caps below
> had ever been constructed in the app (D-81), and the chat allowance had
> never been applied (D-80).
>
> **Chat spend: §6.4 governs, and the §9 summary is corrected.** §6.4 decides
> that chat charges the daily ledger and is not charged against the
> per-generation cap. §9 item 2 restates the cap as "$5 per network
> generation, including that session's chat", which contradicts it. §6.4
> carries the reasoning (a question happens long after the build that would
> have metered it, and ten questions cannot reach $5), and §9 is a summary of
> the sections above it. A summary that contradicts its own section is a
> transcription error, not a competing decision. Read §9 item 2 as "$5 per
> network generation".
>
> **Summaries and self-enrichment: a new decision, since this record was
> silent on them.** On the project key, both charge the daily ledger, as chat
> does, because the ledger is a spend cap and both spend. Neither is charged
> against the per-generation cap. Neither counts against the ten-question
> allowance. That allowance is a promise to the visitor about questions they
> ask. Summaries are produced when a group is selected, and self-enrichment is
> the profile comparison panel. A visitor whose ten questions were partly
> consumed by summaries they never asked for would be misled in the same way
> as a cost quoted from the headcount instead of the uncached titles. So there
> is one ledger with three sources, and one question count with a single
> source.
>
> **§6.5, as built.** The daily total is a file (`data/spend/daily.json`),
> not the module-level number §6.5 describes. That was chosen in `spend.py`
> so that a process restart does not reset it. On Community Cloud the
> container's disk is itself ephemeral, so a container being recycled still
> resets the day. §6.5's conclusion stands unchanged: the Console limit is
> the guard for that, and for "a bug in the metering itself", which is what
> D-81 turned out to be.

## 1. Why these three are one piece of work

They cannot be built separately:

- An upload with no key cannot classify.
- A key field with no free tier means the first visitor with a 4,000-row export spends your money, with no ceiling.
- A free tier with no key field means a visitor who exhausts it has nowhere to go.

Everything built in commits 1 to 4 is also unreachable until this lands: nothing populates session state, so `build_network` has no caller in the UI.

## 2. What already exists

- `build_network()` takes a path or parsed people, a client and a cache path, and returns a `BuildResult`.
- `retry_unclassified()` re-classifies without moving anyone.
- `session_build.get_built()` / `set_built()` hold one network per session.
- `BudgetExhausted` is defined in `claude_classifier` and maps to the `budget_reached` reason, which the notice already knows not to offer a retry for.
- `InvalidExport` covers a missing file, a CSV that is not an export, an empty export, too few people, and an export with no titles.

So this work is the UI path and the key policy, not new machinery.

## 3. Found while writing this: four key readers (proposed D-55)

`_default_client()` exists **four times**, each reading `ANTHROPIC_API_KEY` from the environment:

- `src/claude_classifier.py` L88
- `src/assistant.py` L180
- `src/dashboard/summaries.py` L420
- `src/self_enrichment.py` imports the classifier's

They agree today because there is one key and it comes from one place. A session key makes them disagree: paste a key, and the build would use it while the chat and the summaries quietly carried on with the project's. The user would have no way to tell.

**Proposed: one resolver before any of this is wired.** `src/dashboard/keys.py` exposes `resolve_client(purpose)` and every caller uses it. This is D-53's shape again, found before it bites rather than after.

## 4. Where a key comes from

In order:

1. **A key the user pasted this session.** Their key, their credit, no limits imposed by us.
2. **The project key**, if one is configured, subject to the free tier in section 6.
3. **No key at all.** See section 5.

The `source` field already in `BuildResult.provenance` records which of these was used, and section 7 puts it on screen.

## 5. Classification is automatic; the keyless build is the fallback

Every uploaded network is classified immediately, on whichever key resolves:
the visitor's own if they pasted one, otherwise the project key. Amr fronts
that cost deliberately — a network without groups demonstrates the layout but
not the product, and asking a stranger for an API key before showing them
anything is a poor trade for them and a worse one for us.

The keyless build stays, as the fallback for the two cases where no key
resolves:

- nobody has pasted one and the project key is not configured;
- the daily budget is spent.

In both, the whole network still renders — everyone placed, every edge drawn,
everyone in the fourth state — and the notice says why and offers the key
field. Nobody gets a dead app; they get shape without meaning, which is more
than they had.

This reverses the earlier "keyless by default" decision (24 September). The
machinery is unchanged: it was built for a partial classification and serves an
absent one identically.

## 6. The free tier, in money

**Agreed: $5 per network generation, $30 per day.** Caps are denominated in
spend, not in titles, because spend is the thing being protected. A title
count only bounds the bill if the cost per title never moves, and it moves
whenever the model, the prompt or the tokenizer changes.

### 6.1 This means metering tokens, not counting people

Every response carries `usage.input_tokens` and `usage.output_tokens`. The
classifier must return them, the build must total them, and the limiter must
price them. Counting titles would be a proxy for a number the API hands us
directly.

Consequences for the code:

- `ClassifyOutcome` gains the usage totals for the run.
- The limiter is consulted **between batches**, with the spend so far. When the
  next batch would cross a cap, it raises `BudgetExhausted` — which is already
  wired end to end: everyone unclassified gets `budget_reached`, the network
  still renders, and the notice offers the key field rather than a retry.
- Cache hits cost nothing and are metered as nothing, so deduplication and
  retries stay honest: a retry pays only for what it re-sends.

### 6.2 The price table, and why it is a liability

`claude-sonnet-5` is **$2 per million input tokens and $10 per million output
tokens**. The introductory rate was made permanent in August 2026, so the
scheduled rise to $3/$15 did not happen. Cache reads are $0.20 per million.
Source: anthropic.com/news/claude-sonnet-5.

A price table in the code is a copy of someone else's number. When Anthropic
changes it, the app silently under-counts and the $30 daily cap quietly
becomes $45.
So:

- the rates live in `config.py`, beside the model id, with the date they were
  checked and the source URL;
- the deploy checklist includes verifying them;
- the estimate shown to a user says "about", because it is.

### 6.3 What a network costs — measured 26 September 2026

One run of the real classifier over 100 distinct titles from the real export,
cache off, `claude-sonnet-5`, batch size 20:

| | |
|---|---|
| Calls | 5 |
| Input tokens | 8,791 |
| Output tokens | 7,782 |
| Answered | 100 / 100 |
| Total | $0.0954 |
| **Per title** | **$0.00095** |

At that rate:

| | |
|---|---|
| A 442-person network (371 distinct titles) | **$0.35** |
| Ten chat questions | ~$0.20 |
| A full free session | **~$0.55** |
| Free networks per $30 day | **~85** |

Two findings worth keeping.

**Adaptive thinking is not dominating.** Output ran at 0.9× input, not the 3–5×
feared when MAX_TOKENS was raised to 8,000 for D-42. Prompt caching on the
system block would save roughly $0.003 per network and is not worth adding.

**Chat is the expensive half.** Ten questions cost more than half of what the
network itself costs. If free usage skews toward the chat, the allowance is
the number to revisit, not the build.

The limiter assumes **$0.0012 per title**, the measured figure rounded up by
about 25%. Re-run `tools/measure_cost.py` whenever the model, the prompt or
MAX_TOKENS changes; all three move this number.

### 6.4 Two ceilings, and what they are for

| Ceiling | Guards against | Value |
|---|---|---|
| Per network generation | A pathological upload — 4,000 rows, or a title set nothing caches | **$5**, estimated before the first call |
| Per day, across everyone | The demo being posted somewhere busy | **$30** |

Chat is not charged against the per-generation cap. A question happens long
after the build that would have metered it, and keeping a meter alive across a
session to enforce a cap that ten questions (~$0.20) cannot reach buys nothing.
Chat charges the daily ledger, and the ten-question allowance in 6.6 is its
real limit.

The per-generation cap is a runaway guard rather than a budget. At measured
rates a 442-person network costs $0.35, so $5 never binds in practice — which
is the point. A cap that binds routinely is a cap set wrong.

The daily figure is the real limit: about **85 free networks a day**, and
rising as the cache fills.

**The pre-flight estimate is mandatory, not advisory.** The other ceiling is
enforced between batches, and on the project key an automatic classification
means a stranger's export starts spending the moment it lands. The estimate
runs before the first call and refuses the build rather than starting it. On
the visitor's own key there is nothing to guard and no estimate is shown.

### 6.5 What the counters are worth, honestly

Community Cloud gives no durable shared storage. The daily total is a
module-level number in the app process: shared by every session on that
container, reset by any redeploy or idle restart.

- It bounds ordinary use, which is what it is for.
- It does not survive a redeploy, so a restart resets the day's spend.
- Anyone who can make the app restart can reset it.

**Set an Anthropic Console spend limit of $150 a month on the deploy-only
key.** Note the units: the app's $30 is daily and in-process, the Console's is
monthly and authoritative — they are not the same guard and the Console figure
is deliberately loose against the app's.

The Console limit exists for the cases the in-process counters cannot see: a
redeploy resetting them mid-day, more than one process each counting to $30
alone, or a bug in the metering itself. $150 is about five fully saturated
days, or 425 networks — far above normal traffic, low enough that a runaway
stops at an amount worth absorbing. If it ever binds, the right response is to
find out why the daily cap didn't, not to raise it.

Use a key created for this deploy alone, so it can be revoked without touching
anything else.

### 6.6 The chat allowance

Each question sends the whole network as a payload — about 9,000 tokens for
442 people, roughly $0.02 on the project key. Cheap alone, unbounded in
aggregate: forty questions from one visitor costs about as much as another
whole build.

**Ten questions per session on the project key. Unlimited on your own.**

A count rather than a spend figure, because a count is something the user can
see: "10 questions on the free tier, unlimited with your own key", with the
remaining number shown beside the box. A spend figure would need explaining and
would move under them mid-session.

The tenth answer says the allowance is spent and points at the key field. The
network, the corrections and everything else stay usable — only the chat stops.

### 6.7 The title cache is what makes this affordable

A title classified for any visitor is free for every visitor afterwards. The
cache keys on (title, company) and holds the answer, not the person, so it is
shared safely across sessions: "Software Engineer" is paid for once, ever.

Two consequences:

- **Ship the cache with the deploy.** It already holds the real network's 371
  distinct titles and the synthetic set. Starting empty would mean paying again
  for titles already bought.
- **A returning visitor is nearly free**, with nothing to explain and nothing
  to ask of them. A saved session does NOT help here: the download holds
  corrections, notes and profile text, never the nodes or the classifications,
  so restoring one still rebuilds. If skipping the rebuild is ever wanted, that
  means putting the node table in the download, which is a privacy decision —
  the file would then carry every connection's name and group rather than the
  user's own notes.

## 7. Holding a key

- **Session state only.** Never a file, never a URL parameter, never the session export, never a log line.
- **Entered through a password field**, so it is not left on screen.
- **Redacted from every error path.** One `redact()` applied to any message before it is displayed or logged, matching `sk-ant-` followed by anything. Tracebacks from the SDK can carry the key in a request repr.
- **Forgettable.** A "Forget my key" control that clears it, and a line saying it is held for this session only.
- **The field says what it is for**, with a link to the source on GitHub. A public page asking for an API key looks exactly like a phishing page, and the only answer to that is showing the code that handles it.

**Validation before the build**, one cheap call with `max_tokens=1`, with four distinct outcomes:

| Outcome | Message |
|---|---|
| Valid | proceed |
| Rejected (401/403) | "That key was rejected. Check it was copied in full." |
| No credit (400, credit balance) | "That key has no credit left." |
| Service busy (429/5xx) | "The classification service is busy. Your key looks fine — try again in a moment." |

The last one must not read as a bad key. Telling someone their key is broken when the service is having a bad minute sends them to rotate a key that was never the problem.

## 8. Upload limits (numbers needed)

The resource spike measured **442 people at 1,332 MB peak against a 3,072 MB ceiling**. Roughly 1.1 GB of that is the imports, so the marginal cost per person is small — but "roughly" is not a number, and a 4,000-person export is nine times the data through UMAP, whose memory is not linear in the row count.

**Proposed: measure before promising.** A short spike — build at 1,000, 2,000 and 4,000 synthetic rows, record peak memory and wall time — then set the row cap from the measurement. Until then, a conservative cap of 1,500 rows, refusing above it with a clear message.

Also needed:

- a file-size cap (Streamlit's uploader has its own, and it defaults higher than we want);
- a message for a file that is a valid CSV but enormous, distinct from one that is not an export at all.

## 9. Decisions

1. Every upload is classified immediately, on the visitor's key or the
   project's. The keyless build is the fallback.
2. **$5** per network generation, including that session's chat, estimated
   before the first call.
3. **$30** per day across everyone.
4. **10 chat questions** per session on the project key; unlimited on the
   visitor's own.
5. The project key is **on** in the public deploy. (Reverses the earlier
   config-flag-off-by-default decision.)
6. When the daily budget is spent: upload works, the network builds and
   renders, everyone lands in the fourth state, and the notice offers the key
   field.
7. No row cap. `MAX_PEOPLE = None`, with a warning above 1,500 and the guard
   kept in the code for when a number is measured.
8. D-55 when necessary — done, 24 September.
9. Cost per title measured 26 September: $0.00095 (section 6.3). The limiter
   assumes $0.0012, that figure rounded up. At this rate $30 a day buys about
   85 free networks.

## 10. Slicing, once decided

1. **Upload and build with no key**: the file uploader, `build_network` on the parsed export, the result in session state, everyone in the fourth state. The app becomes genuinely usable here.
2. **The key field**, with **D-55 first** inside this slice: one key resolver,
   four callers, no behaviour change — then paste, validate, redact, forget,
   and a build that classifies.
3. Both ceilings, enforced: $5 per generation and $30 per day.

## 11. Not in scope

- Durable rate limiting and abuse bounding. Item 6 of the plan says these are done properly for the API, not here.
- Auth and hosting. Item 8.
- The cache keyed on content, session expiry, provenance on screen, and the About-text acceptance check. Separate P2.9b items, each independent of this one.
