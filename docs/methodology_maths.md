# Skill-Clustered Network Visualiser — Mathematical Methodology

> **Correction note — 6 October 2026 (D-77).** The table below is headed "real values", and
> the introduction speaks of "the current build". Both mean values actually
> measured at the time of writing (July 2026), over the 83 generated Phase 1
> profiles: N = 83, as stated at each point of use. They are not values for the
> real network, or for the method the project now uses.
>
> Over the real network the cross-algorithm agreement collapsed. ARI was 0.047
> and HDBSCAN modularity 0.3352 over 430 people, and 0.0557 and 0.3429 over 442.
> HDBSCAN was discarded at the Phase 1.5 close-out on 19 July 2026. The
> mathematics of each object below is unaffected, but the "convergent evidence"
> the document closes on held for the generated data only. See
> `docs/phase1_5_methodology.md`. The run that produced these figures survives
> only in the private repository's history. The document below is left as
> written.

A complete reference for every mathematical object in the pipeline, from the
embedding space through to graph validation. Written as a standing appendix for
the UCL MSc write-up. Reported metrics from the current build are worked in
where relevant.

**Convergent validation at a glance (real values):**

| Lens | Metric | Value | What it measures |
|---|---|---|---|
| Geometric separation | Silhouette | **0.4745** | own-cluster vs nearest-rival distance |
| Neighbourhood preservation | Trustworthiness | **0.9840** | honesty of the 2-D projection |
| Graph community structure | Modularity $Q$ | **0.5224** | within-community edges vs a random null |
| Cross-algorithm agreement | ARI | **0.8985** | greedy graph communities vs HDBSCAN |

The pipeline validates a *single* geometric object — the embedding — through
four mathematically independent lenses. Their convergence is the core
robustness argument.

---

## 0. The pipeline as a composition of maps

A person begins as text and is mapped
$$\text{text} \xrightarrow{\ \text{embed}\ } x \in \mathbb{R}^{384}
\xrightarrow{\ \text{HDBSCAN}\ } \text{cluster label}
\ \big/\ \xrightarrow{\ \text{UMAP}\ } (x,y) \in \mathbb{R}^{2}
\ \big/\ \xrightarrow{\ \text{threshold}\ } \text{graph } G.$$
Everything downstream is derived from the one representation $x$. The maths
splits into (i) the geometry of the embedding space, (ii) the objectives
optimised over it, and (iii) the combinatorics of the graph built on top.

---

## 1. Embedding space and cosine geometry

Each profile is a vector $x_i \in \mathbb{R}^{384}$ (sentence-transformer
`all-MiniLM-L6-v2`). All similarity is **cosine**:
$$\cos\theta_{ij} = \frac{\langle x_i, x_j\rangle}{\|x_i\|\,\|x_j\|}
= \frac{\sum_k x_{ik}x_{jk}}{\sqrt{\sum_k x_{ik}^2}\ \sqrt{\sum_k x_{jk}^2}}.$$

Cosine discards magnitude and keeps direction, so two profiles with the same
skill mix but different text length count as similar. Geometrically this is work
on the unit sphere $S^{383}$. The link to Euclidean distance, for unit vectors:
$$\|\hat{x}-\hat{y}\|^2 = 2 - 2\langle \hat{x},\hat{y}\rangle = 2\,(1-\cos\theta).$$
So cosine distance $d_{\cos} = 1-\cos\theta$ is monotone in squared Euclidean
distance *after normalisation*. This is why using `metric='cosine'` consistently
through HDBSCAN and UMAP is coherent — all stages operate on the same spherical
geometry.

**Scaling note.** sklearn's HDBSCAN computes cosine via brute-force pairwise
distances, i.e. $O(n^2)$ in the number of people. Fine at $n=83$; a documented
consideration if the network grows.

---

## 2. HDBSCAN — density, a spanning tree, and a persistence hierarchy

The richest stage: estimate density, build a tree, read clusters off its
persistence. Parameters used: `min_cluster_size=5`, `min_samples=3`,
`metric='cosine'`.

**Core distance (a $k$-NN density estimate).** With $k=$ `min_samples`,
$$\operatorname{core}_k(x) = d\big(x,\ \text{its } k\text{-th nearest neighbour}\big).$$
Small core distance $\Rightarrow$ dense neighbourhood
(density $\propto k / \operatorname{core}_k(x)^{\dim}$).

**Mutual reachability distance (density-aware metric).**
$$d_{\text{mreach}}(a,b) = \max\{\operatorname{core}_k(a),\ \operatorname{core}_k(b),\ d(a,b)\}.$$
This inflates distances in sparse regions so noise cannot cheaply bridge dense
clumps, while leaving dense regions unchanged.

**The greedy step (part one — provably optimal).** HDBSCAN builds the
**minimum spanning tree** of the complete graph weighted by $d_{\text{mreach}}$,
sorting edges ascending and merging with union–find. This is **Kruskal's
algorithm**, equivalent to single-linkage clustering on the mutual-reachability
metric. *This greedy construction is globally optimal* — see §8 for why.

**Condensed hierarchy.** Cutting the dendrogram at every height gives a full
hierarchy. `min_cluster_size` condenses it: a split is a real bifurcation only
if both children have $\ge$ `min_cluster_size` points; otherwise the smaller
branch is treated as points *falling out* of the parent, not a new cluster.

**Stability via persistence.** Reparametrise density as $\lambda = 1/\text{distance}$.
A cluster $C$ is born at $\lambda_{\text{birth}}(C)$; each member $p$ falls out at
$\lambda_p$. Cluster stability is the total persistence
$$S(C) = \sum_{p \in C}\big(\lambda_p - \lambda_{\text{birth}}(C)\big).$$
Clusters surviving a wide band of density levels score high.

**Selection (maximise total stability).** HDBSCAN selects the non-overlapping
clusters (an antichain in the condensed tree) maximising $\sum S(C)$, resolved
bottom-up: keep the parent if $S(\text{parent}) \ge \sum_{\text{children}} S$,
else keep the children. Unclaimed points get label $-1$ (the outliers). This is
why HDBSCAN "finds the natural number of clusters" — that number maximises
persistence rather than being supplied as $k$.

**Result:** 7 clusters, 2 outliers (2.4% outlier rate) over the $(83,384)$ matrix.

---

## 3. Silhouette — geometric separation

For point $i$ in cluster $C_I$:
$$a(i) = \frac{1}{|C_I|-1}\sum_{\substack{j \in C_I \\ j \ne i}} d(i,j),
\qquad
b(i) = \min_{J \ne I}\ \frac{1}{|C_J|}\sum_{j \in C_J} d(i,j),$$
the mean intra-cluster distance and the mean distance to the *nearest rival*
cluster. The silhouette coefficient:
$$s(i) = \frac{b(i)-a(i)}{\max\{a(i),\,b(i)\}} \in [-1,1],
\qquad s(i)=0 \text{ for singletons}.$$
The sign answers "is this point better placed here or next door?" The reported
**0.4745** is the mean over clustered points; noise ($-1$) is excluded because it
is not a cluster and would otherwise poison $b(i)$ — a documented choice, not an
oversight.

---

## 4. UMAP — fuzzy simplicial sets and a cross-entropy

A map $\mathbb{R}^{384} \to \mathbb{R}^2$ preserving neighbourhood structure.
Topological in derivation, but the computable core is two probability graphs and
a cross-entropy between them. Parameters used: `n_neighbors=15`, `min_dist=0.1`,
`metric='cosine'`.

**High-dimensional memberships.** For each $i$, let $\rho_i$ be the distance to
its nearest neighbour (enforces local connectivity), and pick scale $\sigma_i$ by
binary search so that
$$\sum_j \exp\!\left(-\frac{\max\big(0,\ d(x_i,x_j)-\rho_i\big)}{\sigma_i}\right)
= \log_2 k, \qquad k = \texttt{n\_neighbors}.$$
This yields directed weights $p_{j\mid i}$, symmetrised by a fuzzy union
(probabilistic t-conorm):
$$p_{ij} = p_{j\mid i} + p_{i\mid j} - p_{j\mid i}\,p_{i\mid j}.$$

**Low-dimensional memberships.** In the plane,
$$q_{ij} = \big(1 + a\,\|y_i - y_j\|^{2b}\big)^{-1},$$
where $a,b$ are fitted (least squares) so the curve matches `min_dist`; for
$0.1$, roughly $a \approx 1.58,\ b \approx 0.90$. `min_dist` controls how tightly
points may clump; `n_neighbors` = $k$ trades local detail against global structure.

**Objective (fuzzy-set cross-entropy).**
$$\mathcal{L} = \sum_{ij}\left[\,p_{ij}\log\frac{p_{ij}}{q_{ij}}
+ (1-p_{ij})\log\frac{1-p_{ij}}{1-q_{ij}}\right],$$
minimised by SGD with negative sampling. The first term is an *attractive* force
along high-$p$ edges; the second a *repulsive* force from sampled non-edges. This
attraction/repulsion balance is what pushes clusters apart on the canvas.

**Trustworthiness (validation).**
$$T(k) = 1 - \frac{2}{n\,k\,(2n-3k-1)}
\sum_{i}\ \sum_{j \in U_i^{(k)}}\big(r_{ij}-k\big),$$
where $U_i^{(k)}$ are points among $i$'s $k$ nearest in 2-D but *not* in
$\mathbb{R}^{384}$, and $r_{ij}$ is $j$'s rank from $i$ in the original space. It
penalises exactly the false neighbours that make a projection misleading. The
reported **0.9840** says the layout is an honest witness — independent of
silhouette, which is why it counts as a separate validation.

---

## 5. TF-IDF cluster labelling — the lexical layer

Purely a weighting on word counts (no semantics; that is the embedding's job).
With sublinear term frequency and smoothed inverse document frequency, on
per-person documents ($N$ people):
$$\text{tf}(t,d) = 1 + \log f_{t,d},
\qquad
\text{idf}(t) = \ln\frac{1+N}{1+\text{df}(t)} + 1,
\qquad
w_{t,d} = \text{tf}(t,d)\cdot\text{idf}(t),$$
each document vector $L^2$-normalised: $v_d / \|v_d\|$. A cluster's label is the
top coordinates of the mean vector
$$\bar{v}_C = \frac{1}{|C|}\sum_{d \in C} v_d.$$
The $\ln$ in idf is load-bearing: as $\text{df}(t) \to N$, $\text{idf} \to 0$, so
ubiquitous words vanish and only distinctive vocabulary survives. Preprocessing:
`ngram_range=(1,2)` (keeps "data science" intact), `min_df=2`, `max_df=0.8`.

**Optional refinement (soft-membership weighting).** Using the HDBSCAN
membership strength $\pi_p$ (`probability`) as weights,
$$\bar{v}_C = \frac{\sum_{p \in C} \pi_p\, v_p}{\sum_{p \in C}\pi_p},$$
down-weights marginal members so labels reflect the cluster core.

---

## 6. Graph construction — order statistics and the handshake lemma

From the similarity matrix $S$ (with $S_{ii}=0$), keep edge $(i,j)$ iff
$S_{ij} \ge \tau$, weighted by $S_{ij}$.

**Choosing $\tau$ from a target degree.** The **handshake lemma**
$$\sum_i \deg(i) = 2m$$
converts a target mean degree $d$ into an edge count $m \approx Nd/2$. Then
$\tau$ is simply the $\big(\lceil Nd/2\rceil\big)$-th largest value among the
$\binom{N}{2}$ upper-triangular similarities — an **order statistic**. This makes
$\tau$ reproducible rather than hand-tuned.

**Density.** $\displaystyle \text{density} = \frac{2m}{N(N-1)}$, the fraction of
possible edges realised.

**Realised values:** $N=83$, target degree $8 \Rightarrow m = 332$ edges,
$\tau = 0.771$, mean degree $8.0$, density $0.0976$. Isolates ($4$) and
non-trivial component count ($13$) follow from the strictness of $\tau$: nodes
with no peer above $0.771$ stay unconnected — deliberate, mirroring HDBSCAN's
treatment of outliers.

---

## 7. Modularity — an observed-minus-expected functional

For a weighted graph with adjacency $A$, node strengths $k_i = \sum_j A_{ij}$,
total weight $m = \tfrac12\sum_{ij} A_{ij}$, and a partition $\{c_i\}$:
$$Q = \frac{1}{2m}\sum_{ij}\left(A_{ij} - \frac{k_i k_j}{2m}\right)\delta(c_i,c_j).$$
The term $\dfrac{k_i k_j}{2m}$ is the expected edge weight between $i$ and $j$
under the **configuration model** — a degree-preserving random graph — so $Q$
measures how much *more* within-community connection exists than chance predicts.
Equivalently,
$$Q = \sum_c \big(e_{cc} - a_c^2\big),$$
within-community weight fraction minus its expectation. Range $[-\tfrac12, 1)$;
$Q > 0.3$ is the usual "structure beyond chance" heuristic.

**Result:** the HDBSCAN partition scores $Q = 0.5224$ — the clusters are
communities in the graph-topological sense too, verified against a null model
that knows nothing about the embedding.

---

## 8. Greedy community detection — and the deep point

`greedy_modularity_communities` is the **Clauset–Newman–Moore** algorithm:

1. Every node starts in its own community.
2. For each pair of communities, compute the modularity gain $\Delta Q_{ij}$ of merging.
3. Perform the merge with the largest positive $\Delta Q_{ij}$.
4. Repeat until no merge increases $Q$; return the highest-$Q$ partition seen.

Locally optimal choice, no backtracking — the textbook greedy schema. **Result:**
13 communities, $Q_{\text{greedy}} = 0.5265$ (slightly above HDBSCAN's, as
expected since greedy directly maximises $Q$).

**The greedy paradigm appears twice in this pipeline, with opposite guarantees.**

- Inside HDBSCAN (§2), the MST is built greedily (Kruskal) and is **globally optimal**.
- For modularity, greedy CNM is **only a heuristic**: exact modularity
  maximisation is NP-hard (Brandes et al., 2008), and greedy can settle in a
  local maximum.

The distinction is structural, not luck. By the **Rado–Edmonds theorem**, a
greedy algorithm returns the optimum for *every* weighting precisely when the
underlying independent sets form a **matroid**. Spanning forests of a graph form
the **graphic matroid**, whose exchange property is exactly what makes Kruskal
exact. The space of graph partitions carries no such matroid structure, so greedy
loses its guarantee and becomes a fast, usually-good heuristic.

**Write-up framing:** MST-greedy is exact by matroid theory; modularity-greedy is
a heuristic for an NP-hard problem — and the fact that it *still* recovers the
HDBSCAN clusters (ARI $= 0.8985$) is therefore *stronger* evidence, not weaker:
an algorithm with no optimality guarantee, working on a different representation
(graph topology, not embedding geometry), independently landed on the same
structure.

---

## 9. Adjusted Rand Index — combinatorics of agreement

Compare the greedy partition $U$ to HDBSCAN's $V$ via the contingency table
$n_{ij} = |U_i \cap V_j|$, with row/column sums $a_i, b_j$:
$$\text{ARI} =
\frac{\displaystyle\sum_{ij}\binom{n_{ij}}{2}
- \dfrac{\left[\sum_i\binom{a_i}{2}\right]\left[\sum_j\binom{b_j}{2}\right]}{\binom{n}{2}}}
{\dfrac{1}{2}\left[\sum_i\binom{a_i}{2}+\sum_j\binom{b_j}{2}\right]
- \dfrac{\left[\sum_i\binom{a_i}{2}\right]\left[\sum_j\binom{b_j}{2}\right]}{\binom{n}{2}}}.$$
Each $\binom{n_{ij}}{2}$ counts pairs the two partitions agree to co-cluster; the
subtracted term is the expectation under a generalised hypergeometric null
(random partitions with fixed block sizes); the denominator normalises so a
perfect match gives $1$. Hence "corrected for chance": $0$ = agreement no better
than random, and negative values are possible. **Result: 0.8985** — high
agreement between two representation-independent algorithms.

---

## 10. Fruchterman–Reingold spring layout (plot fallback only)

If UMAP coordinates are unavailable, the preview uses a force-directed layout
minimising a physical energy with ideal edge length $\ell$:
$$f_{\text{attract}}(d) = \frac{d^2}{\ell} \ \text{ along edges},
\qquad
f_{\text{repulse}}(d) = \frac{\ell^2}{d} \ \text{ between all node pairs}.$$
Gradient descent on this energy; not greedy, and presentation-only — it never
affects any metric.

---

## 11. Metric quick-reference

| Symbol | Definition | Range | "Good" | This build |
|---|---|---|---|---|
| $\cos\theta$ | $\langle x,y\rangle / (\|x\|\|y\|)$ | $[-1,1]$ | $\to 1$ similar | edge $\tau=0.771$ |
| $s(i)$ | silhouette | $[-1,1]$ | $>0$ | mean $0.4745$ |
| $T(k)$ | trustworthiness | $[0,1]$ | $\to 1$ | $0.9840$ |
| $Q$ | modularity | $[-\tfrac12,1)$ | $>0.3$ | $0.5224$ (HDBSCAN), $0.5265$ (greedy) |
| ARI | adjusted Rand | $\le 1$ | $\to 1$ | $0.8985$ |
| $S(C)$ | HDBSCAN stability | $\ge 0$ | large | (selection criterion) |

---

## 12. Reference summary

- **Cosine geometry** — work on $S^{383}$; consistent metric end-to-end.
- **HDBSCAN** — core distance $\to$ mutual reachability $\to$ MST (Kruskal, exact)
  $\to$ condensed tree $\to$ persistence-stability selection.
- **Silhouette / Trustworthiness** — separation and projection-honesty, computed
  in different spaces, hence independent.
- **UMAP** — fuzzy simplicial sets; cross-entropy between high-/low-dimensional
  membership graphs.
- **TF-IDF** — lexical distinctiveness via $\ln$-scaled inverse document frequency.
- **Graph** — order-statistic threshold from the handshake lemma; isolates
  preserved.
- **Modularity** — observed-minus-configuration-model within-community weight.
- **Greedy (CNM)** vs **MST-greedy** — heuristic (NP-hard) vs exact (matroid /
  Rado–Edmonds); the crux mathematical contrast of the project.
- **ARI** — chance-corrected partition agreement; the cross-algorithm check.

**Four independent lenses, one embedding, convergent evidence.**
