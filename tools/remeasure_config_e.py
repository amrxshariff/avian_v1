"""tools/remeasure_config_e.py - D-47: did D-42 touch the config E figures?

Config E (Claude, title only) was measured on the blind 100 by src/bakeoff.py,
which classifies through the same cache that held 118 padded records before
D-42 was fixed. A padded record scores as an abstention, so it could have
lowered coverage, or scored as a correct abstention on a no-occupation title.

Method, with no re-sampling where it can be avoided:
  recorded  config E's per-title predictions as the bake-off wrote them
            (data/eval/bakeoff_report.csv)
  now       the same titles through classify_claude and the same gate, reading
            the cache as it is after the D-42 purge

The cache is only ever appended to, except by that purge. So a title whose
prediction differs between the two had its cache entry replaced: it was padded
when the bake-off ran. Titles that are not cached at all would need new API
calls, which re-sample the model; the tool refuses to make them unless
--allow-api is passed, and reports them separately if it does.

Offline by default:
    python -m tools.remeasure_config_e
    python -m tools.remeasure_config_e --show        # list changed titles
    python -m tools.remeasure_config_e --allow-api   # classify uncached titles
"""
from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

import pandas as pd

from src.bakeoff import LABELS_CSV, REPORT_CSV, score
from src.claude_classifier import CACHE_PATH, _cache_key, _load_cache, classify_claude

CONFIG_E = "E + Claude (title)"


def _pred(value) -> str | None:
    return None if pd.isna(value) or value == "" else str(value)


def recorded_predictions(report: Path) -> dict[str, str | None]:
    if not report.is_file():
        raise SystemExit(f"bake-off report not found: {report}")
    df = pd.read_csv(report, dtype=str)
    rows = df[df["config"] == CONFIG_E]
    if rows.empty:
        raise SystemExit(f"no '{CONFIG_E}' rows in {report}")
    return {r.title: _pred(r.pred) for r in rows.itertuples()}


def current_predictions(titles: list[str], cache: Path) -> dict[str, str | None]:
    """Config E exactly as bakeoff._claude_only computes it, reading `cache`."""
    out = classify_claude([(t, "") for t in titles], cache_path=cache)
    return {t: (c.soc_major if c.tier == "claude" else None) for t, c in zip(titles, out)}


def _outcome(gold: str, pred: str | None) -> str:
    if gold == "99":
        return "correct_abstain" if pred is None else "FABRICATED"
    if pred is None:
        return "missed"
    return "correct" if pred == gold else "wrong"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--labels", type=Path, default=LABELS_CSV)
    ap.add_argument("--report", type=Path, default=REPORT_CSV)
    ap.add_argument("--cache", type=Path, default=CACHE_PATH)
    ap.add_argument("--allow-api", action="store_true",
                    help="classify titles missing from the cache (re-samples the model)")
    ap.add_argument("--show", action="store_true", help="list the titles that changed")
    args = ap.parse_args(argv)

    if not args.labels.is_file():
        raise SystemExit(f"labels not found: {args.labels}")
    gold = pd.read_csv(args.labels, dtype=str)
    titles = gold["title"].tolist()
    recorded = recorded_predictions(args.report)

    cache = _load_cache(args.cache)
    uncached = [t for t in titles if _cache_key(t, "") not in cache]
    unparsed = [t for t in titles if cache.get(_cache_key(t, ""), {}).get("why") == "unparsed"]
    mtime = dt.datetime.fromtimestamp(args.report.stat().st_mtime).strftime("%d %b %Y %H:%M")
    print(f"{len(titles)} blind titles | report written {mtime} | "
          f"{len(uncached)} not in cache | {len(unparsed)} cached as unparsed")
    if unparsed:
        print("  cache still holds padded records for these titles; D-42's purge is incomplete")
    if uncached and not args.allow_api:
        print(f"\n{len(uncached)} title(s) would need new API calls, which re-sample the "
              "model.\nRerun with --allow-api to include them. Nothing was measured.")
        return 2
    if uncached:
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass

    now = current_predictions(titles, args.cache)

    results = [score(gold, recorded, "E as recorded"), score(gold, now, "E on clean cache")]
    cols = ["config", "precision", "coverage", "correct", "wrong", "fabricated",
            "missed", "correct_abstain"]
    print()
    print(pd.DataFrame([{k: r[k] for k in cols} for r in results]).to_string(index=False))

    gold_by = dict(zip(gold["title"], gold["soc_major_group"]))
    changed = [(t, recorded.get(t), now[t]) for t in titles if recorded.get(t) != now[t]]
    resampled = set(uncached)
    print(f"\n{len(changed)} title(s) changed prediction"
          f" ({sum(t in resampled for t, _, _ in changed)} of them re-sampled via the API)")
    moves: dict[str, int] = {}
    for t, old, new in changed:
        key = f"{_outcome(gold_by[t], old)} -> {_outcome(gold_by[t], new)}"
        moves[key] = moves.get(key, 0) + 1
    for key, n in sorted(moves.items(), key=lambda kv: -kv[1]):
        print(f"  {n:>3}  {key}")
    if args.show:
        print()
        for t, old, new in changed:
            tag = "  [re-sampled]" if t in resampled else ""
            print(f"  {t!r}: {old} -> {new} (gold {gold_by[t]}){tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
