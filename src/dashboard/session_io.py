"""
src/dashboard/session_io.py — Phase 2, P2.8c: session save and restore.

DoD: a download control exports the session's work as one JSON file to the
user's own machine; an upload restores it. Nothing is written server-side.
Version A holds unchanged — the file is the user's, and it never leaves their
computer in either direction.

What is saved
-------------
Corrections, per-person notes, and self-enrichment (both the inputs and the
comparison result, at the user's request).

Why not person_index
--------------------
person_index derives from EXPORT ROW ORDER. Re-export a LinkedIn connections
file with forty new people and index 87 names someone else. An index-keyed save
file would silently reattach every correction and note to the wrong person — a
false claim about an individual, which is the failure this project refuses. So
the file speaks IDENTITY, and restore translates identity back to whatever index
the current table uses. The session dicts keep their existing index-keyed shape
on both sides, so set_note() and apply_corrections() are untouched.

Two different match keys, deliberately
--------------------------------------
A correction is a verdict on a TITLE: you judged "Finance Intern" to be group
13. If that person is now "Associate", reapplying 13 is a stale claim, so a miss
is the correct outcome. Corrections key on name plus title.

A note is about a PERSON: "met at the Kings Cross meetup" stays true when their
job changes, and notes are the ten people you actually know — the more valuable
artefact. Notes key on name alone, but carry the title they were WRITTEN
against, and reattach with a drift flag when it has changed: "their role has
changed since you wrote this". That is the only rule that keeps the note and
stays honest about the drift, which is the same principle as a grey needs-review
node beating a confident wrong classification.

Duplicate names DROP and REPORT, never guess. Two people genuinely called James
Smith is rare in 430 connections, and "1 note could not be matched: two people
named James Smith" is honest where a coin-flip is a fabrication.

Ordering constraint (read before moving the panel)
--------------------------------------------------
enrich.py binds KEY_TITLE and KEY_ABOUT directly to st.text_input/st.text_area.
Streamlit permits writing a widget key BEFORE its widget is created — that
becomes the initial value — but raises StreamlitAPIException if you write it
after. render_session_io() must therefore run ABOVE render_enrichment_panel()
in the sidebar. Same class of trap as the chat highlight needing to be read
above build_figure.

This module never touches frame assembly. Restore writes into the same session
dicts the loader already reads live on every rerun (P2.8b decision D5), so a
restored file appears on the next rerun with the loader knowing nothing about
files.
"""

from __future__ import annotations

import dataclasses
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pandas as pd

# 2 since D-84: the enrichment result is one Classification, not a Comparison of
# two. A version-1 file still loads (restore_enrichment_reading takes its
# About-informed half). A version-2 file is refused by a version-1 build, with
# the "saved by a newer version" message, rather than mis-loaded.
FORMAT_VERSION = 2
APP_NAME = "network-visualiser"

NAME_COLUMN = "name"
ROLE_COLUMN = "role"
INDEX_COLUMN = "person_index"

# Miss reasons, surfaced verbatim to the user.
MISS_NO_MATCH = "no longer in your network"
MISS_TITLE_CHANGED = "their title has changed"
MISS_DUPLICATE = "more than one person with that name"

FILENAME_PREFIX = "network-visualiser-session"


class UnsupportedVersion(ValueError):
    """The file was written by a newer build than this one understands."""


# --- keys --------------------------------------------------------------------


def _collapse(text: Any) -> str:
    if text is None or (isinstance(text, float) and pd.isna(text)):
        return ""
    return re.sub(r"\s+", " ", str(text)).strip().lower()


def name_key(name: Any) -> str:
    """Match key for notes: the person, independent of their job."""
    return _collapse(name)


def person_key(name: Any, role: Any) -> str:
    """Match key for corrections: the person AND the title judged."""
    return f"{_collapse(name)}|{_collapse(role)}"


# --- report ------------------------------------------------------------------


@dataclass(frozen=True)
class Miss:
    label: str      # what the user would recognise: "Grace Hopper"
    reason: str
    kind: str       # "correction" | "note"


@dataclass(frozen=True)
class Drift:
    """A note that reattached to a person whose title has since changed."""

    person_index: int
    label: str
    was: str
    now: str


@dataclass(frozen=True)
class RestoreReport:
    corrections_applied: int = 0
    corrections_total: int = 0
    notes_applied: int = 0
    notes_total: int = 0
    enrichment_restored: bool = False
    misses: tuple[Miss, ...] = ()
    drifts: tuple[Drift, ...] = ()

    @property
    def applied(self) -> int:
        return self.corrections_applied + self.notes_applied

    @property
    def total(self) -> int:
        return self.corrections_total + self.notes_total

    def sentence(self) -> str:
        """One honest line per kind. Never rounds a miss away.

        Corrections and notes are counted separately (D-27). A dropped
        correction returns a node to grey and costs one click from the review
        queue; a dropped note is the user's own writing, gone for good. One
        merged fraction hides which of the two happened.
        """
        if not self.total:
            return "That file had no corrections or notes in it."
        parts = []
        if self.corrections_total:
            noun = "correction" if self.corrections_total == 1 else "corrections"
            parts.append(
                # count-exempt: equality is the reassurance — "181 of 181 corrections" is the point
                f"{self.corrections_applied} of {self.corrections_total} {noun}"
            )
        if self.notes_total:
            noun = "note" if self.notes_total == 1 else "notes"
            parts.append(f"{self.notes_applied} of {self.notes_total} {noun}")  # count-exempt: equality is the reassurance — "181 of 181 corrections" is the point
        return "Re-applied " + " and ".join(parts) + "."


# --- export ------------------------------------------------------------------


def _identity_lookup(
    df: pd.DataFrame, wanted: set[int] | None = None
) -> dict[int, tuple[str, str]]:
    """name and role for the indices being saved.

    Scoped to `wanted` because build_export needs identity only for rows that
    carry a correction or a note — a few dozen, not the whole table — and it
    runs on EVERY rerun to fill the download button. Unscoped, that is an
    O(rows) iterrows() per keystroke once live search lands (D-12).
    """
    frame = df if wanted is None else df[df[INDEX_COLUMN].astype(int).isin(wanted)]
    return {
        int(row[INDEX_COLUMN]): (
            str(row.get(NAME_COLUMN, "")), str(row.get(ROLE_COLUMN, ""))
        )
        for _, row in frame.iterrows()
    }


def dump_result(result: Any) -> dict | None:
    """Serialise the enrichment result generically.

    dataclasses.asdict rather than a hand-written mapping, so a field added to
    the result later is carried without this module knowing about it. Returns
    None for anything that is not a dataclass instance.
    """
    if result is None or not dataclasses.is_dataclass(result):
        return None
    return dataclasses.asdict(result)


def build_export(
    df: pd.DataFrame,
    corrections: dict[int, str],
    notes: dict[int, str],
    *,
    title: str = "",
    about: str = "",
    result: Any = None,
    now: datetime | None = None,
) -> dict:
    """The save file, as a dict. Identity-keyed; no person_index anywhere."""
    wanted = {int(i) for i in (corrections or {})} | {int(i) for i in (notes or {})}
    identity = _identity_lookup(df, wanted)
    stamp = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")

    corrections_out = []
    for index, code in (corrections or {}).items():
        who = identity.get(int(index))
        if who is None:
            continue          # already unmatched; nothing to save
        corrections_out.append({"name": who[0], "role": who[1], "soc_major": str(code)})

    notes_out = []
    for index, text in (notes or {}).items():
        who = identity.get(int(index))
        if who is None or not str(text).strip():
            continue
        # role is stored as the title the note was WRITTEN against, which is
        # what makes the drift flag possible on restore.
        notes_out.append({"name": who[0], "role": who[1], "text": str(text)})

    payload: dict[str, Any] = {
        "format_version": FORMAT_VERSION,
        "app": APP_NAME,
        "saved_at": stamp,
        "corrections": corrections_out,
        "notes": notes_out,
    }

    enrichment: dict[str, Any] = {}
    if str(title).strip() or str(about).strip():
        enrichment["title"] = str(title)
        enrichment["about"] = str(about)
    dumped = dump_result(result)
    if dumped is not None:
        enrichment["result"] = dumped
        enrichment["generated_at"] = stamp
    if enrichment:
        payload["enrichment"] = enrichment

    return payload


def to_json(payload: dict) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False)


def export_filename(now: datetime | None = None) -> str:
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
    return f"{FILENAME_PREFIX}-{stamp}.json"


# --- restore -----------------------------------------------------------------


def _index_tables(df: pd.DataFrame) -> tuple[dict[str, list[int]], dict[str, list[int]]]:
    by_person: dict[str, list[int]] = {}
    by_name: dict[str, list[int]] = {}
    for _, row in df.iterrows():
        index = int(row[INDEX_COLUMN])
        by_person.setdefault(person_key(row.get(NAME_COLUMN), row.get(ROLE_COLUMN)), []).append(index)
        by_name.setdefault(name_key(row.get(NAME_COLUMN)), []).append(index)
    return by_person, by_name


def load_result(data: dict | None, result_cls: Any, member_cls: Any) -> Any:
    """Rebuild the enrichment result from its serialised form.

    Only DECLARED fields are read, so a file written by a build with an extra
    field loads rather than raising. A file missing a required field returns
    None — a partial classification presented as whole would be worse than none.
    """
    if not isinstance(data, dict) or result_cls is None:
        return None
    try:
        kwargs = {}
        for f in dataclasses.fields(result_cls):
            value = data.get(f.name)
            if isinstance(value, dict) and member_cls is not None:
                allowed = {m.name for m in dataclasses.fields(member_cls)}
                kwargs[f.name] = member_cls(**{k: v for k, v in value.items() if k in allowed})
            else:
                kwargs[f.name] = value
        return result_cls(**kwargs)
    except Exception:      # noqa: BLE001 — any malformed shape is "no result"
        return None


def restore_enrichment_reading(payload: dict) -> dict:
    """A copy of `payload` whose enrichment result is a single reading (D-84).

    Files saved while the panel compared two readings hold both
    ({"title_only": ..., "enriched": ...}). The panel now shows only the
    About-informed one, so that half is what is restored. Read as one
    Classification directly, a two-reading result matches no field and would
    rebuild as an empty reading that looks like a real one.
    """
    enrichment = payload.get("enrichment")
    result = enrichment.get("result") if isinstance(enrichment, dict) else None
    if isinstance(result, dict) and isinstance(result.get("enriched"), dict):
        return {**payload, "enrichment": {**enrichment, "result": result["enriched"]}}
    return payload


def restore(
    payload: dict,
    df: pd.DataFrame,
    *,
    result_cls: Any = None,
    member_cls: Any = None,
) -> tuple[dict[int, str], dict[int, str], dict[str, Any], RestoreReport]:
    """Translate a save file onto the CURRENT table.

    Returns (corrections, notes, enrichment, report). Nothing is written here —
    the caller puts these into session state, so this stays pure and testable.
    """
    if not isinstance(payload, dict):
        raise ValueError("that file is not a session file")

    version = payload.get("format_version")
    if not isinstance(version, int):
        raise ValueError("that file has no format_version and cannot be read")
    if version > FORMAT_VERSION:
        raise UnsupportedVersion(
            f"that file was saved by a newer version (format {version}; this "
            f"build reads {FORMAT_VERSION}). Nothing has been changed."
        )

    by_person, by_name = _index_tables(df)
    misses: list[Miss] = []
    drifts: list[Drift] = []

    corrections: dict[int, str] = {}
    saved_corrections = payload.get("corrections") or []
    for entry in saved_corrections:
        if not isinstance(entry, dict):
            continue
        label = str(entry.get("name", "")).strip() or "(unnamed)"
        hits = by_person.get(person_key(entry.get("name"), entry.get("role")), [])
        if len(hits) == 1:
            corrections[hits[0]] = str(entry.get("soc_major", ""))
        elif len(hits) > 1:
            misses.append(Miss(label, MISS_DUPLICATE, "correction"))
        else:
            # Distinguish "gone" from "renamed": the second is the common case
            # after a promotion and the user should be told which happened.
            reason = (
                MISS_TITLE_CHANGED
                if by_name.get(name_key(entry.get("name")))
                else MISS_NO_MATCH
            )
            misses.append(Miss(label, reason, "correction"))

    notes: dict[int, str] = {}
    saved_notes = payload.get("notes") or []
    current_role = {int(r[INDEX_COLUMN]): str(r.get(ROLE_COLUMN, "")) for _, r in df.iterrows()}
    for entry in saved_notes:
        if not isinstance(entry, dict):
            continue
        label = str(entry.get("name", "")).strip() or "(unnamed)"
        text = str(entry.get("text", "")).strip()
        if not text:
            continue
        hits = by_name.get(name_key(entry.get("name")), [])
        if len(hits) == 1:
            index = hits[0]
            notes[index] = text
            was, now_role = str(entry.get("role", "")), current_role.get(index, "")
            if _collapse(was) != _collapse(now_role):
                drifts.append(Drift(index, label, was, now_role))
        elif len(hits) > 1:
            misses.append(Miss(label, MISS_DUPLICATE, "note"))
        else:
            misses.append(Miss(label, MISS_NO_MATCH, "note"))

    raw_enrichment = payload.get("enrichment") or {}
    enrichment: dict[str, Any] = {}
    if isinstance(raw_enrichment, dict):
        if raw_enrichment.get("title") or raw_enrichment.get("about"):
            enrichment["title"] = str(raw_enrichment.get("title", ""))
            enrichment["about"] = str(raw_enrichment.get("about", ""))
        rebuilt = load_result(raw_enrichment.get("result"), result_cls, member_cls)
        if rebuilt is not None:
            enrichment["result"] = rebuilt
            enrichment["generated_at"] = str(raw_enrichment.get("generated_at", ""))

    report = RestoreReport(
        corrections_applied=len(corrections),
        corrections_total=len([e for e in saved_corrections if isinstance(e, dict)]),
        notes_applied=len(notes),
        notes_total=len(
            [e for e in saved_notes if isinstance(e, dict) and str(e.get("text", "")).strip()]
        ),
        enrichment_restored="result" in enrichment or "title" in enrichment,
        misses=tuple(misses),
        drifts=tuple(drifts),
    )
    return corrections, notes, enrichment, report


# --- glue --------------------------------------------------------------------

PRIVACY_NOTE = (
    "The file holds your corrections, your notes about named people, and your "
    "own profile text. It is saved straight to your computer — nothing is sent "
    "anywhere or kept on a server. Anyone you share the file with can read "
    "what you wrote about your connections."
)

RESTORE_HEADING = "Save or restore your work"
UPLOAD_LABEL = "Restore a saved session"

STALE_RESULT_NOTE = (
    "The comparison below was generated on {when} and restored from your file. "
    "Run it again for a fresh reading."
)

KEY_UPLOAD = "session_io_upload"
KEY_REPORT = "session_io_report"
KEY_APPLIED = "session_io_applied_file"


def download_session_button(st, df: pd.DataFrame, key: str) -> None:
    """The one download control, wherever it appears. `key` because the panel,
    the unsaved-work prompt and the expiry warning can all be on one screen,
    and Streamlit refuses two identical widgets without one."""
    from src.dashboard.enrich import KEY_ABOUT, KEY_RESULT, KEY_TITLE
    from src.dashboard.lifetime import record_download
    from src.dashboard.notes import get_notes
    from src.dashboard.state import get_corrections

    payload = build_export(
        df,
        get_corrections(),
        get_notes(),
        title=st.session_state.get(KEY_TITLE, ""),
        about=st.session_state.get(KEY_ABOUT, ""),
        result=st.session_state.get(KEY_RESULT),
    )
    st.download_button(
        "Download this session",
        data=to_json(payload),
        file_name=export_filename(),
        mime="application/json",
        use_container_width=True,
        key=key,
        on_click=record_download,
    )


def render_session_io(df: pd.DataFrame) -> None:
    """Download and upload controls. MUST render above render_enrichment_panel().

    enrich.py binds its title and About boxes directly to widget keys, and
    Streamlit forbids writing a widget key after its widget exists. Restoring
    from below the panel raises StreamlitAPIException.
    """
    import streamlit as st

    # expanded=True: this is the one control a user must find on every visit.
    # Collapsed, it reads as an advanced option and the session's work is lost.
    with st.sidebar.expander(RESTORE_HEADING, expanded=True):
        download_session_button(st, df, key="download_session")
        st.caption(PRIVACY_NOTE)

        uploaded = st.file_uploader(UPLOAD_LABEL, type="json", key=KEY_UPLOAD)
        marker = getattr(uploaded, "file_id", None) or (
            (uploaded.name, uploaded.size) if uploaded is not None else None
        )
        if uploaded is not None and st.session_state.get(KEY_APPLIED) != marker:
            st.session_state[KEY_APPLIED] = marker
            _apply_upload(st, uploaded, df)
            st.rerun()

        report = st.session_state.get(KEY_REPORT)
        if isinstance(report, RestoreReport):
            _render_report(st, report)


def _apply_upload(st, uploaded, df: pd.DataFrame) -> None:
    """Parse, match, and write into the same session dicts the user's own
    clicks write into. Nothing here knows about frame assembly (D5)."""
    from src.dashboard.notes import NOTES_KEY
    from src.dashboard.state import CORRECTIONS_KEY
    from src.dashboard.enrich import KEY_ABOUT, KEY_RESULT, KEY_TITLE
    from src.onet import Classification

    try:
        payload = json.loads(uploaded.getvalue().decode("utf-8"))
    except Exception:                       # noqa: BLE001
        st.error("That file could not be read as a session file.")
        return

    try:
        corrections, notes, enrichment, report = restore(
            restore_enrichment_reading(payload), df,
            result_cls=Classification, member_cls=None,
        )
    except UnsupportedVersion as exc:
        st.error(str(exc))
        return
    except ValueError as exc:
        st.error(str(exc))
        return

    st.session_state.setdefault(CORRECTIONS_KEY, {}).update(corrections)
    st.session_state.setdefault(NOTES_KEY, {}).update(notes)
    if "title" in enrichment:
        st.session_state[KEY_TITLE] = enrichment["title"]
        st.session_state[KEY_ABOUT] = enrichment["about"]
    if "result" in enrichment:
        st.session_state[KEY_RESULT] = enrichment["result"]

    st.session_state[KEY_REPORT] = report
    # NO st.rerun() here. It halts immediately, so anything the caller does
    # after this call never runs — including the guard that stops the file
    # being re-applied on the next pass. The caller reruns, after the guard.


DISMISS_KEY = "session_io_dismiss"


def _render_report(st, report: RestoreReport) -> None:
    st.success(report.sentence())

    # Drift first, and framed as KEPT: these notes were re-applied. Rendered
    # after a "not re-applied" block they read as further failures, and the
    # user counts them into the miss total (D-27).
    if report.drifts:
        with st.container(border=True):
            noun = "note" if len(report.drifts) == 1 else "notes"
            st.caption(f"**{len(report.drifts)} {noun} kept, title since changed**")
            for drift in report.drifts:
                st.caption(
                    f"{drift.label} — your note was written when they were "
                    f"“{drift.was}”; they are now “{drift.now}”."
                )

    for kind, plural in (("correction", "corrections"), ("note", "notes")):
        missed = [m for m in report.misses if m.kind == kind]
        if not missed:
            continue
        with st.container(border=True):
            noun = kind if len(missed) == 1 else plural
            st.caption(f"**{len(missed)} {noun} not re-applied**")
            for miss in missed:
                # The kind is in the heading now, so it is not repeated per line.
                st.caption(f"{miss.label} — {miss.reason}")

    if st.button("Dismiss", key=DISMISS_KEY, use_container_width=True):
        # KEY_REPORT is a plain state key, not a widget key, so this write is
        # unrestricted. Terminates after one pass: the report is gone, so the
        # button does not render, so this branch cannot re-enter. KEY_UPLOAD
        # and KEY_APPLIED are deliberately untouched — clearing KEY_APPLIED
        # while the file is still attached would re-apply it immediately.
        st.session_state.pop(KEY_REPORT, None)
        st.rerun()