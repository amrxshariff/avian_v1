"""
src/onet.py — Phase 1.5: classify free-text job titles to O*NET-SOC occupations.

Replaces the synthetic-archetype enrichment. Instead of inventing skills from our
own generator (which could only ever invert our own assumptions), we map each
real job title onto an occupation in the O*NET-SOC taxonomy and read real
occupational data back out.

Data attribution
----------------
This module uses information from the O*NET 30.3 Database by the U.S. Department
of Labor, Employment and Training Administration (USDOL/ETA), used under the
CC BY 4.0 license. O*NET(R) is a trademark of USDOL/ETA. This project has
modified some of that information (normalisation, majority-vote aggregation,
fuzzy and embedding matching). USDOL/ETA has not approved, endorsed, or tested
these modifications.

Tiers, cheapest first
---------------------
  0. exact     — normalised title found verbatim in the 46.5k-entry lexicon
  1. fuzzy     — token Jaccard + sequence ratio against the lexicon
  2. embedding — cosine vs occupation title+description centroids (injectable)
  3. abstain   — nothing clears threshold; NO occupation is assigned

Abstaining is a first-class outcome, not a failure. "Member", "Volunteer" and
"Summer Intern" are not occupations; a blank profile card is correct and a
fabricated one is not.

Ambiguity
---------
15.3% of lexicon entries map to several detailed codes ("data analyst" -> 9), but
only 6.3% are ambiguous at MAJOR-GROUP level — 58.6% of the ambiguity collapses
one level up. So we resolve by majority vote over the 2-digit major group, then
pick the best-corroborated detailed code inside the winner. `n_candidates` and
`major_agreement` are recorded so downstream code can distrust a weak vote.

Run from the repo root:
    python -m src.onet
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import pandas as pd

ONET_DIR = Path("data/onet")
JOB_TITLES_CSV = ONET_DIR / "job_titles.csv"
OCCUPATION_CSV = ONET_DIR / "occupation_data.csv"

CODE_COL = "O*NET-SOC Code"

# The 23 SOC major groups. Verified against occupation_data.csv: every one of
# these appears, and no code carries a prefix outside this set.
MAJOR_GROUP_NAMES: dict[str, str] = {
    "11": "Management",
    "13": "Business and Financial Operations",
    "15": "Computer and Mathematical",
    "17": "Architecture and Engineering",
    "19": "Life, Physical, and Social Science",
    "21": "Community and Social Service",
    "23": "Legal",
    "25": "Educational Instruction and Library",
    "27": "Arts, Design, Entertainment, Sports, and Media",
    "29": "Healthcare Practitioners and Technical",
    "31": "Healthcare Support",
    "33": "Protective Service",
    "35": "Food Preparation and Serving Related",
    "37": "Building and Grounds Cleaning and Maintenance",
    "39": "Personal Care and Service",
    "41": "Sales and Related",
    "43": "Office and Administrative Support",
    "45": "Farming, Fishing, and Forestry",
    "47": "Construction and Extraction",
    "49": "Installation, Maintenance, and Repair",
    "51": "Production",
    "53": "Transportation and Material Moving",
    "55": "Military Specific",
}

# Tier thresholds. Tuned against the eval set, not by intuition.
FUZZY_THRESHOLD = 0.72
EMBED_THRESHOLD = 0.55

# Seniority / scope words carrying no occupational signal. Role-defining nouns
# (analyst, engineer, manager, director) are deliberately NOT here.
SENIORITY_TOKENS = frozenset({
    "senior", "junior", "lead", "principal", "chief", "staff", "trainee",
    "graduate", "global", "regional", "deputy", "interim", "acting",
    "of", "the", "and", "a", "an", "at", "for",
})

Encoder = Callable[[list[str]], np.ndarray]


@dataclass
class Classification:
    """One title's occupation assignment, with the evidence behind it."""

    query: str
    soc_code: str | None        # detailed O*NET-SOC code, None if abstained
    soc_major: str | None       # 2-digit major group
    occupation: str | None      # human-readable occupation title
    tier: str                   # exact | fuzzy | embedding | abstain
    score: float                # match strength (1.0 for exact)
    n_candidates: int           # distinct detailed codes the title matched
    major_agreement: float      # share of candidates in the winning major group

    def is_confident(self) -> bool:
        """Assigned, and the major-group vote was not a near-tie."""
        return self.soc_code is not None and self.major_agreement >= 0.5


def normalise(title: str) -> str:
    """Lowercase, drop the post-comma tail, strip punctuation and seniority words.

    'Senior Investment Analyst, EMEA' -> 'investment analyst'
    Returns '' for titles that are pure seniority noise.
    """
    head = str(title).lower().split(",")[0]
    tokens = [t for t in re.sub(r"[^a-z0-9]+", " ", head).split()
              if t and t not in SENIORITY_TOKENS]
    return " ".join(tokens)


@lru_cache(maxsize=1)
def load_taxonomy() -> tuple[dict[str, list[str]], dict[str, str]]:
    """Return (lexicon, occupation_titles).

    lexicon:           normalised title -> list of detailed O*NET-SOC codes
    occupation_titles: O*NET-SOC code   -> human-readable title

    Both the 57.5k alternate "lay" titles and the 1,016 canonical occupation
    titles are indexed, so 'Data Scientists' resolves as readily as 'data guy'.
    Cached: parsing 4.6MB on every call would dominate runtime.
    """
    for p in (JOB_TITLES_CSV, OCCUPATION_CSV):
        if not p.exists():
            raise FileNotFoundError(
                f"{p} not found. Download the O*NET 30.3 CSVs into {ONET_DIR}/ "
                "(see README data attribution section)."
            )

    jt = pd.read_csv(JOB_TITLES_CSV, dtype=str)
    occ = pd.read_csv(OCCUPATION_CSV, dtype=str)

    occupation_titles = dict(zip(occ[CODE_COL], occ["Title"]))

    lexicon: dict[str, set[str]] = {}
    for raw, code in zip(jt["Job Title"], jt[CODE_COL]):
        n = normalise(raw)
        if n:
            lexicon.setdefault(n, set()).add(code)
    for raw, code in zip(occ["Title"], occ[CODE_COL]):
        n = normalise(raw)
        if n:
            lexicon.setdefault(n, set()).add(code)

    return {k: sorted(v) for k, v in lexicon.items()}, occupation_titles


def _resolve(query: str, codes: list[str], tier: str, score: float) -> Classification:
    """Collapse candidate codes to one assignment by major-group majority vote.

    Detailed-level ambiguity is common; major-level ambiguity is rare. We vote at
    the major level, then inside the winning group take the lowest code — the
    broad/base occupation rather than an arbitrary specialisation (e.g. prefer
    15-2051.00 Data Scientists over 15-2051.01 Business Intelligence Analysts).
    """
    _, occupation_titles = load_taxonomy()

    majors = [c[:2] for c in codes]
    counts: dict[str, int] = {}
    for m in majors:
        counts[m] = counts.get(m, 0) + 1
    winner = max(sorted(counts), key=lambda m: counts[m])
    agreement = counts[winner] / len(codes)

    # Inside the winning group, pick the occupation whose OWN title best matches
    # the query. Sorting by code and taking the first is arbitrary — it sent
    # "data analyst" to Database Architects (15-1243) purely because that sorts
    # below Data Scientists (15-2051).
    n_query = normalise(query)
    q_tok = set(n_query.split())
    in_winner = sorted(c for c in codes if c.startswith(winner))
    chosen = max(
        in_winner,
        key=lambda c: (
            _fuzzy_score(n_query, q_tok,
                         normalise(occupation_titles.get(c, "")),
                         set(normalise(occupation_titles.get(c, "")).split())),
            -int(c.replace("-", "").replace(".", "")),  # stable: prefer base code
        ),
    )

    return Classification(
        query=query,
        soc_code=chosen,
        soc_major=winner,
        occupation=occupation_titles.get(chosen),
        tier=tier,
        score=round(score, 4),
        n_candidates=len(codes),
        major_agreement=round(agreement, 3),
    )


def _abstain(query: str, score: float = 0.0) -> Classification:
    return Classification(query, None, None, None, "abstain", round(score, 4), 0, 0.0)


# --- Tier 0: exact -----------------------------------------------------------

def classify_exact(title: str) -> Classification | None:
    """Verbatim lexicon hit on the normalised title, or None to fall through."""
    lexicon, _ = load_taxonomy()
    n = normalise(title)
    if not n or n not in lexicon:
        return None
    return _resolve(title, lexicon[n], "exact", 1.0)


# --- Tier 1: fuzzy -----------------------------------------------------------

def _fuzzy_score(a: str, a_tok: set[str], b: str, b_tok: set[str]) -> float:
    """Token Jaccard + character sequence ratio, with a head-final suffix bonus.

    English job titles are head-final: in "analytical data scientist" the head is
    "data scientist" and "analytical" merely modifies it. Bag-of-tokens metrics
    are blind to this — they scored "analytical scientist" (0.756, meaning a lab
    chemist) above "data scientist" (0.687), because both share two tokens and
    the character ratio happened to favour the wrong one.

    So an entry that is a contiguous *suffix* of the query is matching the
    query's head noun, and is scored accordingly. This also covers the very
    common "Senior X" / "Trainee X" / "Regional X" patterns that survive
    normalisation.
    """
    if not a_tok or not b_tok:
        return 0.0
    jaccard = len(a_tok & b_tok) / len(a_tok | b_tok)
    base = 0.6 * jaccard + 0.4 * SequenceMatcher(None, a, b).ratio()

    a_seq, b_seq = a.split(), b.split()
    # >=2 tokens required: a single-token suffix is just a token match, not a
    # phrase match, and boosting it is actively harmful — "summer intern" ends
    # with "intern", which O*NET reads as a MEDICAL intern, so a 1-token bonus
    # confidently filed an undergraduate under Physicians.
    if 2 <= len(b_seq) <= len(a_seq) and a_seq[-len(b_seq):] == b_seq:
        # Longer suffix = more of the query's head is matched.
        return max(base, 0.85 + 0.15 * len(b_seq) / len(a_seq))
    return base


def classify_fuzzy(title: str, threshold: float = FUZZY_THRESHOLD) -> Classification | None:
    """Best fuzzy match over the lexicon, gated on `threshold`.

    Only lexicon entries sharing at least one token are scored — 46.5k
    SequenceMatcher calls per title would be unusably slow, and an entry with no
    token overlap can never clear the bar anyway.
    """
    lexicon, _ = load_taxonomy()
    n = normalise(title)
    if not n:
        return None
    tok = set(n.split())

    by_token: dict[str, set[str]] = _token_index()
    candidates: set[str] = set()
    for t in tok:
        candidates |= by_token.get(t, set())
    if not candidates:
        return None

    best, best_score = None, 0.0
    for entry in candidates:
        s = _fuzzy_score(n, tok, entry, set(entry.split()))
        if s > best_score:
            best, best_score = entry, s

    if best is None or best_score < threshold:
        return None
    return _resolve(title, lexicon[best], "fuzzy", best_score)


@lru_cache(maxsize=1)
def _token_index() -> dict[str, set[str]]:
    """token -> lexicon entries containing it. Prunes the fuzzy search space."""
    lexicon, _ = load_taxonomy()
    index: dict[str, set[str]] = {}
    for entry in lexicon:
        for t in entry.split():
            index.setdefault(t, set()).add(entry)
    return index


# --- Tier 2: embedding -------------------------------------------------------

def _l2(m: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(m, axis=1, keepdims=True)
    n[n == 0] = 1.0
    return m / n


def _default_encoder() -> Encoder:
    """Lazily build the real sentence-transformer.

    Imported inside the function so that importing this module, or running the
    deterministic tiers alone, never pulls in the heavy dependency. Uses the
    SAME model as the rest of the pipeline (config.EMBEDDING_MODEL) so the
    occupation corpus and profile embeddings share a vector space.
    """
    from sentence_transformers import SentenceTransformer

    from src import config

    model = SentenceTransformer(config.EMBEDDING_MODEL)

    def encode(texts: list[str]) -> np.ndarray:
        return model.encode(texts, convert_to_numpy=True, show_progress_bar=False)

    return encode


def classify_embedding(
    titles: list[str], encoder: Encoder, threshold: float = EMBED_THRESHOLD
) -> list[Classification]:
    """Nearest occupation by cosine over 'Title. Description' embeddings.

    Batched: the 1,016 occupation vectors are built once for the whole call.
    """
    _, occupation_titles = load_taxonomy()
    occ = pd.read_csv(OCCUPATION_CSV, dtype=str)
    corpus = (occ["Title"] + ". " + occ["Description"].fillna("")).tolist()
    codes = occ[CODE_COL].tolist()

    occ_vecs = _l2(np.asarray(encoder(corpus), dtype=float))
    q_vecs = _l2(np.asarray(encoder(titles), dtype=float))
    sims = q_vecs @ occ_vecs.T

    out: list[Classification] = []
    for i, title in enumerate(titles):
        j = int(sims[i].argmax())
        s = float(sims[i, j])
        if s < threshold:
            out.append(_abstain(title, s))
        else:
            out.append(_resolve(title, [codes[j]], "embedding", s))
    return out


# --- Public API --------------------------------------------------------------

def classify_titles(
    titles: list[str],
    encoder: Optional[Encoder] = None,
    use_embedding: bool = True,
) -> dict[str, Classification]:
    """Classify distinct titles through all tiers. Returns {title: Classification}.

    Deduplicates first — 430 people over ~371 distinct titles means the work is
    per-title, not per-person. Tier 2 is only reached (and the model only
    loaded) if tiers 0 and 1 leave something unresolved.

    encoder=None loads the real sentence-transformer on demand. It does NOT mean
    "skip the embedding tier": a None default that silently abstained on every
    hard title would report the deterministic tiers as if they were the whole
    classifier. Pass use_embedding=False to genuinely run tiers 0-1 only (tests,
    or measuring deterministic coverage on purpose).
    """
    results: dict[str, Classification] = {}
    remaining: list[str] = []

    for t in dict.fromkeys(titles):
        hit = classify_exact(t) or classify_fuzzy(t)
        if hit:
            results[t] = hit
        else:
            remaining.append(t)

    if remaining:
        if not use_embedding:
            results.update({t: _abstain(t) for t in remaining})
        else:
            if encoder is None:
                encoder = _default_encoder()
            for c in classify_embedding(remaining, encoder):
                results[c.query] = c

    return results


def to_frame(results: dict[str, Classification]) -> pd.DataFrame:
    """Classifications -> tidy dataframe, for the eval harness and the sidecar."""
    return pd.DataFrame([asdict(c) for c in results.values()])


CLASSIFICATION_CSV = Path("data/cache/title_classification.csv")


def main() -> None:
    """Classify every distinct title in the configured data source, ALL tiers."""
    from src.ingestion import load_profiles

    lexicon, occupations = load_taxonomy()
    print(f"O*NET 30.3: {len(occupations)} occupations, "
          f"{len(lexicon)} normalised lexicon entries.\n")

    titles = sorted({p.role.strip() for p in load_profiles() if p.role.strip()})
    print(f"Classifying {len(titles)} distinct titles (embedding tier included; "
          f"first run loads the model)...\n")

    results = classify_titles(titles)
    df = to_frame(results)

    print("tier distribution:")
    for tier in ("exact", "fuzzy", "embedding", "abstain"):
        n = int((df.tier == tier).sum())
        print(f"  {tier:<10} {n:>4}  ({100 * n / len(df):>5.1f}%)")
    n_cls = int((df.tier != "abstain").sum())
    print(f"\n  classified {n_cls}/{len(df)} ({100 * n_cls / len(df):.1f}%)")

    # Low-agreement hits are coin flips reported as confident matches — surface
    # them so the number is read with the right amount of trust.
    weak = df[(df.tier != "abstain") & (df.major_agreement < 0.7)]
    print(f"  of which {len(weak)} resolved on major_agreement < 0.7 (unreliable)")

    CLASSIFICATION_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(CLASSIFICATION_CSV, index=False)
    print(f"\nWrote {CLASSIFICATION_CSV}")


if __name__ == "__main__":
    main()