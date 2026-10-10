"""
src/dashboard/provenance.py — who classified this network, said plainly.

The scope document is specific: stated on screen, not in a tooltip. A person
looking at occupation groups attributed to an authoritative taxonomy is
entitled to know which model produced them and whose credit paid, without
hunting for it.

Two shapes answer one question. A BuildResult carries provenance from this
session's build; the demo carries data/demo/provenance.json, written by
tools/build_demo.py when it was classified in advance. The reader does not
care which code path produced the line, so neither is rendered differently.

Left out deliberately: prompt_version and tau are for whoever is debugging a
classification, not for the person reading it, and intake already has its own
line in the upload panel. A line nobody can act on is noise on a screen that
already carries four figures.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from src.dashboard.keys import KEY_NONE, KEY_PROJECT, KEY_USER

DEMO_PROVENANCE = Path("data/demo/provenance.json")

_WHOSE_KEY = {
    KEY_USER: "your own API key",
    KEY_PROJECT: "this demo's shared allowance",
}


def load_demo_provenance(path: Path | str = DEMO_PROVENANCE) -> dict:
    """What the shipped demo records about itself, or {} if unreadable.

    Never raises. A missing or malformed file means the line is not shown;
    the network is still real and still renders, and an exception here would
    take down a screen over a caption.
    """
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — a caption is never worth a crash
        return {}


def demo_line(provenance: dict) -> str:
    """The example network's line.

    real_people is surfaced because it is the strongest privacy statement the
    app can make and it currently exists only in a file nobody reads.
    """
    model = provenance.get("model")
    if not model:
        return ""
    line = f"Example network, classified in advance by {model}."
    if provenance.get("real_people") == 0:
        line += " No real person appears in it."
    return line


def whose_key(provenance: dict) -> Optional[str]:
    """Whose key paid for a build, as words, or None when nothing can be claimed.

    The one answer to that question (D-83). The provenance line and the upload
    panel's note both ask it, and they were worded separately until the note
    told visitors who had pasted nothing that their key paid. None covers a
    keyless build, more than one key, an unrecorded source, and a value
    outside the vocabulary (build_network defaulted to "project_key" before
    D-63): in each, the honest sentence names no key.
    """
    if provenance.get("mixed_sources"):
        return None
    return _WHOSE_KEY.get(provenance.get("source"))


def built_line(built) -> str:
    """This session's build, or empty when nothing was classified.

    A keyless build says nothing here. Nothing was classified, the notice
    below already explains the fourth state, and "classified by nobody" is
    a sentence that answers a question no one asked.
    """
    provenance = (getattr(built, "provenance", None) or {})
    source = provenance.get("source")
    model = provenance.get("model")

    if not model or source == KEY_NONE:
        return ""

    # More than one key, no recorded source, or a value outside the
    # vocabulary: name the model and claim nothing about the key.
    whose = whose_key(provenance)
    if whose is None:
        return f"Classified by {model}."
    return f"Classified by {model}, using {whose}."


def provenance_line(built, demo_provenance: Optional[dict] = None) -> str:
    """One sentence for whichever network is on screen, or empty."""
    if built is not None:
        return built_line(built)
    if demo_provenance is None:
        demo_provenance = load_demo_provenance()
    return demo_line(demo_provenance)
