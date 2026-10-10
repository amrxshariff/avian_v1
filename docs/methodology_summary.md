---
title: "Methodology Summary"
subtitle: "Skill-Clustered Network Visualiser — Phase 1 (Days 0–8)"
author: "Amr Shariff"
date: "July 2026"
geometry: "a4paper, margin=2.5cm"
fontsize: 11pt
linkcolor: blue
---

> **Correction note — 6 October 2026 (D-77).** This document records Phase 1,
> and it does not describe the method the project uses. Every figure in it was
> earned on 83 generated profiles built to be clusterable. That includes all
> three that §11 cites as validation evidence: silhouette 0.4745, HDBSCAN
> modularity 0.5224 and ARI 0.8985.
>
> On the real network the convergence did not hold. Over 430 people, the
> agreement between greedy communities and HDBSCAN (ARI) fell to 0.047, and
> HDBSCAN's modularity to 0.3352; over 442 people they were 0.0557 and 0.3429.
> HDBSCAN was discarded at the Phase 1.5 close-out on 19 July 2026, in favour of
> classification against the SOC taxonomy. So:
>
> - §10's conclusion that "the structure is real" holds for the generated data
>   only.
> - §11's ledger, which lists HDBSCAN as chosen, records a decision that was
>   later reversed.
> - The "complete and validated" engine of §13 was only partly carried forward.
>   The embeddings, projection, graph and centrality were; the clustering and
>   its labels were not.
>
> See `docs/phase1_5_methodology.md`, which reports these Phase 1 figures and
> makes their collapse on real data its central lesson. The run that produced
> the figures here survives only in the private repository's history. The
> document below is left as written.

## About this document

This is the readable, decision-led account of Phase 1 of the Skill-Clustered
Network Visualiser — the "Core ML Engine" that turns a set of professional
profiles into a validated, explorable network. It is written for a general
technical reader and deliberately keeps the mathematics light: the aim is to
explain **what was built, why each design choice was made, what the alternatives
were, and how each stage was shown to work.** A companion document,
*Mathematical Methodology*, gives the formal definitions and equations for every
technique named here.

The single idea to carry through the whole thing: at every step we make a choice,
name the credible alternative we rejected, and back the decision with a number the
pipeline actually produced.

---

## 1. What the engine does, in one paragraph

The engine reads each person's experience and turns it into a numerical
"fingerprint" of meaning; groups people whose fingerprints are alike; lays the
whole set out as a two-dimensional map; names each group automatically; connects
similar people into a network; and finally measures who occupies the important
positions in that network. Every one of these steps is validated on data whose
correct answer is known in advance, so the results can be graded rather than merely
admired.

## 2. Five principles behind every decision

Before the individual stages, it helps to state the design philosophy, because the
same five commitments recur throughout and explain most of the choices.

**Prove it on a known answer first.** The whole pipeline is developed on
synthetic data whose "true" groups we planted ourselves. Only a pipeline that can
recover a known structure earns trust on unknown data.

**One consistent notion of similarity.** A single measure of closeness — the
*angle* between two fingerprints, called cosine similarity — is used from the first
stage to the last. No stage silently redefines what "similar" means, which is a
common and hard-to-diagnose source of error.

**Every choice defended against a named alternative.** For each algorithm there
was an obvious, popular competitor. The document records which one, and the concrete
reason it was passed over — not as an afterthought, but as the point.

**Keep the signal others discard.** Many tools force every data point into a
tidy group. This engine deliberately preserves loners (people who fit no group) and
isolates (people connected to no one above the similarity bar), because in a
professional network an individualist or a bridge is information, not an error.

**Reproducibility as a feature.** Fixed random seeds, cached intermediate
results, and a single canonical output mean a stranger can clone the repository and
reproduce every number in this document.

## 3. A testbed with a known answer — synthetic data (Days 0–2)

The project's founding decision was to **not** scrape LinkedIn — a route that
breaches the platform's terms, creates real data-protection obligations, and reads
as a liability rather than an asset on an application. Instead the engine is fed
from permitted sources, and developed against a synthetic dataset.

Choosing synthetic data first pays off twice. It sidesteps the compliance problem
entirely, and — more importantly for the methodology — it gives us **ground
truth**. We generated 83 fictional profiles drawn from seven distinct professional
"archetypes", then deliberately corrupted about 15% of the fields to make the data
realistically messy. Because we know which archetype each profile came from, every
later stage can be scored against the right answer. When the clustering later
recovers seven groups that match the seven archetypes, that is evidence the engine
works — not a coincidence to be hoped for.

## 4. Turning words into meaning — embeddings (Day 3)

A computer cannot compare "experience" directly, so each profile's text is
converted into a list of 384 numbers — coordinates in a "meaning space" where
people with similar backgrounds land near one another, even when they describe
themselves in different words. This is done with a pretrained language model
(`all-MiniLM-L6-v2`).

The alternative was simple keyword counting (TF–IDF over the raw profiles) or a
paid embedding service. Keyword counting was rejected because it treats "ML
Engineer" and "Data Scientist" as unrelated — it matches spellings, not meaning.
A paid API was rejected because a small, local, free model keeps the whole project
runnable by anyone, anywhere, with no keys or costs — exactly what a shareable
portfolio piece needs. The model is small and fast enough to run on a laptop, yet
captures genuine semantic similarity.

This is also where the project's consistent measure of closeness is introduced.
Two people are judged alike by the **angle** between their fingerprints, not their
magnitude — so a person who wrote a long profile and one who wrote a short profile
are still recognised as similar if they point the same way in meaning space. Angle
is the natural, stable choice in a space of this many dimensions, and it is the
measure the model was trained to make meaningful.

## 5. Finding the natural groups — clustering (Day 4)

The central modelling decision of Phase 1 is how to group people, and here the
engine uses **HDBSCAN** rather than the far more common **K-means**.

K-means has three properties that are wrong for this problem. It requires you to
state the number of groups in advance — but discovering how many communities exist
is part of the question. It assumes groups are round, evenly sized blobs — but real
skill clusters are irregular. And it forces every single person into a group — so a
genuine one-of-a-kind profile gets absorbed into whichever cluster is least wrong,
polluting it.

HDBSCAN avoids all three. It finds dense regions of similar people and discovers
the number of groups by itself; it copes with irregular shapes; and it is willing to
label a person as an **outlier** rather than mis-file them. On our data it found
**seven groups and flagged two outliers** (about 2.4% of people) — the two most
idiosyncratic profiles left honestly ungrouped rather than forced.

To check the grouping is real rather than arbitrary, we use the **silhouette
score**, which asks, for each person, whether they sit closer to their own group
than to the nearest rival group. The engine scores **0.4745** — a clear, positive
separation. For messy real-world text (as opposed to clean textbook data), a value
in this range indicates coherent, well-separated groups.

## 6. Drawing the map — projection (Day 5)

A 384-dimensional cloud of points cannot be drawn, but a picture is essential both
for the eventual dashboard and for sanity-checking the clusters by eye. So the
engine flattens the fingerprints down to two dimensions using **UMAP**, chosen over
the popular **t-SNE**.

The difference that matters is what each method tries to preserve. t-SNE is
excellent at keeping *near* neighbours together but tends to scramble the *global*
arrangement — so the relative positions of whole clusters become meaningless, and
distance between clusters on the plot can't be trusted. UMAP preserves both local
neighbourhoods and the broader layout, so the map is faithful at both scales, and it
is faster to compute. (Plain dimensionality reduction such as PCA was ruled out
earlier still — it is too crude to capture the non-linear structure of meaning.)

A map can lie by placing strangers next to each other, so we measure exactly that
with a score called **trustworthiness**, which counts how often a projected
neighbour was *not* really a neighbour in the original space. The engine scores
**0.9840** out of 1 — the map almost never introduces false neighbours, which is
what licenses us to reason about the clusters from the picture itself.

## 7. Naming the groups — labelling (Day 6)

Groups are useless if a human has to inspect them to know what they are, so the
engine labels each cluster automatically by finding the words that are common
*inside* that cluster but rare across the others — the terms that make a group
distinctive. This recovered clean, human-readable names for all seven groups, for
example *Engineering / Ansys / Engineer*, *Drug / Pharmacology / Clinical*, *Design
/ Interior*, and *VBA / Portfolio / Finance*.

This step quietly closes the loop opened in Day 0: the seven groups the engine
discovered, entirely from the text, are the same seven archetypes we originally
planted. The pipeline found what was really there.

## 8. From similarity to a network — the graph (Day 7)

Grouping tells us *who is alike*; a network tells us *how everyone relates* — who
bridges between groups, who sits at the centre, who stands apart. So the engine
connects the people into a graph, drawing a link between two people whenever their
similarity clears a chosen bar.

Rather than an arbitrary rule, that bar is set by a single, interpretable dial: we
choose a **target average number of connections per person** (here, eight) and let
the bar follow. This keeps the network dense enough to reveal structure and sparse
enough to read, and the knob means something concrete. The result is 332
connections across the 83 people. Consistent with the outlier philosophy, four
people whose every similarity falls below the bar are left as **isolates** rather
than artificially connected — low affinity is treated as signal.

The validation here is the strongest evidence in the whole of Phase 1. We measure
**modularity**, which asks whether there really are more connections *inside* the
groups than random chance would produce; the engine scores **0.5224**, well into
"real community structure" territory. But the decisive point is *agreement across
independent methods*: a completely separate community-detection algorithm, working
only from the network and knowing nothing about the original clustering, draws
almost exactly the same group boundaries — an agreement score (Adjusted Rand Index)
of **0.8985**, where 0 is chance and 1 is identical. In other words, the same
groups emerge whether you cluster in meaning-space, or detect communities in the
network — three routes to the same structure.

## 9. Measuring who matters — centrality (Day 8)

The final stage asks a different question of each person: not *which group are you
in*, but *how important is your position?* Importance, though, has several distinct
meanings, so the engine reports four complementary measures rather than pretending
there is one:

- **Most-connected** (degree) — simply how many links a person has.
- **Broker** (betweenness) — how often a person sits on the shortest path between
  others, i.e. how much they bridge otherwise separate groups.
- **Prestige** (PageRank) — importance that flows from being connected to *other*
  important people, in the spirit of the algorithm behind web search.
- **Reach** (closeness) — how close a person is, on average, to everyone they can
  reach.

Two choices here are worth calling out, because both are forced by an honest
property of the data: the network is not fully connected — it falls into 13
separate pieces, with four people entirely alone. That disconnection breaks the
naïve versions of two measures. For prestige we use PageRank instead of the
classical **eigenvector centrality**, because eigenvector centrality quietly
collapses on a fragmented network — run on our graph it drove **51 of the 83 people
(61%) to essentially zero**, a misleading answer for two-thirds of the network.
PageRank, by contrast, remains meaningful and gives even the isolated people a
small, sensible score. For reach we use a corrected form of closeness
(Wasserman–Faust) that stops a person trapped on a tiny two-person island from
appearing as central as a genuine hub.

The most useful insight from this stage is that **broker and prestige are not the
same thing**, which is exactly why both are reported. Some people score high on
both — central within their group *and* bridging to others — and these dual-role
individuals are the highest-value connectors in the network. Others are strong
brokers without being prestige hubs, or vice versa. Reassuringly, prestige is spread
across five different groups rather than monopolised by one, indicating a healthy
network with a genuine anchor in each community. (Looking ahead commercially, those
dual-role connectors are precisely what a future team-allocation product would want
to surface automatically.)

## 10. Why the result can be trusted — convergent validation

The reason to believe Phase 1 is not any single score but that **four independent
checks, using different mathematics and different assumptions, all agree**. This is
the methodological heart of the project.

| Lens | What it inspects | Score | The claim it supports |
|---|---|---|---|
| Silhouette | tightness/separation of groups | 0.4745 | the groups are internally coherent |
| Trustworthiness | honesty of the 2-D map | 0.9840 | the picture faithfully reflects the data |
| Modularity | community structure in the network | 0.5224 | groups coincide with dense network regions |
| Adjusted Rand Index | agreement of two independent methods | 0.8985 | different methods find the same groups |

No one of these could be dismissed as an artefact of a particular technique,
because they come at the data from genuinely different angles — the geometry of the
points, the honesty of the projection, the structure of the network, and the
agreement between two unrelated grouping algorithms. When four such different tests
point the same way, "the structure is real" stops being an assertion and becomes a
defensible conclusion. The UMAP map provides a fifth, visual confirmation that a
human can read at a glance.

## 11. The decision ledger

The entire Phase-1 argument condensed into one table: for each decision, the option
taken, the credible alternative rejected, and the evidence that vindicates it.

| Decision | Chosen | Alternative rejected | Why, and the evidence |
|---|---|---|---|
| Data source | Synthetic + own export | Scraping LinkedIn | Compliant *and* gives known ground truth; all 7 archetypes recovered |
| Meaning representation | Local sentence-embedding model | Keyword counting / paid API | Captures meaning not spelling; free and portable |
| Similarity measure | Cosine (angle) | Euclidean (distance) | Length-invariant, stable in high dimensions; used consistently end-to-end |
| Clustering | HDBSCAN | K-means | Finds the number of groups, handles irregular shapes, flags outliers; silhouette 0.4745 |
| Projection | UMAP | t-SNE / PCA | Preserves global *and* local structure, faster; trustworthiness 0.9840 |
| Labelling | Distinctive-term extraction | Manual naming | Automatic and interpretable; recovered all 7 archetype names |
| Network edges | Thresholded by target degree | Fixed k-nearest-neighbour | One interpretable density dial; modularity 0.5224 |
| Community check | Modularity + second method + agreement score | Single method | Cross-method corroboration; ARI 0.8985 |
| Prestige metric | PageRank | Eigenvector centrality | Robust on a fragmented network; eigenvector zeroed 61% of nodes |
| Reach metric | Wasserman–Faust closeness | Naïve closeness | Correctly handles the 13 disconnected components |

## 12. Engineering discipline and reproducibility

The engine is built as a chain of independent stages, each with a clean input and
output, so any one can be tested or swapped without disturbing the others. Random
seeds are fixed throughout, so results are identical on every run. The expensive
step — computing the fingerprints — is cached, so the pipeline is cheap to re-run.
And the whole of Phase 1 funnels into a **single canonical table** of 83 people with
their group, map coordinates, and four importance scores, which is the sole input
the Phase-2 dashboard will consume. A stranger can clone the repository and
reproduce every figure in this document from the README.

## 13. What Phase 1 sets up

The Core ML Engine is now complete and validated. Everything downstream reuses it:
the canonical people-table drives the interactive dashboard (Phase 2); the same
fingerprints power the natural-language matcher that will answer questions like
"who in this network suits a fintech startup?" (Phase 3); and the entire engine
generalises, essentially unchanged, from a personal network to a business tool for
team allocation and project staffing (the eventual Stage-2 product). The
methodological care taken in Phase 1 — every choice justified, every stage
validated from multiple angles — is the foundation the rest of the project stands
on.
