"""tools/measure_synthetic.py - P2.9a: measure the demo export against its targets.

Measures what is committed, not what the generator would produce: the export is
regenerated in memory and must match data/synthetic/Connections.csv exactly
before anything is classified.

Classification goes through classify_pipeline.classify_people unchanged, so the
needs-review rule exists in one place. Synthetic titles land in the shared title
cache; it holds titles and labels only, no people.

    python -m tools.measure_synthetic --dry-run   # structure only, no API calls
    python -m tools.measure_synthetic             # classifies; ~1 call per 20 new titles
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter

import pandas as pd

from src import synthetic
from src.schema import Person

BAND = (0.24, 0.34)   # pre-registered v2: 29.0% +/- 5pp (post-D-42 corrected rate)
REAL_SHAPE = {"groups": 19, "ge5": 10, "lt5": 9, "largest_group_pct": 20.6}   # post-D-42 rebuild


def check_committed(rows: list[synthetic.Row]) -> None:
    expected = synthetic.render(rows)
    actual = synthetic.OUTPUT_PATH.read_text(encoding="utf-8").replace("\r\n", "\n")
    if actual != expected:
        sys.exit("Committed export differs from the generator output. "
                 "Re-run python -m src.synthetic, then measure.")


def to_people(rows: list[synthetic.Row]) -> list[Person]:
    return [Person(id=f"li{i:03d}", name=f"{r.first} {r.last}",
                   company=r.company, role=r.position) for i, r in enumerate(rows)]


def group_shape(counts: pd.Series, n_rows: int) -> dict:
    counts = counts[counts > 0]
    return {
        "groups": int(len(counts)),
        "ge5": int((counts >= 5).sum()),
        "lt5": int((counts < 5).sum()),
        "largest_group_pct": round(100 * float(counts.max()) / n_rows, 1) if len(counts) else 0.0,
    }


def structure(rows: list[synthetic.Row]) -> dict:
    nonblank = [r.position for r in rows if r.position]
    proxy = pd.Series([r.source_major for r in rows if r.source_major]).value_counts()
    return {
        "rows": len(rows),
        "distinct_titles": len(set(nonblank)),
        "blank_position": len(rows) - len(nonblank),
        "blank_company": sum(1 for r in rows if not r.company),
        "strata": dict(Counter(r.stratum for r in rows)),
        # O*NET source groups before classification: a proxy for shape, not a result
        "proxy_groups": group_shape(proxy, len(rows)),
        "real_groups": REAL_SHAPE,
    }


def unparsed_titles(rows: list[synthetic.Row], cache: dict, key_fn) -> list[str]:
    """Titles whose cached result is the parser's padding, not a model answer.

    _parse_response pads a truncated or malformed batch with abstains, and the
    cache keeps them. Each one reads as needs-review, so any in the measurement
    means the rate is inflated by failures rather than measured.
    """
    titles = {r.position.strip() for r in rows if r.position.strip()}
    return sorted(t for t in titles if cache.get(key_fn(t, ""), {}).get("why") == "unparsed")


def outcome(rows: list[synthetic.Row], classified: pd.DataFrame) -> dict:
    """Pure: classification frame -> the numbers the DoD is judged on."""
    unc = classified["is_uncertain"].astype(bool)
    shape = group_shape(classified.loc[~unc, "soc_major"].value_counts(), len(rows))
    by_stratum = (
        pd.DataFrame({"stratum": [r.stratum for r in rows], "unc": unc.to_numpy()})
        .groupby("stratum")["unc"].agg(["size", "mean"])
    )
    rate = float(unc.mean())
    return {
        "needs_review": int(unc.sum()),
        "rate": rate,
        "in_band": BAND[0] <= rate <= BAND[1],
        **shape,
        "by_stratum": by_stratum,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    rows = synthetic.generate(synthetic.load_onet_titles(), synthetic.Spec())
    check_committed(rows)
    for k, v in structure(rows).items():
        print(f"{k:>16}: {v}")
    if args.dry_run:
        return

    from src.classify_pipeline import classify_people   # API client only when needed
    from src.claude_classifier import CACHE_PATH, _cache_key   # the one key implementation
    o = outcome(rows, classify_people(to_people(rows)))
    cache = json.loads(CACHE_PATH.read_text(encoding="utf-8")) if CACHE_PATH.exists() else {}
    bad = unparsed_titles(rows, cache, _cache_key)
    if bad:
        print(f"\nINVALID: {len(bad)} titles carry padded 'unparsed' abstains, so the rate "
              f"below counts failed batches as needs-review. Do not re-weight on it.")
        print("  e.g.", bad[:5])
    print(f"\n    needs_review: {o['needs_review']} ({100 * o['rate']:.1f}%)  "
          f"band {100 * BAND[0]:.0f}-{100 * BAND[1]:.0f}%  "
          f"{'IN BAND' if o['in_band'] else 'OUT OF BAND'}")
    print(f"          groups: {o['groups']}  ge5 {o['ge5']}  lt5 {o['lt5']}  "
          f"largest {o['largest_group_pct']}%   (real: {REAL_SHAPE})")
    print("\nneeds-review rate by stratum:")
    print(o["by_stratum"].rename(columns={"size": "n", "mean": "rate"}).round(2).to_string())
    sys.exit(0 if o["in_band"] and o["ge5"] and o["lt5"] and not bad else 1)


if __name__ == "__main__":
    main()
