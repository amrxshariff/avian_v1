"""
tools/check_uncertainty_honesty.py — P2.5 / P2.1 definition-of-done item 9.
VERSION 3 (shared loader).

"Inspection against the assembled display table confirms no uncertain node
renders as confidently classified."

Inspection by eye does not scale to 430 rows and cannot be re-run after a
refactor, so this is the executable form of that criterion. Standalone,
deliberately outside Streamlit: if it passes here and the dashboard still shows
a grey node carrying a group name, the fault is in the render/cache layer, not
the data.

A node passes through three layers on its way to the user's eye and can be
honest in one and dishonest in the next:

    table   -> is_uncertain / soc_major / display_state   (state.py)
    canvas  -> the marker colour it is drawn with          (canvas.py)
    card    -> the group name it is described with         (card.py)

All three are checked, plus the inverse (no classified node silently missing a
group) and the correction round-trip (an assignment must actually leave the
needs-review state; "not an occupation" must not become a hue).

Prints person_index only — never names, titles or employers — so the output is
safe to paste into a commit message or QA log.

Run from the repo root:
    python -m tools.check_uncertainty_honesty

Exit 0 = all checks passed. Exit 1 = at least one failed or errored.
"""

from __future__ import annotations

import sys
import traceback

import pandas as pd

from src.dashboard.loader import load_display_table

VERSION = "v3 (shared loader)"

STATE_NEEDS_REVIEW = "needs_review"
STATE_CLASSIFIED = "classified"
STATE_NOT_OCCUPATION = "not_occupation"

results: list[tuple[str, str, str]] = []  # (check_id, status, detail)


def record(check_id: str, ok: bool, detail: str = "") -> None:
    results.append((check_id, "PASS" if ok else "FAIL", detail))


def record_error(check_id: str, exc: BaseException) -> None:
    results.append((check_id, "ERROR", f"{type(exc).__name__}: {exc}"))


def _norm_group(value) -> str | None:
    """CSV cell -> canonical 2-digit group string, or None for 'no group'.

    pandas reads a column of '11'/'13' as int64 and a column with blanks as
    float64 with NaN; both must collapse to the same notion of absent. "99" is
    the base table's unreviewed-abstain code and is likewise 'no group'.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    s = str(value).strip()
    if s in ("", "nan", "None", "99"):
        return None
    return s.split(".")[0].zfill(2)


def main() -> int:
    print(f"check_uncertainty_honesty {VERSION}\n")

    df = load_display_table(corrections={}, notes_overlay=None)
    print(f"Loaded {len(df)} rows through load_display_table() (sidecar merged)")
    n = len(df)

    print()

    from src.onet import MAJOR_GROUP_NAMES

    # --- C1: column contract -------------------------------------------------
    required = {"person_index", "is_uncertain", "soc_major", "classifier_tier"}
    missing = required - set(df.columns)
    record("C1 column contract", not missing,
           "all present" if not missing else f"missing {sorted(missing)}")
    if missing:
        return report()

    uncertain_mask = df["is_uncertain"].astype(bool)
    uncertain_idx = set(df.loc[uncertain_mask, "person_index"].astype(int))
    print(f"  {len(uncertain_idx)} of {n} rows flagged is_uncertain "
          f"({100 * len(uncertain_idx) / n:.1f}%)\n")

    groups = df["soc_major"].map(_norm_group)

    # --- C2: an uncertain node carries no committed group --------------------
    # Catches a node the classifier abstained on that still has a group sitting
    # in the column, ready for any downstream join that reads soc_major without
    # also reading is_uncertain.
    leaks = df.loc[uncertain_mask & groups.notna(), "person_index"].astype(int).tolist()
    record("C2 uncertain -> no group in table", not leaks,
           "clean" if not leaks else f"{len(leaks)} rows carry a group: {leaks[:12]}")

    # --- C3: the inverse — a classified node must carry a valid group --------
    # Load-bearing for C8: canvas._point_colour falls back to NEEDS_REVIEW_GREY
    # for a classified node with a malformed code, which would put grey into the
    # classified-hue set and make C8 report a false collision.
    bad = df.loc[~uncertain_mask & ~groups.isin(MAJOR_GROUP_NAMES), "person_index"]
    bad = bad.astype(int).tolist()
    record("C3 classified -> valid group", not bad,
           "clean" if not bad else f"{len(bad)} rows blank or off-taxonomy: {bad[:12]}")

    # --- C4-C7: the state layer ----------------------------------------------
    # df is already composed by load_display_table(corrections={}) — no need to
    # re-apply an empty correction to get `shown`.
    shown = df
    try:
        from src.dashboard import state as state_mod
        from src.dashboard.state import apply_corrections

        if "display_state" not in shown.columns:
            raise KeyError("returned frame has no display_state column")

        review_idx = set(
            shown.loc[shown["display_state"] == STATE_NEEDS_REVIEW,
                      "person_index"].astype(int)
        )
        record("C4 needs_review set == is_uncertain set",
               review_idx == uncertain_idx,
               "exact match" if review_idx == uncertain_idx else
               f"only in needs_review: {sorted(review_idx - uncertain_idx)[:8]}; "
               f"only in is_uncertain: {sorted(uncertain_idx - review_idx)[:8]}")

        if uncertain_idx:
            probe = sorted(uncertain_idx)[0]
            before_major = df.loc[df["person_index"] == probe, "soc_major"].iloc[0]

            after = apply_corrections(df, {probe: "15"})
            row = after.loc[after["person_index"] == probe].iloc[0]
            ok = (row["display_state"] == STATE_CLASSIFIED
                  and _norm_group(row["soc_major"]) == "15")
            record("C6 correction leaves needs_review", ok,
                   f"node {probe} -> {row['display_state']} / "
                   f"{_norm_group(row['soc_major'])}")

            # The overlay must return a copy — df itself must be untouched by
            # the call above. df now arrives pre-composed via
            # load_display_table(), so this round trip (the one remaining real
            # apply_corrections(dict) call) is where non-mutation is provable.
            after_major = df.loc[df["person_index"] == probe, "soc_major"].iloc[0]
            unmutated = after_major == before_major
            record("C5 base frame not mutated", unmutated,
                   "unchanged" if unmutated
                   else f"soc_major for node {probe} changed on df itself: "
                        f"{before_major!r} -> {after_major!r}")

            after2 = apply_corrections(df, {probe: state_mod.NOT_OCCUPATION})
            row2 = after2.loc[after2["person_index"] == probe].iloc[0]
            ok2 = (row2["display_state"] == STATE_NOT_OCCUPATION
                   and _norm_group(row2["soc_major"]) not in MAJOR_GROUP_NAMES)
            record("C7 not-an-occupation stays greyed", ok2,
                   f"node {probe} -> {row2['display_state']} / {row2['soc_major']}")
        else:
            record("C5 base frame not mutated", True,
                   "skipped — no uncertain nodes in this table to probe with")
    except Exception as exc:  # noqa: BLE001 — one bad layer must not hide the rest
        record_error("C4-C7 state layer", exc)
        traceback.print_exc()

    # --- C8: canvas — the colour actually drawn ------------------------------
    # Checked through the real figure rather than a colour-map lookup, so it
    # survives the P2.4b trace split: every trace is walked and its markers
    # matched back to person_index via customdata[0].
    if any(c.startswith("C8") for c, _, _ in results):
        pass  # sidecar merge already failed; do not report the same fault twice
    else:
        try:
            from src.dashboard.canvas import build_figure

            fig = build_figure(shown if shown is not None else df,
                               highlight_index=None)
            hues: set[str] = set()
            uncertain_colours: list[tuple[int, str]] = []
            for trace in fig.data:
                colours = getattr(trace.marker, "color", None)
                custom = getattr(trace, "customdata", None)
                if colours is None or custom is None:
                    continue
                if isinstance(colours, str):
                    colours = [colours] * len(custom)
                for cd, colour in zip(custom, colours):
                    pid = int(cd[0] if hasattr(cd, "__len__") else cd)
                    col = str(colour).lower()
                    (uncertain_colours.append((pid, col))
                     if pid in uncertain_idx else hues.add(col))

            # An uncertain node is honest iff its colour is NOT one of the hues
            # used for classified nodes. The specific grey is not hardcoded: the
            # requirement is separation from the categorical space, not a hex.
            collisions = [p for p, c in uncertain_colours if c in hues]
            greys = {c for _, c in uncertain_colours}
            record("C8 uncertain colour outside palette", not collisions,
                   f"{len(uncertain_colours)} uncertain markers, {len(greys)} "
                   f"distinct grey(s) {sorted(greys)}, {len(hues)} classified hues"
                   + ("" if not collisions else f" — COLLISION on {collisions[:8]}"))
        except Exception as exc:  # noqa: BLE001
            record_error("C8 canvas layer", exc)
            traceback.print_exc()

    # --- C9: card — the words shown to the user ------------------------------
    try:
        from src.dashboard.card import group_label

        group_names = set(MAJOR_GROUP_NAMES.values())
        offenders = []
        source = shown if shown is not None else df
        for pid in sorted(uncertain_idx):
            row = source.loc[source["person_index"] == pid].iloc[0]
            label = str(group_label(row))
            if label in group_names:
                offenders.append((pid, label))
        record("C9 card shows no group for uncertain", not offenders,
               f"{len(uncertain_idx)} cards checked"
               + ("" if not offenders
                  else f" — {len(offenders)} name a SOC group: {offenders[:6]}"))
    except Exception as exc:  # noqa: BLE001
        record_error("C9 card layer", exc)

    return report()


def report() -> int:
    print("\n" + "=" * 62)
    width = max(len(c) for c, _, _ in results)
    for check_id, status, detail in results:
        print(f"  {status:<5} {check_id:<{width}}  {detail}")
    print("=" * 62)

    failed = [c for c, s, _ in results if s != "PASS"]
    if failed:
        print(f"\n  DoD item 9: NOT SIGNED OFF — {len(failed)} check(s) failed "
              f"or errored: {failed}")
        return 1
    print("\n  DoD item 9: PASSED — no uncertain node renders as confidently "
          "classified, at any layer.")
    return 0


if __name__ == "__main__":
    sys.exit(main())