"""tools/reconcile_counter.py - D-24: does the remaining counter agree with the save file?

Counts only. No names, no titles: this reads a real session file, and the
project's rule is that real network data stays on the machine it came from.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from src.dashboard.loader import load_display_table

NAME_CANDIDATES = ("name", "full_name", "person")
ROLE_CANDIDATES = ("role", "title", "raw_title", "position")


def _pick(frame, candidates, label):
    for c in candidates:
        if c in frame.columns:
            return c
    raise SystemExit(f"no {label} column; looked for {candidates}")


def main() -> int:
    if len(sys.argv) < 2:
        raise SystemExit("usage: python -m tools.reconcile_counter <session.json>")

    payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))

    base = load_display_table(
        with_coords=False, corrections={}, notes_overlay=lambda d: d
    )
    name_col = _pick(base, NAME_CANDIDATES, "name")
    role_col = _pick(base, ROLE_CANDIDATES, "role")

    state = {
        (str(r[name_col]), str(r[role_col])): str(r["display_state"])
        for _, r in base.iterrows()
    }
    base_review = sum(1 for v in state.values() if v == "needs_review")

    buckets = Counter(
        state.get((str(e["name"]), str(e["role"])), "no match")
        for e in payload.get("corrections", [])
    )

    saved = len(payload.get("corrections", []))
    resolved = buckets.get("needs_review", 0)

    print(f"\nbase table: {len(base)} rows, {base_review} needs_review")
    print(f"matched on ({name_col}, {role_col})\n")
    print(f"corrections in file: {saved}")
    for k, v in sorted(buckets.items()):
        print(f"  target base state {k:>14}: {v}")
    print(f"\npredicted remaining: {base_review} - {resolved} = {base_review - resolved}")
    print("compare against the header and queue counters in the live app.")
    return 0


if __name__ == "__main__":
    sys.exit(main())