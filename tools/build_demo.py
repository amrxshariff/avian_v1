"""
tools/build_demo.py — classify the synthetic export once and ship the result.

The demo network must contain no real person. src/synthetic.py already produces
a raw Connections.csv from Faker names and O*NET titles; this runs the real
build over it and writes the node table the app ships.

Run once, from the repo root, with ANTHROPIC_API_KEY set:
    python -m tools.build_demo

Roughly $0.40 of classification the first time. Titles already in the cache are
free, so a re-run after a tweak costs almost nothing.

The output is TRACKED. That is the point: the demo is identical for every
visitor and costs nothing at runtime.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

SYNTHETIC_CSV = Path("data/synthetic/Connections.csv")
DEMO_DIR = Path("data/demo")
DEMO_NODES = DEMO_DIR / "network_nodes.csv"  # loader-exempt: this WRITES the demo output; src/dashboard/loader.py's DEMO_NODES_CSV is the only reader
DEMO_PROVENANCE = DEMO_DIR / "provenance.json"


def main() -> int:
    from src.build import build_network
    from src.dashboard.keys import KEY_PROJECT
    from src.claude_classifier import CACHE_PATH

    if not SYNTHETIC_CSV.exists():
        print(f"No synthetic export at {SYNTHETIC_CSV}. Generate one first:")
        print("    python -m src.synthetic")
        return 1

    print(f"Building the demo from {SYNTHETIC_CSV} (this one costs money)...")
    # Said explicitly: build_network has no default source (D-63), and this
    # runs on ANTHROPIC_API_KEY from the environment, which is the project's.
    #
    # The cache is said explicitly for the same reason (D-71). This is the one
    # caller that genuinely wants the shared, tracked file: the demo ships its
    # cache, so a clone rebuilding reads the cached classifications rather than
    # taking a fresh draw from a non-deterministic classifier (D-69). Every other
    # classifying caller of build_network is a session, and a session's titles
    # are real people's and do not belong on a shared disk.
    # (tools/diag_canvas.py builds with classify=False and writes nothing.)
    result = build_network(
        SYNTHETIC_CSV, source=KEY_PROJECT, cache_path=CACHE_PATH,
    )

    if not result.complete:
        # A partial demo would ship people in the fourth state forever, with a
        # Retry button nobody can action. Better to fail and re-run.
        print(f"\nIncomplete: {len(result.unclassified)} people unclassified "
              f"({sorted(result.reasons)}). Nothing written — fix and re-run; "
              "everything already classified is cached, so the retry is cheap.")
        return 1

    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    result.nodes.to_csv(DEMO_NODES, index=False)

    provenance = {
        "generated": date.today().isoformat(),
        # Not "source": the build's provenance also carries that key, for
        # whose key paid, and spreading it below silently overwrote this.
        # Two facts, two names.
        "data": "src/synthetic.py — Faker names, O*NET 30.3 job titles",
        "people": int(result.people),
        "real_people": 0,
        **{k: v for k, v in result.provenance.items() if k != "intake"},
    }
    DEMO_PROVENANCE.write_text(json.dumps(provenance, indent=2), encoding="utf-8")

    needs_review = int(result.nodes["is_uncertain"].sum())
    print(f"\nWrote {DEMO_NODES} ({result.people} people)")
    print(f"     {DEMO_PROVENANCE}")
    print(f"  needs review: {needs_review} "
          f"({needs_review / result.people:.1%}) — compare against the real "
          "network's 29.0% before shipping.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
