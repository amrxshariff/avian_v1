"""
src/dashboard/search.py — P2.4 node filtering.

A pure, Streamlit-free substring filter over the display table, so it unit-tests
without a running server (same discipline as state.py and canvas.py). app.py
calls filter_nodes() on each rerun; the returned frame drives the result list,
and selecting a row feeds highlight_index into build_figure.

Matching rules:
  * case-insensitive substring of the query against ANY search field (OR across
    fields, so "analyst" matches on role and "finance" on soc_major_name);
  * an empty or whitespace-only query returns the frame UNCHANGED — the whole
    network is the unfiltered default, not an empty result;
  * fields absent from the frame are skipped, not errored, so the same function
    works before optional columns exist (P2.2 appends enriched skill terms to
    DEFAULT_SEARCH_FIELDS later);
  * NaN cells are treated as empty strings, never matched, never crash;
  * row order is preserved, so the result list is stable across keystrokes.
"""

from __future__ import annotations

import pandas as pd

# Searched in this order. soc_major_name covers "SOC group" from the DoD;
# name/role are the LinkedIn-derived identity. Enriched skill/tool terms get
# appended here once P2.2 self-enrichment lands — filter_nodes needs no change.
DEFAULT_SEARCH_FIELDS: tuple[str, ...] = ("name", "role", "soc_major_name", "note")


def filter_nodes(
    df: pd.DataFrame,
    query: str,
    fields: tuple[str, ...] = DEFAULT_SEARCH_FIELDS,
) -> pd.DataFrame:
    """Rows where `query` is a case-insensitive substring of ANY search field.

    Empty/whitespace query -> `df` unchanged (unfiltered default). A non-empty
    query with no hits -> empty frame (the caller renders the empty state). If
    none of `fields` are present in `df`, returns empty rather than silently
    matching nothing-as-everything, so a schema mismatch is visible.
    """
    q = query.strip().lower()
    if not q:
        return df

    present = [f for f in fields if f in df.columns]
    if not present:
        return df.iloc[0:0]

    mask = pd.Series(False, index=df.index)
    for f in present:
        col = df[f].fillna("").astype(str).str.lower()
        mask |= col.str.contains(q, regex=False)
    return df[mask]


def filter_caption(n_matches: int, n_total: int, filtering: bool) -> str:
    """The result counter's text.

    The "N of M" form describes a filter narrowing the list. With no query and
    no groups there is nothing to narrow, so "442 of 442 shown" restates the
    population and disagrees in vocabulary with the header's "442 people".

    The guard is `filtering`, NOT n_matches == n_total: a filter that happens
    to match everyone is still active, and the counter saying "442 of 442" is
    how the user knows it. That is a different case from at-rest, and the two
    must not be collapsed.
    """
    if not filtering:
        return f"{n_total} people"
    return f"{n_matches} of {n_total} shown"  # count-exempt: guarded by `filtering`; the filtered-and-matching-all case is intended
