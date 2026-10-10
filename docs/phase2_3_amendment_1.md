---
title: "Phases 2–3: Amendment 1"
subtitle: "Skills attribution, network-wide enrichment, and the amended definitions of done"
author: "Amr Shariff"
date: "18 August 2026"
---

# Status of this document

This amends *Phases 2–4: Definitions of Done* (19 July 2026). It supersedes the
affected clauses; everything not mentioned here stands unchanged.

Three amendments are recorded. Two are corrections to criteria that could not
pass as written. One is new scope arising from a design question raised on
18 August 2026.

---

# Amendment 1 — "clicking a node" becomes "selecting from the list"

**Affects:** P2.1, P2.5.

**Original wording:** *"Clicking an uncertain node opens a confirmation
control"*; *"clicking any node opens a detail card"*.

**Amended wording:** *"Selecting any node from the search/list panel opens a
detail card"*, and correspondingly for the confirmation control.

**Reason.** Streamlit's `on_select="rerun"` does not fire reliably on
`Scatter3d`; the mechanism was built for 2D Cartesian plots. This was verified
against the bug tracker before P2.3 was built, not discovered afterwards. The
adopted model makes the graph a pure output surface with selection flowing
through the list panel.

Independently of the technical constraint, this is the better interaction:
precisely clicking one node in a 430-node 3D cloud with depth occlusion is
impractical regardless of event support.

A criterion that cannot pass should be rewritten, not fudged at the QA
checkpoint.

---

# Amendment 2 — no taxonomy-derived skills attributed to individuals

**Affects:** P2.5.

**Original wording:** *"...taxonomy-derived skills/tools where classified..."*

**Amended wording:** *"A skills section is present but populated only from
user-supplied enrichment. Absent enrichment, it states why, rather than
presenting group-level data as personal."*

## Reason

The chosen classifier (Config E) returns a **2-digit SOC major group**. O\*NET
skills and tools join on **detailed O\*NET-SOC codes**. There is therefore no
route from a classification to a person's skills that does not pass through a
group-level inference.

Rendering "financial modelling, forecasting, valuation" against a named
individual because their title landed in major group 13 is individually-attributed
data derived from a group-level inference. It is the confidently-wrong-while-citing-an-authoritative-taxonomy
failure that the entire abstention design exists to prevent, and it violates the
cross-cutting rule that no feature may present an inference as something
stronger than it is.

**`enrichment.csv` must not be resurrected for this purpose.** Its archetype
skills derive from the superseded synthetic generator and can only invert the
project's own assumptions (the generator-inversion ceiling).

## Deferred, not abandoned

The information is still wanted. It is relocated to Amendment 3 in a form that
attributes it to the occupation rather than to the person.

---

# Amendment 3 — network-wide enrichment (new scope)

## The gap this addresses

P2.2 enriches exactly one node out of 430 — the user's own. That is correct for
what P2.2 is: the only lever that raises the classification ceiling, applied
where a lawful basis exists. But it leaves 429 people carrying a job title and
nothing else, and the Phase 3 features assume more.

## An approach considered and rejected

**Proposal:** infer "potential skills" for every person from their job title,
present them as a dropdown, and let the user confirm or remove each one — the
same review pattern that works for uncertain nodes.

**Rejected, for four reasons.**

1. **It is the ruled-out enrichment.** `enrichment.py` already did exactly
   this, mapping roles to archetypes and attributing the archetype's skill pool.
   Substituting O\*NET for the synthetic generator changes the provenance but
   not the logic: it remains *this title implies these skills*, and it cannot
   distinguish two people with identical titles and different actual skills.

2. **The confirmation is unanswerable.** The uncertain-node flow works because
   the user can answer the question — "is 'Deals Associate' a finance role?" is
   knowable. "Does this person know Terraform?" is not knowable for most of 430
   connections.

3. **Confirmation makes it worse, not better.** An unconfirmed inference is
   visibly an inference. A confirmed one reads downstream as verified fact. If
   the user was guessing, the mechanism launders a guess into the data model
   and stamps it with human provenance — the fabrication failure with a UI
   wrapper, and harder to detect than the plain version.

4. **It does not scale, and the partial state is biased.** 430 people times
   ~15 candidate skills is ~6,450 decisions. Nobody completes that. Partial
   completion means skill coverage correlates with which nodes the user
   happened to review, and any Phase 3 ranking would rank partly on that
   artefact.

## The adopted alternative

The underlying need — identifying who suits a project, and who complements a
given profile — is an **occupation-level** question. It is answerable without
attributing unverified skills to individuals.

### P3.6 — Group-level occupational skill profiles

**Definition of done:**

- Each SOC major group carries a skills/tools profile derived from O\*NET,
  displayed as a property of the **occupation**, never of the person.
- Wording on the profile card is unambiguously group-level: "Roles in this
  group typically involve...", not "This person's skills:".
- The profile is visually and semantically distinct from user-supplied
  enrichment, which remains the only per-person skill source.
- The Phase 3 matcher may use group profiles for ranking, provided its
  reasoning states that the basis is occupational rather than individual.
- Nodes in "Needs review" state carry no group profile, since they have no
  group.

**Dependency — this reopens a Phase 1.5 question.** Group-level O\*NET skill
text still requires resolving a major group to records carrying skill data. The
two-stage match deferred in `claude_classifier.py` therefore becomes necessary.
It is materially easier at group level than at individual level: an imprecise
detailed code within the correct major group still yields a broadly correct
occupational description, whereas the same imprecision attributed to a person
would be a false claim about them. Scope this before P3.1.

### P3.7 — Complementarity by occupational distance

**Definition of done:**

- "Who complements this profile?" is answered from SOC structure alone —
  different major group, or distance within the hierarchy — with no skill data
  required.
- Distance logic is documented and its reasoning surfaced to the user.
- Results are framed as occupational complementarity, never as a claim about
  individual capability.

This subsumes part of P3.2 and requires no new data. It works against the
current node table today.

### P2.2b — Optional per-person notes

**Placed in Phase 2, extending P2.2, because it shares P2.2's mechanism:
user-supplied text, provenance-tagged, session-scoped.**

**Definition of done:**

- A free-text notes field is available on any node, populated only by the user.
- No generated suggestions, no confirmation dropdown, no prompt to complete —
  the field is empty until the user chooses to type in it.
- Content is tagged as user-supplied and is visually distinct from both
  taxonomy-derived and title-derived data.
- Notes are searchable via the existing `filter_nodes` field set.
- Notes persist for the session only and are never written server-side.
- Coverage is expected to be low and this is by design: ten people the user
  knows well is more valuable than 430 they do not.

---

# Amended definition of done — P2.5 (current task)

P2.5 and P2.1's UI half are delivered as one unit. The confirmation control has
no surface to live on until the card exists.

1. Selecting any node from the list renders a card: name, raw title verbatim,
   assigned SOC group or "Needs review".
2. Provenance is stated on the card — title-derived, user-corrected, or
   user-enriched.
3. A skills section is present but populated only from user enrichment; absent
   enrichment it states why, rather than presenting group-level data as
   personal. *(Amendment 2)*
4. Uncertain nodes additionally render the confirmation control: 23 SOC groups
   plus an explicit "not an occupation" option.
5. Assignment updates group, colour, and `display_state` on the next rerun,
   with no page reload.
6. Corrections persist in session state, never server-side.
7. "N of M nodes need review" decrements live, derived from the table.
8. The selected node carries a non-occluded name/role label in the 3D scene,
   implemented via `layout.scene.annotations` so it renders in the overlay
   layer and cannot be occluded by nodes in front.
9. Inspection against `network_nodes.csv` confirms no uncertain node renders as
   confidently classified.

**Estimate: 1–1.5 focused days.**

---

# Revised phase contents

**Phase 2** adds P2.2b. Estimate unchanged at 8–11 focused days; P2.2b is small
and shares P2.2's mechanism.

**Phase 3** adds P3.6 and P3.7, and gains a dependency on the two-stage SOC
match. Estimate revised from 5–7 to **7–9 focused days**, the increase being the
detailed-code resolution rather than the features themselves.

**Phase 4** unchanged.

---

# Cross-cutting rule, restated

No feature attributes a skill, tool, or capability to a named individual unless
that individual's own words are its source. Occupational descriptions are
attributed to occupations. This is the same principle as the "Needs review"
node: what is inferred is labelled as inferred, and what is unknown is left
visibly blank.

*Data attribution: this system includes information from the O\*NET 30.3
Database by the U.S. Department of Labor, Employment and Training
Administration (USDOL/ETA), used under the CC BY 4.0 license. O\*NET® is a
trademark of USDOL/ETA.*
