"""
tests/test_session_cache.py — D-71: a session's titles stay in its own cache.

A session build classified real people's job titles into the shared, tracked
classification cache, under a welcome screen that says the export is never
saved. The cache can now be a mapping the caller holds. These tests pin that a
mapping is used as the cache and never becomes a file, that a build or retry
given no cache writes nothing, that the session's mapping saves the repeat
calls a shared file used to, and that the paths still meant to use the file do.

The conftest fixture redirects CACHE_PATH to a per-test file, so "writes no
file" is checked against that file: a path that fell back to the default
would create it.
"""

from __future__ import annotations

import json

import src.claude_classifier as cc
from src.build import build_network, retry_unclassified
from src.classify_pipeline import classify_people
from src.dashboard.keys import remember_key
from src.dashboard.session_build import classification_cache, clear_built
from src.dashboard.upload import render_upload_panel
from tests.test_build import _Client, _embed, _people, _project
from tests.test_upload import FakeStreamlit, _Upload, _build, _csv

_OK = {"soc": "13", "confidence": "high", "why": "ok"}


def _sent(client) -> list[str]:
    return [t for call in client.calls for t in call]


# --- the mapping is the cache --------------------------------------------------


def test_a_mapping_is_read_from_and_written_to():
    cache = {"known title||": dict(_OK)}
    client = _Client()

    outcome = cc.classify_claude_outcome(
        [("Known Title", ""), ("New Title", "")], client=client, cache_path=cache,
    )

    assert _sent(client) == ["New Title"]          # the known one was read
    assert "new title||" in cache                   # the new one was written
    assert all(a is not None for a in outcome.answers)
    assert not cc.CACHE_PATH.exists()


def test_saving_to_a_mapping_writes_no_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cache: dict = {}
    cc._save_cache({"a||": dict(_OK)}, cache)
    assert list(tmp_path.iterdir()) == []
    assert not cc.CACHE_PATH.exists()


def test_the_pipeline_passes_a_mapping_through_uncoerced():
    """Path() on a dict raises, so a coercion here fails every session build."""
    cache: dict = {}
    classify_people(_people(4, titles=["Pipeline Title"]), partial=True,
                    client=_Client(), cache_path=cache)
    assert "pipeline title||" in cache
    assert not cc.CACHE_PATH.exists()


# --- no cache given: nothing written ------------------------------------------


def test_a_retry_with_no_cache_path_writes_no_file():
    """retry_unclassified had the same shared-file default as the build: the
    second writer named in D-71."""
    before = build_network(people=_people(10), client=_Client(fail_at=1),
                           cache_path={}, embed=_embed, project=_project)
    assert not before.complete

    retry_unclassified(before, client=_Client())

    assert not cc.CACHE_PATH.exists()


def test_a_session_build_through_the_upload_panel_writes_no_file():
    """The path that wrote 365 real titles: an upload, with a key."""
    store: dict = {}
    remember_key("sk-ant-user", store)
    st = FakeStreamlit(upload=_Upload(_csv(10)))

    result = render_upload_panel(
        st=st, store=store,
        build_fn=lambda s, **k: _build(s, client=_Client(), **k),
    )

    assert result.complete
    assert classification_cache(store)              # the titles are here...
    assert not cc.CACHE_PATH.exists()               # ...and nowhere else


# --- a session's mapping saves what the shared file used to -------------------


def test_the_panel_passes_one_mapping_for_the_whole_session():
    store: dict = {}
    seen = []

    def spy(upload, **kw):
        seen.append(kw["cache_path"])
        return _build(upload, client=_Client(), **kw)

    for _ in range(2):
        render_upload_panel(st=FakeStreamlit(upload=_Upload(_csv(10))),
                            store=store, build_fn=spy)
        clear_built(store)                          # Start over

    assert len(seen) == 2
    assert seen[0] is seen[1] is classification_cache(store)


def test_two_builds_sharing_a_mapping_classify_a_title_once():
    cache: dict = {}
    client = _Client()
    people = _people(10)

    build_network(people=people, client=client, cache_path=cache,
                  embed=_embed, project=_project)
    first = len(client.calls)
    second = build_network(people=people, client=client, cache_path=cache,
                           embed=_embed, project=_project)

    assert first > 0
    assert len(client.calls) == first               # nothing sent the second time
    assert second.complete
    assert second.provenance["uncached_titles"] == 0


def test_a_retry_reads_titles_the_session_already_answered():
    """Classify a network, Start over, rebuild keyless, then add a key and
    retry: every title was answered earlier in the session, so the retry
    sends nothing."""
    cache: dict = {}
    people = _people(10)
    build_network(people=people, client=_Client(), cache_path=cache,
                  embed=_embed, project=_project)
    keyless = build_network(people=people, classify=False, cache_path=cache,
                            embed=_embed, project=_project)
    assert not keyless.complete

    client = _Client()
    after = retry_unclassified(keyless, client=client, cache_path=cache)

    assert client.calls == []
    assert after.complete


# --- the paths still meant to use the file ------------------------------------


def test_the_cli_pipeline_with_no_cache_path_still_uses_the_file():
    classify_people(_people(4, titles=["Cli Title"]), partial=True,
                    client=_Client())
    assert "cli title||" in json.loads(cc.CACHE_PATH.read_text(encoding="utf-8"))


def test_a_save_to_the_file_keeps_every_key_already_in_it():
    cc.CACHE_PATH.write_text(json.dumps({"earlier title||": _OK}), encoding="utf-8")

    cc.classify_claude_outcome([("Later Title", "")], client=_Client())

    on_disk = json.loads(cc.CACHE_PATH.read_text(encoding="utf-8"))
    assert set(on_disk) == {"earlier title||", "later title||"}
