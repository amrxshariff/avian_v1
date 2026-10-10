"""
src/eval_classifier.py — score src/onet.py against hand-labelled ground truth.

Reads data/eval/title_labels.csv (50 titles labelled BLIND, before any classifier
output existed) and reports where the classifier agrees, where it is wrong, and —
most importantly — where it invents an occupation for something that has none.

The five outcomes, and why they are not equally bad
--------------------------------------------------
  correct        gold=X, pred=X        the product works
  correct_abstain gold=99, pred=none   "Member" has no occupation; we said so
  wrong          gold=X, pred=Y        a real error: wrong skills on the card
  missed         gold=X, pred=none     conservative. Costs coverage, not truth.
  FABRICATED     gold=99, pred=Y       the worst outcome. We assigned an
                                       occupation to something that isn't one
                                       ("President" -> Chief Executives), and it
                                       looks authoritative because it cites O*NET.

`missed` and `fabricated` both come from the abstain boundary but are not
symmetric: a blank card is honest, a fabricated card is a lie the user cannot
detect. Tune thresholds to drive fabrication toward zero even at the cost of
some misses.

Run from the repo root (after labelling):
    python -m src.eval_classifier
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.onet import classify_titles

LABELS_CSV = Path("data/eval/title_labels.csv")
REPORT_CSV = Path("data/eval/eval_report.csv")

UNCLASSIFIABLE = "99"


def load_labels() -> pd.DataFrame:
    """Load the hand-labelled eval set, keeping only rows actually labelled."""
    if not LABELS_CSV.exists():
        raise FileNotFoundError(
            f"{LABELS_CSV} not found. Generate the sample and hand-label the "
            "soc_major_group column first."
        )
    df = pd.read_csv(LABELS_CSV, dtype=str)
    for col in ("title", "soc_major_group"):
        if col not in df.columns:
            raise KeyError(f"Expected column '{col}' in {LABELS_CSV}; "
                           f"found {list(df.columns)}.")

    df["soc_major_group"] = df["soc_major_group"].fillna("").str.strip()
    unlabelled = int((df["soc_major_group"] == "").sum())
    if unlabelled:
        print(f"! {unlabelled} of {len(df)} rows are unlabelled — skipping them.\n")
    return df[df["soc_major_group"] != ""].reset_index(drop=True)


def outcome(gold: str, pred: str | None) -> str:
    """Classify one prediction into the five outcomes."""
    if gold == UNCLASSIFIABLE:
        return "correct_abstain" if pred is None else "FABRICATED"
    if pred is None:
        return "missed"
    return "correct" if pred == gold else "wrong"


def evaluate(labels: pd.DataFrame, encoder=None) -> pd.DataFrame:
    """Run the classifier over the labelled titles and join gold vs predicted."""
    results = classify_titles(labels["title"].tolist(), encoder=encoder)

    rows = []
    for _, r in labels.iterrows():
        c = results[r["title"]]
        rows.append({
            "title": r["title"],
            "gold": r["soc_major_group"],
            "pred": c.soc_major,
            "occupation": c.occupation,
            "tier": c.tier,
            "score": c.score,
            "n_candidates": c.n_candidates,
            "major_agreement": c.major_agreement,
            "outcome": outcome(r["soc_major_group"], c.soc_major),
        })
    return pd.DataFrame(rows)


def report(df: pd.DataFrame) -> None:
    """Print the headline numbers and every error, so each one is inspectable."""
    n = len(df)
    counts = df["outcome"].value_counts()

    def pct(k: str) -> str:
        c = int(counts.get(k, 0))
        return f"{c:>3} ({100*c/n:>5.1f}%)"

    print(f"=== Eval: {n} hand-labelled titles ===\n")
    print(f"  correct          {pct('correct')}")
    print(f"  correct_abstain  {pct('correct_abstain')}")
    print(f"  wrong            {pct('wrong')}")
    print(f"  missed           {pct('missed')}")
    print(f"  FABRICATED       {pct('FABRICATED')}   <- drive this to zero")

    good = int(counts.get("correct", 0)) + int(counts.get("correct_abstain", 0))
    print(f"\n  overall accuracy: {100*good/n:.1f}%")

    assigned = df[df["pred"].notna()]
    if len(assigned):
        prec = (assigned["outcome"] == "correct").sum() / len(assigned)
        print(f"  precision when it commits: {100*prec:.1f}% "
              f"({len(assigned)}/{n} titles assigned)")

    print("\n--- accuracy by tier ---")
    for tier, grp in df.groupby("tier"):
        ok = grp["outcome"].isin(["correct", "correct_abstain"]).sum()
        print(f"  {tier:10} {ok:>3}/{len(grp):<3} ({100*ok/len(grp):>5.1f}%)")

    errs = df[df["outcome"].isin(["wrong", "FABRICATED"])]
    if len(errs):
        print(f"\n--- every error ({len(errs)}) ---")
        for _, r in errs.iterrows():
            print(f"  [{r['outcome']:10}] {r['title'][:34]:36} "
                  f"gold={r['gold']} pred={r['pred']} "
                  f"({r['tier']}, {r['score']}) -> {r['occupation']}")

    missed = df[df["outcome"] == "missed"]
    if len(missed):
        print(f"\n--- missed, i.e. abstained but shouldn't have ({len(missed)}) ---")
        for _, r in missed.iterrows():
            print(f"  {r['title'][:34]:36} gold={r['gold']}")


def main() -> None:
    labels = load_labels()
    df = evaluate(labels)
    report(df)

    REPORT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(REPORT_CSV, index=False)
    print(f"\nwrote {REPORT_CSV}")


if __name__ == "__main__":
    main()