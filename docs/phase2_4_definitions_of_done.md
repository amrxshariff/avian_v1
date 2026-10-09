# Phases 2–4: Definitions of Done

### Network Visualiser — post–Phase 1.5 delivery plan

*Amr Shariff · 19 July 2026*

---

> **Correction note — 21 September 2026 (D-42).** This plan expects roughly 40% of a real network to be flagged uncertain. That expectation came from figures inflated by a classifier defect that cached failed API batches as abstentions. On the real 442-row network the corrected figure is **128 (29.0%)**. The plan's design, a visible and correctable uncertain population, is unaffected. The document below is left as written. See `docs/d42_failure_record.md` for the cause, the evidence and the fix.


## Framing

Phase 1.5 established that occupation grouping is a classification problem with a
~60% accuracy ceiling on job titles alone, and that ~40% of any real network will
be flagged uncertain. This reshaped Phase 2. The two highest priorities below —
the uncertain-node confirmation flow and self-enrichment — are **not polish**;
they are the direct product consequences of that finding, and everything the
earlier roadmap described is built on top of them.

Each item has an explicit, testable definition of done (DoD). A phase is complete
only when every DoD in it passes and a QA checkpoint has been signed off. Ordering
within a phase is dependency-driven, not preference.

Estimates assume focused part-time work and carry no fixed calendar deadline.

---

# Phase 2 — MVP Dashboard with Uncertainty and Enrichment

**Goal:** a deployable single-user dashboard that renders a real network honestly
— grouping what it can, visibly flagging what it cannot, and letting the user both
correct uncertain nodes and enrich their own profile. **Estimated 8–11 focused days**
(larger than the original roadmap's 5–7, because the two ceiling-driven priorities
are new scope).

The two priorities (P2.1, P2.2) are listed first because they are load-bearing.
The dashboard foundation (P2.3–P2.9) is sequenced after them in dependency order
but much of it can proceed in parallel.

## Priority 1 — Uncertain-node confirmation UX (P2.1)

The ~40% of nodes the classifier abstains on must be visible and user-correctable.
This is the concrete realisation of the "coverage-first with visible uncertainty"
decision.

**Definition of done:**

- Nodes with `is_uncertain = True` render in a visually distinct, neutral style
  (e.g. grey) clearly separated from the classified colour palette, with a legend
  entry labelled "Needs review" (never "Outlier").
- Clicking an uncertain node opens a confirmation control that shows the raw
  title and lets the user assign a SOC major group from the 23-option list, or
  explicitly mark it "not an occupation".
- A user assignment updates that node's group, colour, and `is_uncertain` state
  live, without a full page reload.
- User corrections persist for the session (Version A: ephemeral, never written
  server-side); a documented mechanism exists to carry them for the session's
  duration.
- A visible counter shows "N of M nodes need review", decrementing as the user
  resolves them.
- The dashboard never presents an uncertain node as if it were confidently
  classified — verified by inspection against `network_nodes.csv`.

## Priority 2 — Self-enrichment via "About" text (P2.2)

The only lever that raises the classification ceiling is richer input. The user
supplies their own profile "About" text as consented first-party data.

**Definition of done:**

- A single text input lets the user paste their own "About" section (optional;
  the dashboard is fully functional without it).
- Pasted text enriches **only the user's own node** — it is never attributed to
  any other person, and no other person's data is collected or scraped.
- The enriched text materially improves the user's own classification and/or the
  skill profile shown on their card (demonstrable on at least one worked example).
- The enrichment is clearly labelled as user-supplied, distinct from taxonomy-
  derived data.
- A short, visible privacy note states the text is processed ephemerally and not
  stored server-side.
- No pathway exists — by design or by accident — to collect other connections'
  "About" text; this is verified and documented as an explicit non-goal.

> **Correction note — 8 October 2026 (D-84).**
>
> **What was specified.** The criterion above: the enriched text "materially
> improves the user's own classification … (demonstrable on at least one worked
> example)". It was built as a side-by-side of two readings, one from the title
> alone and one from the title with the user's About text. It passed at Gate B on
> 2 September.
>
> **What the measurement showed.** Six runs on one title and one About text, with
> identical input each time. The title-only reading gave group 15 at 0.95 every
> time. The About-informed reading abstained three times, and assigned 15 three
> times, at 0.95, 0.75 and 0.75. A side-by-side therefore made a claim about the
> user's writing that the code cannot support: half the time the same description
> produces the opposite outcome. A single worked example cannot demonstrate
> improvement on a path that unstable, so the criterion was met on one draw. The
> measurement covers one title and one text: it establishes that the path is
> unstable, not how unstable it is in general.
>
> **What ships instead.** The About-informed reading alone, labelled as coming from
> the user's own description, with the caveat that it is one answer from a
> classifier that can answer differently when asked again. That caveat is true and
> sufficient for one reading; it was never sufficient for a comparison. The
> comparison is withdrawn from the product, and the "materially improves"
> criterion is withdrawn with it, since the panel no longer claims an improvement.
> The two-reading form remains on the command line (`python -m src.self_enrichment`)
> as the measurement path. The criteria above are otherwise left as written:
> optional, the user's own node only, labelled as user-supplied, the privacy note,
> and no pathway to anyone else's text.

## Foundation — the dashboard the priorities sit on (P2.3–P2.9)

### P2.3 — 3D network visualisation
**DoD:** a 3D Plotly network renders all ~430 nodes from `network_nodes.csv`,
positioned by the UMAP coordinates, coloured by SOC major group with uncertain
nodes greyed. The user can rotate, zoom, and pan smoothly at this node count with
no perceptible lag.

### P2.4 — Real-time search
**DoD:** a search box filters/highlights nodes by name, role, SOC group, and any
enriched skill terms, updating live as the user types; a query with no matches
returns a clear empty state rather than a blank canvas.

### P2.5 — Click-for-detail profile cards
**DoD:** clicking any node opens a detail card showing name, raw title, assigned
SOC group (or "needs review"), taxonomy-derived skills/tools where classified,
and provenance (title-derived vs user-enriched). Uncertain nodes show the
confirmation control from P2.1.

### P2.6 — SOC-tree cluster zoom
**DoD:** the user can zoom from major group into the occupations within it using
the SOC hierarchy (not a clustering re-run); outer group labels remain visible
while zoomed; multiple groups can be selected at once, dimming the rest.

### P2.7 — Cluster summaries
**DoD:** each SOC group has an auto-generated 2–3 sentence summary of its
composition, generated once and cached; summaries are accurate to the members
actually in the group and regenerate if membership changes via P2.1 corrections.

### P2.8 — Chat interface
**DoD:** a chat panel is wired to the Anthropic API and can answer questions
grounded in the current network state (e.g. "who works in finance?"), reading
from the live node table including any user corrections; the API key is handled
via secrets, never committed.

### P2.9 — Deployment
**DoD:** the dashboard is deployed to Streamlit Community Cloud, boots cleanly
from the repo with no real personal data present (synthetic or an
upload-your-own flow), runs the full render without crashing, and a README
records how to run it locally with a real export. A short demo recording exists.

## Phase 2 QA checkpoint
Every P2 DoD passes; the deployed app renders a real network with grey nodes
present and correctable; the user can enrich their own node; no crash across the
core interactions; no real personal data in the public deploy.

---

# Phase 3 — Team Composition and Network Insight

**Goal:** turn the classified, enriched network into a decision tool — ranked team
suggestions with reasoning, and structural insight into the network.
**Estimated 5–7 focused days.** Depends on a stable Phase 2 node table and the
similarity graph.

### P3.1 — Team composition queries
**DoD:** a natural-language query specifying a team (e.g. "3 developers and a
product manager for a SaaS startup") returns a ranked shortlist of people from
the network, with a short written justification per person, produced via the
Anthropic API grounded in the node table and skills.

### P3.2 — Complementarity ranking
**DoD:** team suggestions are ranked by complementarity (diversity of occupation
and skills across the proposed team), not merely individual fit; the ranking logic
is documented and the reasoning surfaced to the user.

### P3.3 — Serendipity suggestions
**DoD:** a "people you should connect" feature uses graph traversal over the
similarity graph to surface non-obvious relevant people; results are framed
honestly as skill/occupation bridges, not as social connections (the graph is a
similarity graph, not a social network).

### P3.4 — Network insight: top connectors
**DoD:** a chart ranks people by betweenness centrality, presented with the
correct interpretation — bridges between skill areas, explicitly not "most
socially connected"; the chart reads from the centrality columns already in
`network_nodes.csv`.

### P3.5 — Cluster skill matrices and pairings
**DoD:** for each SOC group, a view shows the skill/tool composition; and a
"typical co-founder pairing" feature suggests complementary group pairings with a
brief rationale.

## Phase 3 QA checkpoint
Team queries return sensible, reasoned shortlists on the real network; serendipity
and connector features are framed with the correct (similarity, not social)
interpretation; every insight reads from the canonical node/centrality data.

---

# Phase 4 — Polish, Narrative, and Public Launch

**Goal:** production-quality finish and a public, documented release.
**Estimated 4–5 focused days.** Depends on Phases 2 and 3 being feature-complete.

### P4.1 — Team synergy narratives
**DoD:** team suggestions carry a short narrative of *why* the group works
together (complementary strengths, coverage gaps filled), not just who is in it.

### P4.2 — UI polish
**DoD:** micro-interactions and animations on the core interactions; a working
dark mode; visual consistency across all views.

### P4.3 — Export
**DoD:** the user can export a team suggestion or network summary to PDF.

### P4.4 — Onboarding
**DoD:** a first-run onboarding tour walks a new user through upload, the grey
"needs review" concept, self-enrichment, and the assistant.

### P4.5 — Performance
**DoD:** the full pipeline and dashboard perform acceptably on a network at least
as large as the 430-node real set; any known scaling limits are documented.

### P4.6 — Documentation and launch
**DoD:** complete README (run locally, deploy, data attribution); the methodology
doc linked; a video demo recorded; the repository made public with the O\*NET
attribution and license compliance in place.

## Phase 4 QA checkpoint
The public repository is launched, documented, and license-compliant; the demo is
recorded; the deployed app is stable and onboards a first-time user without
external explanation.

---

## Cross-cutting definition of done (applies to every phase)

- **Version A privacy holds:** real personal data is processed ephemerally, never
  persisted server-side, never committed to the repo.
- **Honest representation:** no feature presents an uncertain classification, a
  similarity edge, or a centrality score as something stronger than it is.
- **License compliance:** O\*NET 30.3 attribution present in README and dashboard
  footer wherever taxonomy data is shown.
- **QA before advancing:** the phase checkpoint is signed off before the next
  phase begins.

---

*Data attribution: this plan describes a system that includes information from the
O\*NET 30.3 Database by the U.S. Department of Labor, Employment and Training
Administration (USDOL/ETA), used under the CC BY 4.0 license. O\*NET® is a
trademark of USDOL/ETA.*
