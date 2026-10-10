"""
src/bakeoff.py — Phase 1.5: head-to-head on the same 50 hand-labelled titles.

Four configurations, one eval set, so the comparison is apples to apples:

  A  deterministic          exact + fuzzy only        (baseline: 81.8% / 44%)
  B  deterministic + embed  the tier we're replacing  (measured: 74.1% / 54%)
  C  deterministic + Claude (title only)              fills the abstains
  D  deterministic + Claude (title + company)         + the unexplored lever

C and D keep the deterministic tiers in front: they measure 85.7% (exact) and
75.0% (fuzzy), they are free, and they cite a lexicon row. Claude is asked only
for the ~56% they abstain on. D adds company, which is the difference between
"President" (undecidable) and "President @ Barclays" (11).

The gate, set before any of this was run: precision >= 85% when it commits,
coverage >= 50%. Precision is weighted over coverage because a blank profile
card is honest and a confidently wrong one cites an authoritative taxonomy while
being undetectable to the user.

Read the number, then read the caveat
-------------------------------------
These 50 labels were revised AFTER we had seen predictions. Principled or not,
that is contamination: this is a DEVELOPMENT set. Use it to choose between A-D
and to find bugs. Do not quote it as the product's accuracy and do not tune
thresholds against it. The gate is adjudicated on the blind 100.

Run from the repo root (C and D need ANTHROPIC_API_KEY):
    python -m src.bakeoff
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.claude_classifier import classify_claude
from src.ingestion import load_profiles
from src.onet import classify_titles

LABELS_CSV = Path("data/eval/title_labels_blind.csv")
REPORT_CSV = Path("data/eval/bakeoff_report.csv")
UNCLASSIFIABLE = "99"


def score(gold: pd.DataFrame, pred: dict[str, str | None], name: str) -> dict:
    """One config's outcomes. pred maps title -> soc_major (None = abstained)."""
    rows = []
    for _, r in gold.iterrows():
        p = pred.get(r.title)
        g = r.soc_major_group
        if g == UNCLASSIFIABLE and p is None:
            o = "correct_abstain"
        elif g == UNCLASSIFIABLE:
            o = "FABRICATED"
        elif p is None:
            o = "missed"
        elif p == g:
            o = "correct"
        else:
            o = "wrong"
        rows.append({"config": name, "title": r.title, "gold": g, "pred": p,
                     "outcome": o})
    df = pd.DataFrame(rows)
    committed = df[df.pred.notna()]
    n_commit = len(committed)
    return {
        "config": name,
        "precision": round(100 * (committed.outcome == "correct").mean(), 1) if n_commit else 0.0,
        "coverage": round(100 * n_commit / len(df), 1),
        "correct": int((df.outcome == "correct").sum()),
        "wrong": int((df.outcome == "wrong").sum()),
        "fabricated": int((df.outcome == "FABRICATED").sum()),
        "missed": int((df.outcome == "missed").sum()),
        "correct_abstain": int((df.outcome == "correct_abstain").sum()),
        "_detail": df,
    }


def _company_map() -> dict[str, str]:
    """title -> company, first occurrence. Titles recur across companies; the
    first is enough to test whether company helps at all."""
    m: dict[str, str] = {}
    for p in load_profiles():
        t = p.role.strip()
        if t and t not in m:
            m[t] = p.company.strip()
    return m


def _fill(base: dict[str, str | None], titles: list[str],
          use_company: bool, companies: dict[str, str]) -> dict[str, str | None]:
    """Run Claude on whatever `base` abstained on; leave the rest untouched."""
    todo = [t for t in titles if base.get(t) is None]
    if not todo:
        return dict(base)
    items = [(t, companies.get(t, "") if use_company else "") for t in todo]
    out = dict(base)
    for t, c in zip(todo, classify_claude(items)):
        out[t] = c.soc_major if c.tier == "claude" else None
    return out

def _claude_only(titles, use_company, companies):
    items = [(t, companies.get(t, "") if use_company else "") for t in titles]
    return {t: (c.soc_major if c.tier == "claude" else None)
            for t, c in zip(titles, classify_claude(items))}


def main() -> None:
    gold = pd.read_csv(LABELS_CSV, dtype=str)
    titles = gold.title.tolist()
    companies = _company_map()

    n_with_co = sum(1 for t in titles if companies.get(t))
    print(f"{len(titles)} eval titles | company available for {n_with_co}\n")

    # A: deterministic only
    det = classify_titles(titles, use_embedding=False)
    a = {t: (c.soc_major if c.tier != "abstain" else None) for t, c in det.items()}

    # B: deterministic + embedding
    emb = classify_titles(titles, use_embedding=True)
    b = {t: (c.soc_major if c.tier != "abstain" else None) for t, c in emb.items()}

    # C / D: deterministic + Claude
    c = _fill(a, titles, use_company=False, companies=companies)
    d = _fill(a, titles, use_company=True, companies=companies)

    e = _claude_only(titles, use_company=False, companies=companies)
    f = _claude_only(titles, use_company=True, companies=companies)

    

    results = [
        score(gold, a, "A deterministic"),
        score(gold, b, "B + embedding"),
        score(gold, c, "C + Claude (title)"),
        score(gold, d, "D + Claude (title+company)"),
        score(gold, e, "E + Claude (title)"),
        score(gold, f, "F + Claude (title+company)")
    ]

    summary = pd.DataFrame([{k: v for k, v in r.items() if k != "_detail"}
                            for r in results])
    print(summary.to_string(index=False))
    print("\ngate: precision >= 85.0 and coverage >= 50.0")
    for r in results:
        ok = r["precision"] >= 85.0 and r["coverage"] >= 50.0
        print(f"  {r['config']:<28} {'PASS' if ok else 'fail'}"
              f"   ({r['precision']}% / {r['coverage']}%)")

    detail = pd.concat([r["_detail"] for r in results], ignore_index=True)
    detail.to_csv(REPORT_CSV, index=False)
    print(f"\nWrote {REPORT_CSV}")

    print("\n--- errors introduced by the best Claude config (D) ---")
    dd = results[3]["_detail"]
    for _, r in dd[dd.outcome.isin(["wrong", "FABRICATED"])].iterrows():
        print(f"  [{r.outcome:<10}] {r.title[:42]:<44} gold={r.gold} pred={r.pred}")

    print("\nDEVELOPMENT set — labels were revised after seeing predictions.")
    print("Choose a config with it; do not quote it. Gate on the blind 100.")


if __name__ == "__main__":
    main()
