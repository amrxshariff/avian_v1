"""Did classified drop because people LEFT, or because settled titles moved?

The second case would mean classification is not stable across rebuilds, which
would undermine every correction ever made. Run before trusting a rebuild.

Compares a snapshot of the node table saved BEFORE the rebuild against the
classifier output AFTER it. The snapshot is personal data and gitignored, so a
clean checkout has none: save a copy of the node table before rebuilding, and
pass it with --old (D-40).

    python -m tools.diff_rebuild --old path/to/pre_rebuild_copy.csv
    python -m tools.diff_rebuild --old OLD.csv --new data/cache/classified.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

DEFAULT_NEW = Path("data/cache/classified.csv")
KEY = ["name", "role"]


def _read(path: Path, what: str) -> pd.DataFrame:
    if not path.is_file():
        raise SystemExit(f"{what} not found: {path}\n"
                         "Save a copy of the node table BEFORE rebuilding, and pass it "
                         "with --old. Nothing was compared.")
    return pd.read_csv(path)


def _norm(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    for col in KEY:
        out[col] = out[col].fillna("").astype(str).str.strip().str.casefold()
    out["soc_major"] = out["soc_major"].astype("string").fillna("")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--old", type=Path, required=True,
                    help="node table snapshot saved before the rebuild")
    ap.add_argument("--new", type=Path, default=DEFAULT_NEW,
                    help=f"classifier output after the rebuild (default {DEFAULT_NEW})")
    args = ap.parse_args(argv)

    old = _norm(_read(args.old, "--old snapshot"))
    new = _norm(_read(args.new, "--new table"))

    for label, frame in (("old", old), ("new", new)):
        dupes = frame.duplicated(subset=KEY).sum()
        if dupes:
            print(f"WARNING: {dupes} duplicate (name, role) in {label} — "
                  f"the join below will over-count")

    old_keys = set(map(tuple, old[KEY].to_numpy()))
    new_keys = set(map(tuple, new[KEY].to_numpy()))

    merged = old.merge(new, on=KEY, suffixes=("_old", "_new"))
    changed = merged[merged["soc_major_old"] != merged["soc_major_new"]]

    print(f"old rows     : {len(old)}")
    print(f"new rows     : {len(new)}")
    print(f"left network : {len(old_keys - new_keys)}")
    print(f"joined       : {len(new_keys - old_keys)}")
    print(f"in both      : {len(old_keys & new_keys)}")
    print(f"reclassified : {len(changed)}   <-- must be 0")

    if len(changed):
        cols = KEY + ["soc_major_old", "soc_major_new",
                      "is_uncertain_old", "is_uncertain_new"]
        print()
        print(changed[cols].to_string(index=False, max_rows=40))

    old_names = set(old["name"])
    new_names = set(new["name"])
    stayed = old.merge(new, on="name", suffixes=("_old", "_new"))
    retitled = stayed[stayed["role_old"] != stayed["role_new"]]

    print()
    print("--- keyed on name alone ---")
    print(f"genuinely left : {len(old_names - new_names)}")
    print(f"genuinely new  : {len(new_names - old_names)}")
    print(f"present in both: {len(old_names & new_names)}")
    print(f"changed title  : {len(retitled)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
