# Phase 3 — Amendment 2

## P3.8 — Query expansion at retrieval time

**Status:** proposed, scheduled into Phase 3. Raised during P2.2b, deferred
deliberately: no Phase 2 definition of done covers it.

---

## The request

Notes and roles use different words for the same thing. One person is tagged
"pitching", several others "presentation skills". Searching one should surface
the other. More generally: similar capabilities should be findable together,
however they happen to be worded.

The instinct is right. The obvious implementation is not, and the reason is
worth recording, because it will be proposed again.

---

## What is ruled out: clustering people by note content

**Three independent reasons, each sufficient on its own.**

**1. It breaks the cross-cutting rule.** After P2.2b the only free text spanning
multiple people is notes — and a note is the *user's* words about someone else,
not that person's own words about themselves. Amendment 1 permits attribution
only where "that individual's own words are its source". Grouping a note about
Sarah into a facet labelled "presentation" converts the user's recollection into
an attribute on Sarah's card. That is the same laundering that kept notes out of
`skills_note()` in the first place.

It is also structurally impossible to do compliantly. Under Version A the user
holds their own `Connections.csv` and will never possess anyone else's
self-description, so the permitted source for a per-person skill cannot exist.

**2. The method is already ruled out on this exact case.** The MiniLM embedding
tier was measured at 40% accuracy and abandoned because it matches word overlap
rather than meaning. "Pitching" and "presentation skills" share no tokens. This
pair is the *hardest* case for that method, not a favourable one.

**3. There is nothing to cluster.** P2.2b criterion 6 states that low note
coverage is by design — ten people known well beats 430 who are not. HDBSCAN
already failed on 371 titles with 336 singletons; six to twenty notes offers
less density, not more. A feature that only pays off at high note coverage
creates pressure to write more notes, which directly attacks the criterion that
protects the feature's integrity.

---

## What P3.8 is instead

The underlying need is **retrieval**, not grouping. The user types
"presentation" and wants the person they tagged "pitching" returned. That is
achieved by widening the *query*, not by grouping the *people*.

The distinction is the whole point:

| | asserts something about a person | needs density | needs a compliant per-person source |
|---|---|---|---|
| clustering notes | yes | yes | yes |
| expanding the query | **no** | **no** | **no** |

Expansion is a function of the **query string alone**. No personal data enters
it. Nothing is written to any person's record. No card gains a term. The user
typed the word; the tool matched it generously; the match is shown and can be
overridden. A note stays a note.

This also works at n = 6 notes, which is the coverage P2.2b actually expects.

---

## Definition of done

1. A query matches semantically related terms across the existing
   `filter_nodes` field set, so "presentation" returns a row noted as
   "pitching".
2. **Expansion is visible.** The result list shows which term caused each row to
   match. A widened match the user cannot see is indistinguishable from a bug.
3. **Expansion is derived from the query only.** No person's note, role, or
   identity is an input to term generation — verified in code and documented as
   an explicit non-goal.
4. **No individual gains an attribute.** No expanded term is written to any
   record, displayed on any card, or persisted in any form.
5. Expansion is switchable, and switching it off returns *exactly* the P2.4
   substring behaviour. The current search is the pre-registered fallback.
6. Degrades gracefully: where nothing expands, behaviour is identical to
   substring matching. No minimum note count.

## Pre-registered gate

Fixed before implementation, on a hand-built probe set of 20 related term pairs
and 20 unrelated pairs, written before any expansion code is run:

- **≥ 15/20** related pairs match after expansion.
- **≤ 2/20** unrelated pairs match after expansion.

Failing either gate, P3.8 is dropped and search remains as delivered in P2.4.
Expansion that pulls in unrelated people is worse than no expansion: it makes
the result list untrustworthy, and an untrustworthy result list undermines the
one interaction the whole dashboard depends on.

---

## Placement and cost

Phase 3, after P3.6 and P3.7. Those two do similarity work at the level of
**occupations**, which is where similarity is both permitted and statistically
viable; P3.8 is the same principle applied to the search box.

**Estimate: 0.5 focused days.** Touches `search.py` and the result list only.

Phase 3 estimate revised from 7–9 to **7.5–9.5 focused days**.

---

## Cross-cutting rule, restated again

No feature attributes a skill, tool, or capability to a named individual unless
that individual's own words are its source. Occupational descriptions are
attributed to occupations. Search behaviour is attributed to the search box.

*Data attribution: this system includes information from the O\*NET 30.3
Database by the U.S. Department of Labor, Employment and Training
Administration (USDOL/ETA), used under CC BY 4.0. USDOL/ETA has not endorsed
this application.*
