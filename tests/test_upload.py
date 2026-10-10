"""
tests/test_upload.py — P2.9b: upload, and the build that spends nothing.

Two things under test, and they are the same promise from two ends:

  * build_network(classify=False) returns the WHOLE network with nobody
    grouped, which is only coherent because option B made "no answer yet" a
    state every surface already renders;
  * the panel around it never writes the upload anywhere, and turns every bad
    file into a sentence the person holding it can act on.

Run from the repo root:
    python -m pytest tests/test_upload.py -v
"""

from __future__ import annotations

import io

import pytest

from src.build import InvalidExport, MAX_PEOPLE, MIN_PEOPLE, WARN_PEOPLE, build_network
from src.dashboard.session_build import (
    BUILT_KEY, CLASSIFICATION_CACHE_KEY, TOUCHED_KEY, classification_cache, get_built,
)
from src.dashboard.state import STATE_NOT_CLASSIFIED, apply_corrections, review_counts
from src.dashboard.unclassified import REASON_COLUMN, can_retry, reasons_in
from src.dashboard.keys import KEY_NONE, KEY_PROJECT, KEY_USER, remember_key
from src.dashboard.retry_offer import OFFER_SLOT, offer_retry
from src.dashboard.upload import (
    CLASSIFIED_TAIL,
    KEYLESS_NOTE,
    KEY_SECTION_LABEL,
    MAX_UPLOAD_MB,
    render_upload_panel,
)
from src.failure_reasons import REASON_NO_KEY
from tests.test_build import _Client, _embed, _people, _project

HEADER = "First Name,Last Name,Company,Position\n"


def _csv(rows: int, preamble: str = "") -> bytes:
    body = "".join(
        f"P{i},Person,Acme,Title {i % 6}\n" for i in range(rows)
    )
    return (preamble + HEADER + body).encode("utf-8")


class _Upload(io.BytesIO):
    """What Streamlit hands over: bytes with a name and a size."""

    def __init__(self, data: bytes, name: str = "Connections.csv"):
        super().__init__(data)
        self.name = name
        self.size = len(data)


class FakeStreamlit:
    def __init__(self, upload=None, click: bool = False):
        self.captions: list[str] = []
        self.errors: list[str] = []
        self.successes: list[str] = []
        self.buttons: list[str] = []
        self.warnings: list[str] = []
        self._upload = upload
        self._click = click

    def caption(self, text): self.captions.append(text)
    def warning(self, text, **kw): self.warnings.append(text)
    def error(self, text): self.errors.append(text)
    def success(self, text): self.successes.append(text)

    def button(self, label, **kw):
        self.buttons.append(label)
        return self._click

    def file_uploader(self, label, **kw):
        return self._upload

    def spinner(self, _text):
        class _Null:
            def __enter__(self): return None
            def __exit__(self, *a): return False
        return _Null()

    def expander(self, label, **kw):
        class _Null:
            def __enter__(self): return None
            def __exit__(self, *a): return False
        return _Null()

    def text_input(self, label, **kw):
        return ""

    @property
    def text(self) -> str:
        return " ".join(self.captions + self.errors + self.successes).lower()


def _build(upload, **kw):
    """The real build, with the two heavyweight steps faked."""
    return build_network(upload, embed=_embed, project=_project, **kw)


def _built():
    """A minimal, valid BuildResult — for stub builders that don't need a
    real upload, only something with .people to hand back."""
    return build_network(people=_people(10), classify=False,
                         embed=_embed, project=_project)


# --- the keyless build -------------------------------------------------------


def test_a_build_with_no_classifier_still_places_everyone():
    result = build_network(people=_people(30), classify=False,
                           embed=_embed, project=_project)

    assert result.people == 30
    assert not result.complete
    assert set(result.reasons) == {REASON_NO_KEY}
    assert not result.nodes[["umap_3d_x", "umap_3d_y", "umap_3d_z"]].isna().any().any()
    assert result.nodes["pagerank"].notna().all()


def test_nobody_is_asked_to_review_a_network_nobody_classified():
    """The backlog is empty, not full: no one declined, no one was asked."""
    result = build_network(people=_people(30), classify=False,
                           embed=_embed, project=_project)
    shown = apply_corrections(result.nodes, {})

    assert (shown["display_state"] == STATE_NOT_CLASSIFIED).all()
    assert review_counts(result.nodes, {}) == (0, 0)
    assert not result.nodes["is_uncertain"].any()


def test_no_retry_is_offered_without_a_key():
    """Retrying the same nothing would fail the same way."""
    result = build_network(people=_people(10), classify=False,
                           embed=_embed, project=_project)
    shown = apply_corrections(result.nodes, {})
    assert reasons_in(shown) == [REASON_NO_KEY]
    assert not can_retry(reasons_in(shown))


def test_a_keyless_build_makes_no_calls_at_all():
    client = _Client()
    build_network(people=_people(10), classify=False, client=client,
                  embed=_embed, project=_project)
    assert client.calls == []


def test_classifying_later_fills_the_groups_without_moving_anyone(tmp_path):
    """The keyless build and a retry are the two halves of one promise."""
    from src.build import retry_unclassified

    keyless = build_network(people=_people(20), classify=False,
                            embed=_embed, project=_project)
    filled = retry_unclassified(keyless, client=_Client(),
                                cache_path=tmp_path / "c.json")

    layout = ["umap_3d_x", "umap_3d_y", "umap_3d_z", "pagerank"]
    assert filled.complete
    assert keyless.nodes[layout].equals(filled.nodes[layout])
    assert set(filled.nodes[REASON_COLUMN]) == {""}


# --- reading an upload -------------------------------------------------------


def test_an_upload_is_parsed_from_memory(tmp_path, monkeypatch):
    """Nothing reaches the disk: the bytes are all there is."""
    monkeypatch.chdir(tmp_path)
    result = _build(_Upload(_csv(30)), classify=False)
    assert result.people == 30
    assert list(tmp_path.iterdir()) == []


def test_a_linkedin_preamble_is_skipped():
    """Real exports open with a notes block before the header."""
    preamble = "Notes:\nWhen exporting, some fields may be empty.\n\n"
    assert _build(_Upload(_csv(12, preamble)), classify=False).people == 12


def test_a_csv_that_is_not_an_export_is_refused():
    data = b"colour,animal\nred,fox\nblue,cat\n"
    with pytest.raises(InvalidExport, match="LinkedIn"):
        _build(_Upload(data), classify=False)


def test_there_is_no_row_cap_by_default():
    """Decided 24 September: no hard limit until one has been measured.

    The guard stays in the code and stays tested, because the moment the
    memory spike produces a number, MAX_PEOPLE is where it goes.
    """
    assert MAX_PEOPLE is None
    assert _build(_Upload(_csv(WARN_PEOPLE + 10)), classify=False).people == \
        WARN_PEOPLE + 10


def test_a_cap_refuses_when_one_is_set(monkeypatch):
    import src.build as build

    monkeypatch.setattr(build, "MAX_PEOPLE", 20)
    with pytest.raises(InvalidExport, match="20"):
        _build(_Upload(_csv(21)), classify=False)


def test_a_large_upload_is_warned_about_but_not_refused(monkeypatch):
    """No measured ceiling means no honest refusal — only a warning.

    Keyless: the warning comes before the build, so classification has
    nothing to do with it. With a key in the shell, this sent its titles to
    the real API (D-74)."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    store: dict = {}
    st = FakeStreamlit(upload=_Upload(_csv(WARN_PEOPLE + 50)))
    st.warnings = []
    render_upload_panel(st=st, store=store,
                        build_fn=lambda s, **k: _build(s, **k))
    assert st.warnings and "memory" in st.warnings[0].lower()
    assert get_built(store) is not None


def test_an_export_below_the_floor_is_refused():
    with pytest.raises(InvalidExport, match="At least"):
        _build(_Upload(_csv(MIN_PEOPLE - 1)), classify=False)


# --- the panel ---------------------------------------------------------------


def test_the_panel_holds_the_build_and_reports_it(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    store: dict = {}
    st = FakeStreamlit(upload=_Upload(_csv(20)))
    result = render_upload_panel(
        st=st, store=store,
        build_fn=lambda src, **kw: _build(src, **kw),
    )

    assert result is not None
    assert get_built(store) is result
    # The network, its clock, and the session's classification cache (D-71).
    assert set(store) == {BUILT_KEY, TOUCHED_KEY, CLASSIFICATION_CACHE_KEY}
    assert "20 connections placed" in st.text
    assert "group" in st.text          # says what is missing


def test_the_panel_builds_without_a_classifier(monkeypatch):
    """The panel must not quietly spend money the user has not offered."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    seen: dict = {}

    def spy(upload, **kw):
        seen.update(kw)
        return _build(upload, **kw)

    render_upload_panel(st=FakeStreamlit(upload=_Upload(_csv(10))),
                        store={}, build_fn=spy)
    assert seen["classify"] is False


def test_upload_classifies_when_a_key_is_configured(monkeypatch):
    """D-57: has_key drives this. A truthiness bug here is invisible —
    both branches build a network, and only one of them classifies."""
    seen = {}

    def builder(upload, classify, source=None, cache_path=None, meters=None):
        seen["classify"] = classify
        seen["source"] = source
        return _built()

    monkeypatch.setattr("src.dashboard.keys.key_source", lambda store=None: KEY_PROJECT)
    render_upload_panel(st=FakeStreamlit(upload=_Upload(_csv(10))),
                        store={}, build_fn=builder)
    assert seen["classify"] is True
    assert seen["source"] == KEY_PROJECT  # D-63: asserted, not defaulted


def test_the_key_field_renders_with_a_built_network_on_screen():
    """D-61: a keyless build already on screen is exactly the moment someone
    would want to paste a key — the field must reach that side of the fork."""
    store = {BUILT_KEY: _built()}
    st = FakeStreamlit()
    render_upload_panel(st=st, store=store)
    assert "no key?" in st.text


def test_the_key_field_renders_before_a_file_is_chosen():
    store: dict = {}
    st = FakeStreamlit()  # no upload yet
    render_upload_panel(st=st, store=store)
    assert "no key?" in st.text


class _CountingExpanders(FakeStreamlit):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.expanders: list[str] = []

    def expander(self, label, **kw):
        self.expanders.append(label)
        return super().expander(label, **kw)


def test_unboxed_the_key_field_opens_no_expander_of_its_own():
    """D-66: the sidebar has already put the panel in "Your network", and
    Streamlit refuses an expander inside another. This fake would not have
    refused — tests/test_app_smoke.py is what runs the real rule."""
    for store in ({}, {BUILT_KEY: _built()}):
        st = _CountingExpanders()
        render_upload_panel(st=st, store=store, boxed=False)
        assert st.expanders == []
        assert KEY_SECTION_LABEL in st.captions
        assert "no key?" in st.text


def test_boxed_by_default_for_the_welcome_screen():
    st = _CountingExpanders()
    render_upload_panel(st=st, store={})
    assert st.expanders == [KEY_SECTION_LABEL]


def test_a_key_configured_shows_the_classified_note_not_the_keyless_one(monkeypatch):
    monkeypatch.setattr("src.dashboard.keys.key_source", lambda store=None: KEY_PROJECT)
    st = FakeStreamlit(upload=_Upload(_csv(10)))
    render_upload_panel(st=st, store={},
                        build_fn=lambda upload, classify, source=None, cache_path=None, meters=None: _built())
    assert any(CLASSIFIED_TAIL in c for c in st.captions)
    assert KEYLESS_NOTE not in st.captions


def test_no_key_still_shows_the_keyless_note(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    st = FakeStreamlit(upload=_Upload(_csv(10)))
    render_upload_panel(st=st, store={},
                        build_fn=lambda upload, classify, source=None, cache_path=None, meters=None: _built())
    assert KEYLESS_NOTE in st.captions
    assert not any(CLASSIFIED_TAIL in c for c in st.captions)


def test_a_bad_file_is_explained_not_swallowed():
    store: dict = {}
    st = FakeStreamlit(upload=_Upload(b"colour,animal\nred,fox\n"))
    assert render_upload_panel(st=st, store=store,
                               build_fn=lambda s, **k: _build(s, **k)) is None
    # Nothing held: the session's cache may exist, but it is empty (D-71).
    assert {k: v for k, v in store.items() if v} == {}
    assert "linkedin" in st.text


def test_an_oversized_file_is_refused_before_it_is_read():
    store: dict = {}
    called = []
    upload = _Upload(b"x")
    upload.size = (MAX_UPLOAD_MB + 1) * 1024 * 1024
    st = FakeStreamlit(upload=upload)

    render_upload_panel(st=st, store=store, build_fn=lambda *a, **k: called.append(1))
    assert called == [] and store == {}
    assert f"{MAX_UPLOAD_MB} mb" in st.text


def test_no_upload_does_nothing():
    st = FakeStreamlit(upload=None)
    assert render_upload_panel(st=st, store={}) is None
    assert st.errors == []


def test_the_panel_offers_a_way_back_to_the_demo():
    result = build_network(people=_people(10), classify=False,
                           embed=_embed, project=_project)
    store = {BUILT_KEY: result}
    reran = []
    st = FakeStreamlit(click=True)

    render_upload_panel(st=st, store=store, on_built=lambda: reran.append(1))
    assert get_built(store) is None
    assert reran == [1]


# --- cleaning the export -----------------------------------------------------


REAL_HEADER = ("First Name,Last Name,URL,Email Address,Company,Position,"
               "Connected On\n")


def _real_export(rows: int) -> bytes:
    """The shape LinkedIn actually ships: a notes preamble, a blank line, and
    columns we never asked for — including email addresses."""
    preamble = ("Notes:\n"
                '"When exporting your connection data, you may notice that some '
                'of the email addresses are missing."\n'
                "\n")
    body = "".join(
        f"P{i},Person,https://linkedin.com/in/p{i},p{i}@example.com,"
        f"Acme,Title {i % 6},08 Sep 2026\n"
        for i in range(rows)
    )
    return (preamble + REAL_HEADER + body + "\n\n").encode("utf-8")


def test_the_real_export_shape_parses():
    assert _build(_Upload(_real_export(30)), classify=False).people == 30


def test_columns_we_never_asked_for_are_dropped_immediately():
    """Email addresses must not be carried through the parse at all.

    A column that is never loaded cannot reach a traceback, a log line or a
    debugger, which is a stronger guarantee than remembering not to print it.
    """
    result = _build(_Upload(_real_export(20)), classify=False)
    discarded = result.provenance["intake"]["columns_discarded"]
    assert "Email Address" in discarded and "URL" in discarded
    assert "@example.com" not in result.nodes.to_csv()


def test_blank_rows_are_ignored_rather_than_counted_as_skipped():
    empty_row = b",,,,,,\n"
    data = _real_export(12).replace(
        b"P5,Person,https://linkedin.com/in/p5,p5@example.com,Acme,"
        b"Title 5,08 Sep 2026\n",
        empty_row,
    )
    result = _build(_Upload(data), classify=False)
    intake = result.provenance["intake"]
    assert result.people == 11
    assert intake["blank_rows"] >= 1


@pytest.mark.parametrize("keyed", [False, True], ids=["keyless", "classified"])
def test_the_panel_says_what_it_did_not_use(keyed, monkeypatch):
    """442 placed from a 456-row file invites the question; answer it.

    "What it did not use" is the intake: rows skipped, columns not read. It
    does not depend on classification, and both sides are run to show it. This
    test used to classify only when the shell happened to hold a key, with
    the real API (D-74)."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    store: dict = {}
    if keyed:
        remember_key("sk-ant-user", store)
    st = FakeStreamlit(upload=_Upload(_real_export(20)))

    result = render_upload_panel(
        st=st, store=store,
        build_fn=lambda s, **k: _build(s, client=_Client(), **k),
    )

    assert result.complete is keyed
    assert "columns not read" in st.text
    assert "email address" in st.text


# --- D-63: the build's own provenance, asserted at the call site ------------


def test_the_panel_threads_the_session_key_source_into_the_build():
    """Without this, provenance always says "project" — even when the build
    just classified on the visitor's own key — and a later key_failed reads
    as our outage rather than their key."""
    store: dict = {}
    remember_key("sk-ant-user", store)
    st = FakeStreamlit(upload=_Upload(_csv(10)))

    result = render_upload_panel(
        st=st, store=store,
        build_fn=lambda s, **k: _build(s, client=_Client(), **k),
    )

    assert result.provenance["source"] == KEY_USER


def test_a_keyless_build_records_key_none_not_a_key_it_did_not_have(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    st = FakeStreamlit(upload=_Upload(_csv(10)))
    result = render_upload_panel(st=st, store={},
                                 build_fn=lambda s, **k: _build(s, **k))
    assert result.provenance["source"] == KEY_NONE


def test_a_new_build_clears_a_pending_offer(monkeypatch):
    """The offer, if any, pointed at the network this build just replaced.

    Keyed, because that is the only way an offer exists: key_field makes one
    when a key is pasted over a keyless build, so the next upload classifies
    on that key. This used to reach the real API when the shell held a key,
    and build keyless when it did not (D-74)."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    store: dict = {}
    remember_key("sk-ant-user", store)
    offer_retry(store)
    st = FakeStreamlit(upload=_Upload(_csv(10)))

    result = render_upload_panel(
        st=st, store=store,
        build_fn=lambda s, **k: _build(s, client=_Client(), **k),
    )

    assert result.complete
    assert OFFER_SLOT not in store
