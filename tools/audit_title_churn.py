"""How many saved corrections would a restore actually drop, and why?

Uses session_io's own key functions rather than an approximation, because the
question is what the PRODUCT would do, not what a diff script would do.

Compares a snapshot of the node table saved BEFORE a rebuild against the
classifier output AFTER it. The snapshot is personal data and gitignored, so a
clean checkout has none: save a copy of the node table before rebuilding, and
pass it with --old (D-40).

    python -m tools.audit_title_churn --old path/to/pre_rebuild_copy.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from src.dashboard.session_io import name_key, person_key

DEFAULT_NEW = Path("data/cache/classified.csv")


def _read(path: Path, what: str) -> pd.DataFrame:
    if not path.is_file():
        raise SystemExit(f"{what} not found: {path}\n"
                         "Save a copy of the node table BEFORE rebuilding, and pass it "
                         "with --old. Nothing was compared.")
    return pd.read_csv(path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--old", type=Path, required=True,
                    help="node table snapshot saved before the rebuild")
    ap.add_argument("--new", type=Path, default=DEFAULT_NEW,
                    help=f"classifier output after the rebuild (default {DEFAULT_NEW})")
    args = ap.parse_args(argv)

    old = _read(args.old, "--old snapshot")
    new = _read(args.new, "--new table")

    old_pk = {
        person_key(n, r): (str(n), str(r))
        for n, r in zip(old["name"], old["role"])
    }
    new_pk = {person_key(n, r) for n, r in zip(new["name"], new["role"])}

    new_by_name: dict[str, list[str]] = {}
    for n, r in zip(new["name"], new["role"]):
        new_by_name.setdefault(name_key(n), []).append(str(r))

    dropped = [old_pk[k] for k in set(old_pk) - new_pk]
    still_present = [(n, r) for n, r in dropped if name_key(n) in new_by_name]

    print(f"corrections a restore would drop : {len(dropped)}")
    print(f"  ...of people still in the network: {len(still_present)}")
    print(f"  ...of people who genuinely left  : {len(dropped) - len(still_present)}")
    print()
    print("title differences (old -> new), first 25:")
    for n, r in still_present[:25]:
        print(f"  {r!r}")
        print(f"    -> {new_by_name[name_key(n)][0]!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
