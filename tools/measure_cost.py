"""
tools/measure_cost.py — what does classifying one title actually cost?

Every figure in docs/p2_9b_upload_key_tier.md rests on an estimate: roughly
$0.001–0.002 per title, derived from prompt size and a guess at how much
adaptive thinking spends. The difference between the estimate and the
conservative assumption the limiter would use is the difference between ~40
free networks a day and ~15, so it is worth one run to replace it with a
number.

Run from the repo root, with a key, on titles NOT already cached:
    python -m tools.measure_cost --n 100

Costs about $0.20. Always classifies with the cache off, so it measures a cold
classification; the cache on disk is untouched either way.
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

REAL_EXPORT = Path("data/raw/Connections.csv")
SYNTHETIC_EXPORT = Path("data/synthetic/Connections.csv")


def titles_from(path: Path, n: int, seed: int) -> list[str]:
    from src.linkedin import load_linkedin_profiles

    people = load_linkedin_profiles(path)
    distinct = sorted({p.role.strip() for p in people if p.role.strip()})
    random.Random(seed).shuffle(distinct)
    return distinct[:n]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--export", default=None,
                    help="defaults to the real export, else the synthetic one")
    args = ap.parse_args()

    from src.claude_classifier import BATCH_SIZE, MODEL, classify_claude_outcome

    source = Path(args.export) if args.export else (
        REAL_EXPORT if REAL_EXPORT.exists() else SYNTHETIC_EXPORT
    )
    if not source.exists():
        print(f"No export at {source}.")
        return 1

    titles = titles_from(source, args.n, args.seed)
    print(f"Measuring {len(titles)} distinct titles from {source.name}, "
          f"model {MODEL}, batch size {BATCH_SIZE}, cache OFF...")

    outcome = classify_claude_outcome(
        [(t, "") for t in titles], use_cache=False
    )
    usage = outcome.usage
    answered = sum(1 for a in outcome.answers if a is not None)

    per_title = usage.cost() / len(titles)
    print(f"\n  calls        : {usage.calls}")
    print(f"  input tokens : {usage.input_tokens:,}")
    print(f"  output tokens: {usage.output_tokens:,}")
    print(f"  answered     : {answered}/{len(titles)}"
          f"{'' if outcome.complete else f'  ({sorted(outcome.reasons)})'}")
    print(f"\n  total cost   : ${usage.cost():.4f}")
    print(f"  per title    : ${per_title:.5f}")

    print("\nAt this rate:")
    for label, count in (("442-person network (371 titles)", 371),
                         ("1,000 titles", 1000)):
        print(f"  {label:34}: ${per_title * count:.2f}")
    print(f"  networks per $30 day{'':14}: {30 / (per_title * 371):.0f}")
    print("\nWrite the per-title figure into the record (section 6.3) and set "
          "the limiter's assumption from it, rounded up.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
