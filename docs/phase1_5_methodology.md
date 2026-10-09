# From Clustering to Classification
### Methodology of the Phase 1 → Phase 1.5 Transition in the Network Visualiser

*Amr Shariff · 19 July 2026*

---

> **Correction note — 21 September 2026 (D-42).** The needs-review figure in this document, 168 of 430 (39.1%), was measured while a classifier defect was caching failed API batches as abstentions. How many of the 168 were affected cannot be recovered, because the cache does not timestamp its entries, so read the figure as an upper bound. At 442 rows the corrected figure is **128 (29.0%)**. Separately, `src/bakeoff.py` classifies through the same cache, so whether the Phase 1.5 evaluation figures carry padded abstentions is an open question, logged as D-47. A padded record removes an answer, so it would lower coverage and could count as a correct abstention on a no-occupation title; precision when the classifier commits is affected only through which titles remain answered. The document below is left as written. See `docs/d42_failure_record.md` for the cause, the evidence and the fix.

> **Update — 22 September 2026 (D-47 closed).** Re-measured on the clean cache with `tools/remeasure_config_e.py`: none of the 100 blind titles changed prediction, and config E's figures are unchanged at 63.5% precision, 74.0% coverage and 0 fabrications. D-42 did not affect the Phase 1.5 evaluation.


# Overview

This document records the methodological transition the network visualiser
underwent between the end of Phase 1 and the close of Phase 1.5. It is written
as a decision log rather than a results summary: the point is not that a final
approach was chosen, but *why* two earlier approaches were abandoned on
evidence, and what the abandonment revealed about the problem.

The headline conclusion is a single sentence. **Grouping a professional network
by occupation is a classification problem constrained by the information content
of the input, not a clustering problem constrained by algorithm choice.** Every
result below is in service of establishing that claim and acting on it.

The transition was triggered by a simple substitution: swapping the synthetic
development dataset (83 generated profiles) for a real LinkedIn connections
export (430 people). Nothing about the pipeline's code changed at the moment of
substitution. What changed was that the real data violated an assumption the
synthetic data had silently satisfied, and that violation cascaded through every
downstream stage.

# Starting Point: Phase 1 on Synthetic Data

Phase 1 built an unsupervised pipeline validated on 83 synthetic profiles drawn
from eleven hand-designed archetypes (finance, data science, several engineering
sub-types, and so on). On that data the pipeline performed well across four
independent validation lenses:

| Stage | Metric | Value |
|:------|:-------|------:|
| Clustering (HDBSCAN) | Silhouette (cosine, noise excluded) | 0.4745 |
| Projection (UMAP) | Trustworthiness (384 to 2 dimensions) | 0.9840 |
| Graph | Modularity $Q$ of the HDBSCAN partition | 0.5224 |
| Graph | ARI, greedy communities vs HDBSCAN | 0.8985 |

These numbers were real, but they were earned on data engineered to be
clusterable. The synthetic generator produced profiles by sampling skills and
tools from archetype-specific pools, with controlled overlap and a handful of
deliberate outliers. By construction, the data contained dense, well-separated
regions for a density-based algorithm to find. The validation confirmed the
pipeline could recover structure that had been placed there on purpose.

This is the first methodological lesson, recorded here because it was not obvious
in advance: **validation on synthetic data confirms that a method can recover
known structure; it says nothing about whether real data contains structure of
the same kind.**

# The Substitution and Its Consequence

The real LinkedIn export contained 443 rows. After dropping 13 contacts with
neither a role nor a company (LinkedIn withholds position for some connections),
430 people remained. A single diagnostic reframed the entire project:

- 430 people
- 371 distinct job titles
- 336 titles occurring exactly once (singletons)
- **1.16 people per title**

The synthetic data had many people per archetype. The real data had, in effect,
one person per title. In the 384-dimensional embedding space this means every
person is very nearly their own neighbourhood: there are no dense regions,
because density requires repetition and the real network barely repeats.

This is why the HDBSCAN stage did not merely perform worse on real data --- it
addressed a structure that was not present.

# Approach One Abandoned: HDBSCAN Clustering

A factorial hyperparameter sweep was run over `min_cluster_size`
$\in \{5, 10, 15, 20, 25\}$ and `min_samples` $\in \{3, 5, 10\}$, with
`min_samples` always explicit so each row of the sweep table was reproducible
(the default `None` silently resolves to `min_cluster_size`, which would vary
two knobs at once).

The sweep exhibited three diagnostic failures, each more informative than the
last.

**Coverage and separation were in direct opposition.** No configuration achieved
both. The two extremes bracket the trade-off:

| Configuration | Clusters | Coverage | Silhouette |
|:--------------|---------:|---------:|-----------:|
| `min_cluster_size=5, min_samples=5` | 15 | 30.5% | 0.5246 |
| `min_cluster_size=15, min_samples=3` | 2 | 70.7% | 0.1382 |

The highest silhouette (0.5246) was computed on the 30.5% of the network that
fell into clusters; the other 69.5% were discarded as noise. Silhouette
evaluated on non-noise points rewards discarding hard cases, so
"maximise silhouette" degenerates into "cluster a small clean core and ignore
the rest". Every configuration that included more people destroyed separation.

**The primary knob went dead.** Above `min_cluster_size=15`, results were
byte-identical at every `min_samples` value. The two clusters HDBSCAN found were
each already larger than 25, so raising the floor never bit. This is not a
tuning surface with an unexplored region; it is a plateau, and the plateau is
the answer.

**A pre-registered gate failed cleanly.** The gate --- silhouette $\geq 0.35$ at
coverage $\geq 50\%$, fixed before the sweep --- was cleared by no configuration.
The gate was set in advance precisely so the result could not be rationalised
after the fact.

A controlled test isolated the cause. Job title text alone (without company) was
compared against title-plus-company text; removing the company string measurably
changed the cluster geometry (the dead knob briefly revived), but no
configuration cleared the coverage bar. The limiting factor was not the feature
set but the fundamental sparsity: 371 distinct two-word titles do not form
density.

HDBSCAN was abandoned for the primary grouping task. It survives only as a
possible Phase 3 experiment for finding sub-structure *within* a large
occupation group, over company text --- the one place structure orthogonal to
the taxonomy might exist.

# Reframing: Clustering Has No Ground Truth

The abandonment of HDBSCAN forced a conceptual clarification that reshaped the
rest of the work.

Silhouette measures geometric separation. It has no notion of correctness --- a
partition can score well while grouping unrelated people, and nothing in the
metric detects the error. The moment the project's priority became *accuracy on
real data*, clustering became the wrong tool, because accuracy presupposes a
target and clustering has none.

Stating the requirement plainly: wanting "barrister" not to be grouped with
"bartender" is a statement that the correct group for a barrister is known in
advance. Once categories are known in advance, the task is **classification, not
clustering** --- assigning each person to a member of a fixed, external taxonomy.

The taxonomy chosen was O\*NET 30.3 (U.S. Department of Labor / ETA, CC BY 4.0),
which provides a hierarchy of occupations with associated skills, tools, and
tasks, and --- critically --- a lexicon of roughly 57,000 real-world job titles
already mapped to occupation codes. Grouping is performed at the level of the
23 SOC major groups, where the taxonomy is most stable: a measurement on the
lexicon showed 93.7% of distinct titles map unambiguously to a single major
group, against only 84.7% at the finer detailed-occupation level.

# Approach Two Abandoned: The Embedding Tier

A tiered classifier was built: an exact lexicon match, a fuzzy match, then an
embedding-similarity fallback against occupation descriptions, and finally an
explicit abstention when nothing cleared threshold. Abstention was treated as a
first-class correct outcome --- "Member", "Volunteer" and "Summer Intern" name
no occupation, and a blank result is the right one.

Measured per tier against a hand-labelled evaluation set, the tiers separated
sharply:

| Tier | Mechanism | Accuracy |
|:-----|:----------|---------:|
| Exact | Verbatim lexicon hit | 85.7% |
| Fuzzy | Token similarity to lexicon | 75.0% |
| Embedding | Cosine vs occupation description | 40.0% |

The embedding tier was net-negative. Adding it raised coverage by ten points but
lowered precision from 81.8% to 74.1%, and all of its outputs scored within a
narrow band (0.55--0.60 cosine), so no threshold could separate its correct
answers from its incorrect ones. Inspection of its errors showed the mechanism:
it matched on shared words, not meaning (mapping "Student Ambassador --- School
of Mathematical Sciences" to a mathematics teacher on the word "Mathematical").
On two-word titles, a sentence-embedding model contributes no world knowledge; it
is a string matcher with additional cost. The tier was removed.

Company was tested as an input signal across multiple configurations and hurt
precision every time. Company encodes industry, which is a distractor for
occupational classification: an accountant at a chemicals firm is an accountant,
but the employer string drags the embedding toward chemistry. Company was
dropped.

# Establishing the Ceiling

The remaining classifier --- deterministic tiers followed by an LLM tier (Claude,
title only) for the abstentions --- was evaluated against a blind set of 100
titles, labelled before any classifier output was seen. Six configurations were
compared. The two informative endpoints:

| Configuration | Precision | Coverage |
|:--------------|----------:|---------:|
| A: deterministic only | 62.5% | 40.0% |
| E: Claude, title only | 63.5% | 74.0% |

No configuration cleared the original 85% precision gate. This prompted the
decisive measurement: **how often do two humans, given the same titles and the
same labelling rules, agree with each other?**

On the 80 titles both labellers committed to (neither abstaining), agreement was
**60.0%**. A second, self-consistency check pointed the same way: a single
labeller, revisiting the same title boundaries (Office Support versus Business
Operations; Life Science versus Healthcare Support), was internally inconsistent
on exactly the titles the classifier also failed on.

This is the central finding of Phase 1.5. **A classifier precision of ~63% is
not a failure relative to an 85% target; it is performance at the human ceiling.**
The 85% gate was never achievable, because the input --- a two-word job title ---
frequently does not contain enough information to determine an occupation, even
for a human expert. "Systems Engineer" is genuinely split between Computer and
Engineering; "Co-Founder" between Business Operations and Management. The residual
error is irreducible ambiguity, not model deficiency.

# Consequences for Product Design

Because the ceiling is a property of the input, three design decisions follow
directly rather than as preferences.

**Coverage-first with visible uncertainty.** The chosen configuration (Claude,
title only) commits to what it can and abstains otherwise, at zero fabrications on
the blind set. On the full 430-person network this yields 262 classified (60.9%)
and 168 flagged uncertain (39.1%). The uncertain nodes are surfaced to the user
for confirmation rather than hidden or guessed. A blank node is honest; a
confidently wrong node that cites an authoritative taxonomy is the worst possible
outcome, because the user cannot detect it.

**Richer input is the only lever that raises the ceiling.** No further prompt or
model change moves performance meaningfully, because the information is absent from
the title. The identified route --- deferred to Phase 2 --- is self-enrichment:
the user supplies their own profile "About" text, which is consented first-party
data and adds the signal titles lack. Automated collection of other people's
profile text remains ruled out on Terms-of-Service and data-protection grounds.

**Classification replaces clustering in the live pipeline.** The SOC major group
becomes the grouping key, and the existing graph and centrality stages were
retained unchanged by having the classifier emit the same file schema the
clustering stage previously produced. The one addition to that contract is an
`is_uncertain` flag carried through to the final node table, which is the concrete
data artifact of the visible-uncertainty design.

# An Incidental Finding: Duplicate Titles and Path Metrics

Integrating real data surfaced a latent bug in the Phase 1 centrality code that
synthetic data had masked. Path-based centralities convert edge similarity to
distance via $d = 1 - s$. When several people share an identical title, they
receive identical embeddings and a cosine similarity of exactly 1.0; floating
point occasionally returns a value fractionally above 1.0, producing a negative
distance, which causes the shortest-path routine to fail with a negative-weight
error. Synthetic profiles never repeated text, so the edge case never arose. The
fix is to clip the distance at zero. This is recorded because it exemplifies the
phase's theme: **assumptions that hold silently on generated data fail loudly on
real data, and finding them is the purpose of testing on real data.**

# Summary of the Transition

| | Phase 1 (end) | Phase 1.5 (end) |
|:--|:--|:--|
| Task framing | Unsupervised clustering | Supervised classification |
| Grouping mechanism | HDBSCAN | O\*NET SOC major group |
| Validation metric | Silhouette (no ground truth) | Precision vs blind labels |
| Data | 83 synthetic profiles | 430 real connections |
| Governing constraint | Algorithm choice | Information in the input |
| Handling of hard cases | Forced into noise or a cluster | Explicit, visible abstention |

Three approaches were ruled out on evidence: HDBSCAN clustering (no density in a
371-title long tail), the embedding classification tier (40% accuracy,
net-negative), and company as a signal (industry is a distractor). The chosen
classifier operates at the measured human ceiling, abstains rather than
fabricates, and hands a per-node uncertainty flag to the visualisation layer.

The most important sentence to carry into Phase 2 is the reframing itself:
the limiting factor was never the method, and no better method exists below the
information content of a two-word title. The only way forward is more input.

---

*Data attribution: this document describes a system that includes information from
the O\*NET 30.3 Database by the U.S. Department of Labor, Employment and Training
Administration (USDOL/ETA), used under the CC BY 4.0 license. O\*NET is a
trademark of USDOL/ETA.*
