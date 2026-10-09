"""
tools/check_summary_safety.py — P2.7 verification against the real network.

The unit tests prove the branches. This proves the OUTPUT: it generates real
summaries from the real node table and checks the things that can only fail once
a live model has written prose.

Six checks:
  1. Every summarised group has at least MIN_GROUP_SIZE members.
  2. No summary contains a surname from the node table (Amendment 2: nothing is
     attributed to a named individual).
  3. No summary contains a company name from the node table (company is a
     distractor and was never sent — its presence would mean leakage).
  4. Every prompt payload carries titles only — no name, no company column value.
  5. Each summary is 1-4 sentences (the DoD asks for 2-3; 1 is the permitted
     "too sparse to say more" case, 5+ means the constraint slipped).
  6. Regenerating after a simulated correction produces a cache MISS.

Reads the table through load_display_table() (src/dashboard/loader.py), the
same assembly path app.py uses, so the table it checks is the same shape the
dashboard sees.

Costs one API call per group with >= MIN_GROUP_SIZE members (typically ~15).

Run from the repo root:
    python -m tools.check_summary_safety
"""

from __future__ import annotations

import re
import sys

import pandas as pd

from src.dashboard.loader import load_display_table
from src.dashboard.state import STATE_CLASSIFIED
from src.dashboard.summaries import (
    MIN_GROUP_SIZE,
    STATUS_SUMMARY,
    build_prompt,
    group_members,
    member_titles,
    summarise_group,
    title_counts,
)

# Words that are surnames in the table but also ordinary occupational English.
# Matching on them would produce false alarms rather than catching leakage.
_SURNAME_STOPLIST = {
    "banks", "baker", "carpenter", "chandler", "clark", "cook", "cooper",
    "dean", "fisher", "gardener", "hunter", "judge", "knight", "mason",
    "miller", "page", "parker", "porter", "sawyer", "shepherd", "smith",
    "steward", "taylor", "turner", "walker", "ward", "weaver",
}


def _surnames(df: pd.DataFrame) -> set[str]:
    out: set[str] = set()
    for name in df.get("name", pd.Series(dtype=str)).fillna("").astype(str):
        parts = [p for p in re.split(r"[\s,]+", name.strip()) if len(p) > 3]
        if parts:
            token = parts[-1].lower()
            if token not in _SURNAME_STOPLIST:
                out.add(token)
    return out


def _companies(df: pd.DataFrame) -> set[str]:
    return {
        c.strip().lower()
        for c in df.get("company", pd.Series(dtype=str)).fillna("").astype(str)
        if len(c.strip()) > 3
    }


def _contains_token(text: str, tokens: set[str]) -> list[str]:
    lowered = text.lower()
    return [t for t in tokens if re.search(rf"\b{re.escape(t)}\b", lowered)]


def _sentence_count(text: str) -> int:
    return len([s for s in re.split(r"[.!?]+", text) if s.strip()])


def main() -> int:
    df = load_display_table(with_coords=False, corrections={}, notes_overlay=None)
    surnames, companies = _surnames(df), _companies(df)

    codes = sorted(
        df.loc[df["display_state"] == STATE_CLASSIFIED, "soc_major"].astype(str).unique()
    )
    eligible = [c for c in codes if len(group_members(df, c)) >= MIN_GROUP_SIZE]

    print(f"{len(codes)} classified groups; {len(eligible)} at or above the "
          f"{MIN_GROUP_SIZE}-member floor.\n")

    failures: list[str] = []
    cache: dict[str, str] = {}

    for code in eligible:
        result = summarise_group(df, code, cache=cache)
        if result.status != STATUS_SUMMARY:
            # D-45: every group here is above the floor and a key is present,
            # so "unavailable" means the call failed. It used to be skipped,
            # which let a failed summary pass this harness.
            failures.append(f"[0] {code} {result.group_name}: {result.status} "
                            "(generation failed; see the logged warning)")
            print(f"  [FAIL] {code} {result.group_name}: {result.status}")
            continue

        text = result.text or ""
        label = f"{code} {result.group_name}"

        if result.n_members < MIN_GROUP_SIZE:
            failures.append(f"[1] {label}: summarised below the floor")

        hits = _contains_token(text, surnames)
        if hits:
            failures.append(f"[2] {label}: names an individual ({', '.join(hits)})")

        hits = _contains_token(text, companies)
        if hits:
            failures.append(f"[3] {label}: names a company ({', '.join(hits)})")

        prompt = build_prompt(
            result.group_name, title_counts(result.titles), result.n_members
        )
        leaked = _contains_token(prompt, surnames) + _contains_token(prompt, companies)
        if leaked:
            failures.append(f"[4] {label}: prompt payload leaked {', '.join(leaked)}")

        n_sentences = _sentence_count(text)
        if not 1 <= n_sentences <= 4:
            failures.append(f"[5] {label}: {n_sentences} sentences")

        print(f"  [ok]   {label}: {result.n_members} people, {n_sentences} sentences")

    # Check 6 — a correction must miss the cache.
    review = df.loc[df["display_state"] != STATE_CLASSIFIED, "person_index"]
    if len(review) and eligible:
        target, code = int(review.iloc[0]), eligible[0]
        before = summarise_group(df, code, cache=cache).cache_key
        # Compose from the frame the loader already returned, not a second read
        # of the CSV: a separately-read frame carries no notes and no
        # coordinates, so it is a different table that happens to share
        # person_index values.
        moved = load_display_table(
            frame=df, with_coords=False, corrections={target: code}, notes_overlay=None
        )
        after = summarise_group(moved, code, cache=dict(cache)).cache_key
        if before == after:
            failures.append("[6] a correction did not change the cache key")
        else:
            print(f"\n  [ok]   correction into {code} produced a cache miss")

    print()
    if failures:
        print(f"FAILED — {len(failures)} issue(s):")
        for f in failures:
            print(f"  {f}")
        return 1

    print(f"PASSED — {len(eligible)} summaries, all checks clean.")
    return 0


if __name__ == "__main__":
    sys.exit(main())