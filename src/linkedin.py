"""
src/linkedin.py — Phase 1.5, Day 9: real LinkedIn export loader.

Loads a LinkedIn "Connections" CSV into Person objects for everything
downstream (classification, embeddings, projection, graph). Reached via
src.ingestion.load_profiles().

Robust to the export's usual quirks:
  * a 2-3 line "Notes:" preamble before the real header (auto-detected; also
    fine when you've already stripped it to a clean header row);
  * UTF-8 BOM from an Excel re-save (utf-8-sig);
  * blank Company / Position cells (LinkedIn withholds them for some contacts);
  * columns you may have trimmed away (URL, Email, Connected On) — never
    required, and dropped for GDPR minimisation if present.

A row is kept when it has a name AND at least one of role/company — a bare name
carries no clustering signal. Dropped rows are counted and reported, never
silently lost.

profile_text is the role alone, or role + company when
config.PROFILE_TEXT_INCLUDE_COMPANY is True. Nothing is inferred and nothing
is written to disk: loading an export has no side effects.

Run from the repo root:
    python -m src.linkedin
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src import config
from src.schema import Person

# Header aliases -> our canonical field. Matched case-insensitively on the
# stripped column name, so "First Name" / "first name" both resolve.
_COLMAP = {
    "first name": "first",
    "last name": "last",
    "company": "company",
    "position": "role",
}


def _read_source(source) -> bytes:
    """The export's bytes, from a path, raw bytes, or an upload.

    P2.9b: a Streamlit upload arrives as a file-like object in memory, and it
    stays that way. Writing it to a temporary file to satisfy a Path signature
    would put a stranger's connections on a shared disk for no reason.
    """
    if isinstance(source, bytes):
        return source
    if isinstance(source, (str, Path)):
        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(
                f"LinkedIn export not found at {path.resolve()}. Place your "
                "Connections.csv in data/raw/ (gitignored) or update "
                "config.LINKEDIN_CSV."
            )
        return path.read_bytes()

    read = getattr(source, "read", None)
    if read is None:
        raise TypeError(
            f"Cannot read a LinkedIn export from {type(source).__name__}."
        )
    if hasattr(source, "seek"):
        source.seek(0)
    data = read()
    return data if isinstance(data, bytes) else str(data).encode("utf-8")


def _find_header_row(data: bytes, encoding: str = "utf-8-sig") -> int:
    """Index of the row that starts the real table (the 'First Name' header).

    Returns 0 when there is no preamble. Scans only the first ~10 lines.
    """
    text = data.decode(encoding, errors="replace")
    for i, line in enumerate(text.splitlines()):
        if i > 10:
            break
        if line.lower().lstrip().startswith("first name"):
            return i
    return 0


def _clean(value) -> str:
    """CSV cell -> trimmed string; NaN/None -> ''."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def load_linkedin_profiles(
    source: Path | str | bytes | None = None,
    stats: dict | None = None,
) -> list[Person]:
    """Load, clean and validate the LinkedIn export into Person objects.

    Row order is preserved (never shuffled) so the returned list aligns with the
    embeddings matrix computed downstream.
    """
    import io

    label = getattr(source, "name", None) or (
        Path(source).name if isinstance(source, (str, Path)) else "the upload"
    )
    data = _read_source(source if source is not None else config.LINKEDIN_CSV)

    header_row = _find_header_row(data)
    df = pd.read_csv(io.BytesIO(data), skiprows=header_row, dtype=str,
                     encoding="utf-8-sig")

    # Map recognised columns; ignore any extras (URL/Email/Connected On/etc.).
    # Normalise headers defensively: strip a stray BOM (if utf-8-sig didn't) and
    # surrounding whitespace before matching.
    def _norm(c: str) -> str:
        return c.replace("\ufeff", "").strip().lower()

    resolved = {c: _COLMAP[_norm(c)] for c in df.columns if _norm(c) in _COLMAP}
    df = df.rename(columns=resolved)

    # Drop everything we did not ask for, immediately. A LinkedIn export ships
    # email addresses, profile URLs and connection dates; none of it is used,
    # and holding it in a frame for the rest of the parse means it can reach a
    # traceback, a log line or a debugger. The cheapest way not to leak a
    # column is not to carry it.
    wanted = [c for c in ("first", "last", "role", "company") if c in df.columns]
    discarded = [c for c in df.columns if c not in wanted]
    df = df[wanted]

    # Rows that are entirely blank — the trailing newline at the end of a file,
    # a separator line someone left in a spreadsheet. Dropped before counting,
    # so they are never reported as "skipped": nothing was there to skip.
    before_blank = len(df)
    df = df.replace(r"^\s*$", pd.NA, regex=True).dropna(how="all")
    blank_rows = before_blank - len(df)

    for required in ("role", "company"):
        if required not in df.columns:
            raise KeyError(
                f"Column for '{required}' not found. Saw {list(df.columns)}. "
                "Expected LinkedIn headers First Name, Last Name, Company, Position."
            )

    people: list[Person] = []
    dropped_no_name = 0
    dropped_no_role_or_company = 0
    idx = 0

    for _, row in df.iterrows():
        first = _clean(row.get("first"))
        last = _clean(row.get("last"))
        name = " ".join(p for p in (first, last) if p)
        role = _clean(row.get("role"))
        company = _clean(row.get("company"))

        if not name:
            dropped_no_name += 1
            continue
        if not role and not company:
            dropped_no_role_or_company += 1
            continue

        people.append(Person(id=f"li{idx:03d}", name=name,
                             company=company, role=role))
        idx += 1

    total = len(df)
    if stats is not None:
        stats.update({
            "rows": total,
            "blank_rows": blank_rows,
            "kept": len(people),
            "dropped_no_name": dropped_no_name,
            "dropped_no_role_or_company": dropped_no_role_or_company,
            "columns_discarded": discarded,
        })

    print(f"Read {total} rows from {label} (header at line {header_row}).")
    if discarded:
        print(f"  ignored columns: {', '.join(discarded)}")
    print(f"  kept:    {len(people)}")
    print(f"  dropped: {dropped_no_name} no-name, "
          f"{dropped_no_role_or_company} no role/company")
    blank_company = sum(1 for p in people if not p.company)
    blank_role = sum(1 for p in people if not p.role)
    print(f"  of kept: {blank_role} missing role, {blank_company} missing company")

    for p in people:
        if config.PROFILE_TEXT_INCLUDE_COMPANY:
            p.build_profile_text()
        else:
            p.profile_text = p.role

    return people


def main() -> None:
    people = load_linkedin_profiles()
    print(f"\nLoaded {len(people)} LinkedIn profiles.")
    sample = people[0]
    print("\nSample record (first profile):")
    print(f"  id:      {sample.id}")
    print(f"  name:    {sample.name}")
    print(f"  company: {sample.company}")
    print(f"  role:    {sample.role}")
    print(f"  profile_text: {sample.profile_text!r}")


if __name__ == "__main__":
    main()