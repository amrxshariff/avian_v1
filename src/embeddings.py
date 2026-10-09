"""
embeddings.py — Phase 1, Day 3

Turns each person's profile_text into a dense semantic vector using
sentence-transformers (all-MiniLM-L6-v2, 384 dims). Results are cached to
disk, keyed on content, so they are not recomputed on every run.

Row order of the returned matrix matches the order of the input people list:
embeddings[i] corresponds to people[i]. Downstream stages (HDBSCAN, UMAP)
depend on this alignment, so the order is never changed.

Run from the repo root:
    python -m src.embeddings
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import numpy as np

from src.ingestion import load_profiles
from src.schema import Person

# --- Configuration -----------------------------------------------------------

MODEL_NAME = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384  # all-MiniLM-L6-v2 output dimensionality

# data/cache/ is gitignored — safe place for recomputable artifacts.
DEFAULT_CACHE_PATH = Path("data/cache/embeddings.npy")

# How many hex characters of the content hash go in the filename. 16 is
# 64 bits: collisions are not a practical concern at one file per rebuild,
# and a shorter name stays readable in a directory listing.
HASH_LENGTH = 16


def content_key(people: list[Person], model_name: str = MODEL_NAME) -> str:
    """A fingerprint of exactly what the vectors are computed from.

    The model, then profile_text and its order, which is the whole input to
    the encoder. Two runs agreeing here must produce identical vectors, and
    two runs differing anywhere must not share a cache. Order is part of the
    contract: embeddings[i] must correspond to people[i], so the same people
    in a different order are a different key.

    Row count was the old key. It caught a differently sized export and
    nothing else: re-running after correcting a title, or against a different
    person with the same headcount, silently returned vectors computed from
    someone else's text, and the network was then placed by them.

    The model is in the key because MODEL_NAME is the one other input. Change
    it, and without this every cached file would still match — returning
    another model's vectors, possibly at another width.
    """
    digest = hashlib.sha256()
    digest.update(model_name.encode("utf-8"))
    digest.update(b"\x00")
    for person in people:
        # The separator matters: without it, ("ab", "c") and ("a", "bc")
        # hash identically, and a title edited across a boundary would hit
        # a cache computed from different text.
        digest.update(person.profile_text.encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()[:HASH_LENGTH]


def keyed_path(cache_path: Path, key: str) -> Path:
    """The cache file for this content, beside the path the caller named.

    The key is in the FILENAME rather than a sidecar. A sidecar is a second
    file to keep in step, and a mismatch there is a comparison that can be
    got wrong; in the name, a mismatch is simply a miss, and a stale file is
    visibly stale in a directory listing.
    """
    return cache_path.with_name(f"{cache_path.stem}-{key}{cache_path.suffix}")


# --- Model loading -----------------------------------------------------------

def _load_model():
    """
    Load the sentence-transformer model once.

    Imported lazily inside the function so that merely importing this module
    (e.g. for the cache path) does not pull in the heavy dependency. The first
    call downloads ~80MB from Hugging Face and caches it locally; later calls
    are fast.
    """
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(MODEL_NAME)


# --- Public API --------------------------------------------------------------

def compute_embeddings(
    people: list[Person],
    cache_path: Path | str | None = DEFAULT_CACHE_PATH,
    recompute: bool = False,
) -> np.ndarray:
    """
    Return a (len(people), 384) embedding matrix, aligned to `people` order.

    Caching:
      - The cache file is named for its content: cache_path's stem plus
        content_key(people), e.g. embeddings-3f9a1c0b7d2e4a51.npy. If that
        file exists and loads with the expected shape, it is returned
        (unless recompute=True).
      - Otherwise the model encodes all profile_text strings in one batch,
        the result is saved under that keyed name, and returned.

    Changed content is a different name, so it misses rather than loading
    stale vectors; there is nothing to invalidate. Each distinct content
    leaves its own file, and deleting data/cache/ is always safe.
    """
    # cache_path=None: compute in memory and write nothing. A raw export is
    # real people's names, and P2.9b's build holds one network for a session
    # rather than leaving a matrix on a shared disk.
    cache_path = Path(cache_path) if cache_path is not None else None

    key = content_key(people) if cache_path is not None else None
    keyed = keyed_path(cache_path, key) if cache_path is not None else None
    expected = (len(people), EMBEDDING_DIM)

    # --- Try the cache first ---
    if keyed is not None and not recompute and keyed.exists():
        try:
            cached = np.load(keyed)
        except (ValueError, EOFError, OSError) as exc:
            # A truncated or corrupt file raises inside np.load, before any
            # shape could be checked. It is a recomputable cache: rebuild it
            # rather than take the build down.
            cached = None
            print(f"Cache at {keyed} could not be read ({exc}) — recomputing.")
        if cached is not None and cached.shape == expected:
            print(f"Loaded cached embeddings from {keyed} (shape {cached.shape}).")
            return cached
        if cached is not None:
            # Belt and braces. The key is derived from these people and this
            # model, so a shape mismatch means the file was written by
            # something else — recompute rather than trust it.
            print(
                f"Cache at {keyed} has shape {cached.shape}, expected "
                f"{expected} — recomputing."
            )

    # --- Compute ---
    texts = [person.profile_text for person in people]

    model = _load_model()
    print(f"Encoding {len(texts)} profiles with '{MODEL_NAME}'...")
    embeddings = model.encode(
        texts,
        batch_size=32,
        show_progress_bar=True,
        convert_to_numpy=True,
    )

    # Sanity check before anything downstream depends on it.
    if embeddings.shape != expected:
        raise ValueError(
            f"Unexpected embedding shape {embeddings.shape}, expected {expected}."
        )

    # --- Save cache ---
    if cache_path is None:
        return embeddings

    keyed.parent.mkdir(parents=True, exist_ok=True)
    # Written beside the target and renamed into place, so an interrupted
    # save leaves no half-written file under the name a later run trusts.
    partial = keyed.with_name(keyed.name + ".partial")
    with open(partial, "wb") as handle:
        np.save(handle, embeddings)
    os.replace(partial, keyed)
    print(f"Saved embeddings to {keyed} (shape {embeddings.shape}).")

    return embeddings


def main() -> None:
    """CLI entry point: load profiles, embed them, report the matrix shape."""
    people = load_profiles()
    embeddings = compute_embeddings(people)

    print(f"\nEmbedding matrix shape: {embeddings.shape}")
    print(f"Alignment check: people[0] = {people[0].name!r}")
    print(f"                 embeddings[0][:5] = {embeddings[0][:5]}")


if __name__ == "__main__":
    main()
