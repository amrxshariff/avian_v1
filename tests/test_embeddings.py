"""
tests/test_embeddings.py — the embeddings cache is keyed on content.

The old key was row count. It caught a differently sized export and nothing
else: a corrected title, or a different network of the same size, loaded
vectors computed from someone else's text, and the network was placed by them.

The rules under test:

  * the key changes when anything the vectors are computed from changes —
    any profile_text, their ORDER (embeddings[i] must be people[i]'s), or
    the model — and only then;
  * a changed key is a miss, never a stale load;
  * a file that cannot be trusted — truncated, or the wrong shape — is
    recomputed, not returned and not raised.

No test loads the real model: _load_model is replaced with a counting fake.

Run from the repo root:
    python -m pytest tests/test_embeddings.py -v
"""

from __future__ import annotations

import numpy as np
import pytest

import src.embeddings as embeddings
from src.embeddings import (
    EMBEDDING_DIM,
    compute_embeddings,
    content_key,
    keyed_path,
)
from src.schema import Person


def _person(i: int, text: str) -> Person:
    return Person(id=f"p{i}", name=f"Person {i}", company="", role="",
                  profile_text=text)


def _people(*texts: str) -> list[Person]:
    return [_person(i, t) for i, t in enumerate(texts)]


class _FakeModel:
    """Vectors derived from the text, so a stale load is detectable."""

    def __init__(self):
        self.calls = 0

    def encode(self, texts, **kw):
        self.calls += 1
        return np.array([
            np.full(EMBEDDING_DIM, float(sum(map(ord, t)) % 997), dtype=np.float32)
            for t in texts
        ])


@pytest.fixture
def model(monkeypatch):
    fake = _FakeModel()
    monkeypatch.setattr(embeddings, "_load_model", lambda: fake)
    return fake


# --- the key -----------------------------------------------------------------


def test_the_same_people_produce_the_same_key():
    assert content_key(_people("Analyst", "Engineer")) == \
        content_key(_people("Analyst", "Engineer"))


def test_one_edited_title_changes_the_key():
    assert content_key(_people("Analyst", "Engineer")) != \
        content_key(_people("Analyst", "Senior Engineer"))


def test_reordering_the_same_people_changes_the_key():
    """Order is part of the contract: embeddings[i] must be people[i]'s
    vector. A cache written for one order and loaded for another would
    attach every vector to the wrong person."""
    assert content_key(_people("Analyst", "Engineer")) != \
        content_key(_people("Engineer", "Analyst"))


def test_the_separator_keeps_boundaries_apart():
    assert content_key(_people("ab", "c")) != content_key(_people("a", "bc"))


def test_a_different_model_changes_the_key():
    people = _people("Analyst", "Engineer")
    assert content_key(people, "all-MiniLM-L6-v2") != \
        content_key(people, "all-mpnet-base-v2")


def test_the_key_is_in_the_filename(tmp_path):
    path = keyed_path(tmp_path / "embeddings.npy", "0123456789abcdef")
    assert path.name == "embeddings-0123456789abcdef.npy"
    assert path.parent == tmp_path


# --- the cache ---------------------------------------------------------------


def test_a_cached_matrix_is_reused_for_matching_content(tmp_path, model):
    cache = tmp_path / "embeddings.npy"
    first = compute_embeddings(_people("Analyst", "Engineer"), cache_path=cache)
    again = compute_embeddings(_people("Analyst", "Engineer"), cache_path=cache)
    assert model.calls == 1
    np.testing.assert_array_equal(first, again)


def test_changed_content_misses_the_cache_rather_than_loading_it(tmp_path, model):
    """The old failure: same row count, different text, stale vectors."""
    cache = tmp_path / "embeddings.npy"
    before = compute_embeddings(_people("Analyst", "Engineer"), cache_path=cache)
    after = compute_embeddings(_people("Analyst", "Nurse"), cache_path=cache)
    assert model.calls == 2
    assert not np.array_equal(before[1], after[1])
    assert len(list(tmp_path.glob("embeddings-*.npy"))) == 2


def test_cache_path_none_computes_and_writes_nothing(tmp_path, model, monkeypatch):
    monkeypatch.chdir(tmp_path)
    compute_embeddings(_people("Analyst"), cache_path=None)
    assert model.calls == 1
    assert list(tmp_path.rglob("*")) == []


def test_recompute_overwrites_the_keyed_file(tmp_path, model):
    cache = tmp_path / "embeddings.npy"
    people = _people("Analyst", "Engineer")
    keyed = keyed_path(cache, content_key(people))
    compute_embeddings(people, cache_path=cache)
    np.save(keyed, np.zeros((2, EMBEDDING_DIM), dtype=np.float32))

    fresh = compute_embeddings(people, cache_path=cache, recompute=True)
    assert model.calls == 2
    np.testing.assert_array_equal(np.load(keyed), fresh)
    assert fresh.any()


def test_a_truncated_cache_file_is_recomputed_rather_than_returned(tmp_path, model):
    """np.load raises on a truncated file before any shape can be checked.
    A recomputable cache must not take the build down."""
    cache = tmp_path / "embeddings.npy"
    people = _people("Analyst", "Engineer")
    keyed = keyed_path(cache, content_key(people))
    compute_embeddings(people, cache_path=cache)
    whole = keyed.read_bytes()
    keyed.write_bytes(whole[: len(whole) // 2])

    result = compute_embeddings(people, cache_path=cache)
    assert model.calls == 2
    assert result.shape == (2, EMBEDDING_DIM)
    assert keyed.read_bytes() == whole          # rewritten whole


def test_a_cache_of_the_wrong_shape_is_recomputed(tmp_path, model):
    """Belt and braces: the name matched, the contents are not these people's."""
    cache = tmp_path / "embeddings.npy"
    people = _people("Analyst", "Engineer")
    np.save(keyed_path(cache, content_key(people)),
            np.ones((2, EMBEDDING_DIM * 2), dtype=np.float32))

    result = compute_embeddings(people, cache_path=cache)
    assert model.calls == 1
    assert result.shape == (2, EMBEDDING_DIM)


def test_a_save_leaves_no_partial_file(tmp_path, model):
    cache = tmp_path / "embeddings.npy"
    compute_embeddings(_people("Analyst"), cache_path=cache)
    assert [p.name for p in tmp_path.iterdir()] == [
        keyed_path(cache, content_key(_people("Analyst"))).name
    ]


def test_the_old_unkeyed_file_is_never_read(tmp_path, model):
    """data/cache/embeddings.npy from before this change is orphaned."""
    cache = tmp_path / "embeddings.npy"
    np.save(cache, np.zeros((2, EMBEDDING_DIM), dtype=np.float32))
    result = compute_embeddings(_people("Analyst", "Engineer"), cache_path=cache)
    assert model.calls == 1
    assert result.any()
