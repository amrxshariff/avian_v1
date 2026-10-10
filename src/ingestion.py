"""
ingestion.py - the one entry point from a LinkedIn export to Person objects.

Phases 0-1 carried a second loader for the archetype generator's JSON-list CSV,
switched by a config flag. P2.9a retired both: the demo dataset is itself a
LinkedIn-format export (data/synthetic/Connections.csv), so there is one format
and one path.

Run from the repo root:
    python -m src.ingestion
"""

from __future__ import annotations

from pathlib import Path

from src.schema import Person


def load_profiles(csv_path: Path | str | None = None) -> list[Person]:
    """Person objects from a LinkedIn export. None reads config.LINKEDIN_CSV."""
    from src.linkedin import load_linkedin_profiles   # lazy, as before: keeps the import graph acyclic
    # Positional (D-79): the parameter was renamed path -> source in 719d64f,
    # and the old keyword left every command-line module raising TypeError.
    return load_linkedin_profiles(csv_path)


def main() -> None:
    people = load_profiles()
    print(f"Loaded {len(people)} profiles.")
    if people:
        p = people[0]
        print(f"  first: {p.name} | {p.role} | {p.company}")


if __name__ == "__main__":
    main()
