"""P2.9a: synthetic export generator. Pure, no data files, no API."""

from datetime import datetime

import pandas as pd
import pytest

from src import synthetic as syn
from tools import measure_synthetic as ms

MAJORS = ["11", "13", "15", "17", "19", "21", "23", "25", "27", "29", "31",
          "33", "35", "37", "39", "41", "43", "45", "47", "49", "51", "53", "55"]


@pytest.fixture(scope="module")
def onet():
    rows = []
    for m in MAJORS:
        for i in range(200):
            rows.append({syn.ONET_CODE_COL: f"{m}-{1000 + i}.00", syn.ONET_TITLE_COL: f"Role {m} Type {i}"})
    rows += [
        {syn.ONET_CODE_COL: "13-2011.00", syn.ONET_TITLE_COL: "Accountant, Tax"},
        {syn.ONET_CODE_COL: "13-2011.00", syn.ONET_TITLE_COL: "Very Long Five Word Title"},
    ]
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def rows(onet):
    return syn.generate(onet, syn.Spec())


def test_exact_row_count(rows):
    assert len(rows) == syn.Spec().n_rows


def test_deterministic(onet, rows):
    assert syn.render(syn.generate(onet, syn.Spec())) == syn.render(rows)


def test_different_seed_differs(onet, rows):
    assert syn.render(syn.generate(onet, syn.Spec(seed=7))) != syn.render(rows)


def test_names_never_collide(rows):
    keys = [syn.name_key(r.first, r.last) for r in rows]
    assert len(set(keys)) == len(keys)


def test_every_row_survives_linkedin_keep_rule(rows):
    # linkedin.py keeps a row with a name and at least one of role/company
    assert all(r.first and r.last and (r.position or r.company) for r in rows)


def test_strata_counts_are_exactly_allocated(rows):
    spec = syn.Spec()
    got = {s: sum(1 for r in rows if r.stratum == s) for s in syn.STRATA}
    assert got == syn.allocate(spec.n_rows, spec.stratum_weights)


def test_allocate_sums_and_rejects_partial_weights():
    w = syn.Spec().stratum_weights
    for n in (1, 7, 442, 1000):
        assert sum(syn.allocate(n, w).values()) == n
    with pytest.raises(ValueError):
        syn.allocate(10, {"occupational": 1.0})


def test_blank_positions_only_from_blank_stratum(rows):
    assert all((r.position == "") == (r.stratum == "blank") for r in rows)


def test_occupational_titles_come_from_onet(onet, rows):
    clean = set(syn.clean_onet_titles(onet, syn.Spec().max_title_words)["title"])
    for r in rows:
        if r.stratum == "occupational":
            words = r.position.split()
            base = " ".join(words[1:]) if words[0] in syn.SENIORITY_PREFIX else r.position
            assert base in clean, r.position


def test_onet_cleaning_drops_military_punctuation_and_long_titles(onet):
    clean = syn.clean_onet_titles(onet, 4)
    assert "55" not in set(clean["major"])
    assert "Accountant, Tax" not in set(clean["title"])
    assert "Very Long Five Word Title" not in set(clean["title"])


def test_distinct_title_count_is_exact(rows):
    # repeats also exercise centrality.py's zero-distance clip
    nonblank = [r.position for r in rows if r.position]
    assert len(set(nonblank)) == syn.Spec().distinct_titles < len(nonblank)


def test_repeats_stay_within_their_stratum(rows):
    by_title = {}
    for r in rows:
        if r.position:
            by_title.setdefault(r.position, set()).add(r.stratum)
    assert all(len(s) == 1 for s in by_title.values())


def test_blank_stratum_path_when_weighted(onet):
    w = dict(syn.Spec().stratum_weights, blank=0.06)
    spec = syn.Spec(stratum_weights=w, distinct_titles=380)
    got = syn.generate(onet, spec)
    blanks = [r for r in got if r.stratum == "blank"]
    assert blanks and all(r.position == "" and r.company for r in blanks)
    assert len({r.position for r in got if r.position}) == 380


def test_occupational_groups_limited_to_eligible(rows):
    majors = {r.source_major for r in rows if r.source_major}
    assert len(majors) <= syn.Spec().eligible_groups
    assert all(r.source_major is None for r in rows
               if r.stratum not in ("occupational", "multi_hat"))


def test_impossible_repeat_count_raises(onet):
    with pytest.raises(ValueError):
        syn.generate(onet, syn.Spec(distinct_titles=2))


def test_exhausted_pool_raises_rather_than_duplicating(onet):
    w = {s: 0.0 for s in syn.STRATA}
    w["vague"] = 1.0                                   # 60 templates, 442 rows
    with pytest.raises(syn.PoolExhausted):
        syn.generate(onet, syn.Spec(stratum_weights=w, distinct_titles=442))


def test_render_is_a_linkedin_export(rows):
    lines = syn.render(rows).split("\n")
    header_at = next(i for i, l in enumerate(lines) if l.lower().startswith("first name"))
    assert 0 < header_at <= 10            # preamble present, within linkedin.py's scan
    df = pd.read_csv(pd.io.common.StringIO(syn.render(rows)), skiprows=header_at, dtype=str,
                     keep_default_na=False)
    assert list(df.columns) == syn.HEADER
    assert len(df) == len(rows)
    assert (df["URL"] == "").all() and (df["Email Address"] == "").all()
    dates = [datetime.strptime(d, "%d %b %Y") for d in df["Connected On"]]
    assert dates == sorted(dates, reverse=True)


def test_stratum_never_written_to_export(rows):
    text = syn.render(rows)
    assert "occupational" not in text and "student_seeking" not in text


def test_outcome_counts_from_a_classified_frame(rows):
    n = len(rows)
    unc = [i % 100 < 29 for i in range(n)]            # 29% uncertain, mid-band
    soc = ["99" if u else ("13" if i % 3 else "29") for i, u in enumerate(unc)]
    soc[-1] = "15"                                     # one tiny group
    unc[-1] = False
    frame = pd.DataFrame({"is_uncertain": unc, "soc_major": soc})
    o = ms.outcome(rows, frame)
    assert o["needs_review"] == sum(unc)
    assert o["in_band"] is True
    assert o["ge5"] >= 1 and o["lt5"] >= 1
    assert set(o["by_stratum"].index) <= set(syn.STRATA)


def test_name_key_matches_session_io_if_available():
    session_io = pytest.importorskip("src.dashboard.session_io")
    for first, last in [("Anne", "O'Neil"), ("  jo ", "SMITH"), ("Zoë", "Brown")]:
        assert syn.name_key(first, last) == session_io.name_key(f"{first} {last}")


def test_unparsed_titles_found_by_the_cache_key(rows):
    key = lambda title, company: f"{title.lower()}||{company}"
    some = list(dict.fromkeys(r.position for r in rows if r.position))[:3]
    cache = {key(some[0], ""): {"soc": None, "confidence": "low", "why": "unparsed"},
             key(some[1], ""): {"soc": None, "confidence": "low", "why": "no job function"},
             key(some[2], ""): {"soc": "13", "confidence": "high", "why": "accountant"}}
    assert ms.unparsed_titles(rows, cache, key) == [some[0]]
