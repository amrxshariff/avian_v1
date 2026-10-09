"""
src/dashboard/upload.py — P2.9b: bring your own network.

The whole path from "here is my Connections.csv" to a network on screen,
without a key and without spending anything. The build runs with
classify=False, so everyone arrives in the fourth state: placed, connected,
and ungrouped, with the groups arriving later when a key does.

That is only possible because of option B. If a failed classification meant a
failed build, there would be nothing to show anyone until they had pasted a
key — and asking a stranger for an API key before showing them anything is a
poor trade for them and a worse one for us.

What this module refuses to do
------------------------------
Write the upload anywhere. Streamlit hands over a file-like object in memory
and it stays that way: parsed from its bytes, built into a frame, held in
session state, gone when the session ends. A temporary file would put someone
else's connections on a shared disk to satisfy a function signature.
"""

from __future__ import annotations

from typing import Callable, Optional

MAX_UPLOAD_MB = 10

UPLOAD_HELP = (
    "LinkedIn > Settings > Data privacy > Get a copy of your data > "
    "Connections. The file stays in this session: it is never saved, and it is "
    "gone when you close the tab."
)

KEYLESS_NOTE = (
    "Built without a classifier, so nobody has a group yet. Everything else is "
    "real: these are your connections, placed by how similar their titles are."
)

CLASSIFIED_TAIL = (
    "Anyone the classifier could not place is marked as such rather than "
    "guessed at."
)


def classified_note(result) -> str:
    """The note after a classified build, naming whose key paid only when known.

    It used to say "Classified with your key" whenever any key was present,
    which told a visitor who had pasted nothing that their key paid for a
    build the project's key paid for (D-83). The words now come from the same
    place as the provenance line, over the build's own recorded source.
    """
    from src.dashboard.provenance import whose_key

    whose = whose_key(getattr(result, "provenance", None) or {})
    lead = f"Classified using {whose}." if whose else "Classified."
    return f"{lead} {CLASSIFIED_TAIL}"


def intake_note(result) -> str:
    """What the file held versus what was used, in one line.

    An export of 456 rows that becomes 442 people invites the question of
    where the other 14 went, and "cleaned automatically" is not an answer.
    Silence about skipped rows is how a user comes to distrust a count.
    """
    intake = (getattr(result, "provenance", None) or {}).get("intake") or {}
    if not intake:
        return ""

    parts = []
    skipped = (intake.get("dropped_no_name", 0)
               + intake.get("dropped_no_role_or_company", 0))
    if skipped:
        parts.append(
            f"{skipped} row(s) skipped: no name, or no position and no company"
        )
    if intake.get("blank_rows"):
        parts.append(f"{intake['blank_rows']} blank row(s) ignored")
    discarded = intake.get("columns_discarded") or []
    if discarded:
        parts.append(f"columns not read: {', '.join(discarded)}")
    return ". ".join(parts) + "." if parts else ""


def _row_estimate(upload) -> Optional[int]:
    """Roughly how many rows the upload holds, without parsing it.

    Counting newlines on the bytes we already have costs nothing and is close
    enough for a warning. The exact figure comes from the parse.
    """
    try:
        position = upload.tell() if hasattr(upload, "tell") else None
        upload.seek(0)
        data = upload.read()
        upload.seek(position or 0)
    except Exception:      # noqa: BLE001 — a warning is never worth an error
        return None
    if not isinstance(data, bytes):
        return None
    return max(0, data.count(b"\n") - 1)


def _too_big(upload) -> bool:
    size = getattr(upload, "size", None)
    return size is not None and size > MAX_UPLOAD_MB * 1024 * 1024


KEY_SECTION_LABEL = "Add an API key for occupation groups"


def _key_section(st, store, on_key, *, boxed: bool = True) -> None:
    """The key field, in an expander so it reads as optional.

    Rendered on both sides of the built/not-built fork, because the case that
    most needs it is a keyless build already on screen. Never above the
    uploader: a public page asking for an API key before it has shown anything
    reads as phishing, whatever the help text says.

    `boxed=False` when the caller has already put the panel in an expander —
    the sidebar's "Your network". That is the same affordance one level up,
    and Streamlit refuses an expander inside another (D-66), so the label
    becomes a caption over the field.
    """
    from src.dashboard.key_field import render_key_field
    from src.dashboard.keys import KEY_NONE, key_source

    if not boxed:
        st.caption(KEY_SECTION_LABEL)
        render_key_field(st=st, store=store, on_validated=on_key)
        return

    held = key_source(store) != KEY_NONE
    with st.expander(KEY_SECTION_LABEL, expanded=not held):
        render_key_field(st=st, store=store, on_validated=on_key)


def render_upload_panel(
    *,
    st=None,
    build_fn: Optional[Callable] = None,
    store: Optional[dict] = None,
    on_built: Optional[Callable] = None,
    on_key: Optional[Callable] = None,
    boxed: bool = True,
) -> Optional[object]:
    """Draw the uploader, build what is dropped on it, and hold the result.

    Returns the BuildResult when this run produced one, else None.

    `boxed=False` from a caller that has already wrapped the panel in an
    expander, so the key field does not open a second one inside it (D-66).

    `on_key` becomes the key field's `on_validated`, and runs inside its
    on_change callback: never st.rerun (D-67). render_key_field says what a
    valid use looks like.

    `build_fn` and `store` are injected for tests, and `on_built` is how the
    app asks for a rerun without this module importing Streamlit's control
    flow. The panel itself knows nothing about the rest of the page.
    """
    if st is None:
        import streamlit as st  # noqa: PLC0415 — lazy, as everywhere in dashboard/

    from src.build import InvalidExport, MAX_PEOPLE, WARN_PEOPLE, build_network
    from src.dashboard.keys import KEY_NONE, key_source
    from src.dashboard.metering import meters_for
    from src.dashboard.session_build import (
        classification_cache, clear_built, get_built, set_built,
    )

    built = get_built(store)

    if built is not None:
        st.caption(f"Your network: {built.people} people.")
        _key_section(st, store, on_key, boxed=boxed)
        if st.button("Use the demo instead", key="clear_built"):
            clear_built(store)
            if on_built is not None:
                on_built()
        return None

    upload = st.file_uploader(
        "Build from your own LinkedIn export",
        type="csv",
        help=UPLOAD_HELP,
        key="connections_upload",
    )
    _key_section(st, store, on_key, boxed=boxed)
    if upload is None:
        return None

    if _too_big(upload):
        st.error(
            f"That file is larger than {MAX_UPLOAD_MB} MB. A connections "
            "export of a few thousand people is well under 1 MB, so this is "
            "probably not one."
        )
        return None

    builder = build_fn or build_network
    rows = _row_estimate(upload)
    if rows is not None and rows > WARN_PEOPLE:
        # Not a refusal: there is no measured ceiling, so this says what is
        # known rather than pretending to a limit. Running out of memory kills
        # the container, which takes the app down for everyone on it.
        st.warning(
            f"That looks like about {rows:,} rows. The largest network "
            f"measured on this host is {WARN_PEOPLE:,}, so this build may run "
            "out of memory and restart the app."
        )

    # Read here, not earlier: the key field above may have stored a key during
    # this same run, and a build that ignored it would silently produce the
    # fourth state for someone who had just paid to avoid it.
    has_key = key_source(store) != KEY_NONE
    try:
        with st.spinner("Reading your connections and placing them..."):
            # The session's own cache, never the shared file (D-71): this
            # export's titles are real people's.
            # Metered on the project key (D-81): without this the $5 and $30
            # caps, and the pre-flight refusal, never ran for anyone.
            result = builder(upload, classify=has_key, source=key_source(store),
                             cache_path=classification_cache(store),
                             meters=meters_for(key_source(store)))
    except InvalidExport as exc:
        # The message is written for the person holding the file, so it is
        # shown as it is rather than wrapped in an apology.
        st.error(str(exc))
        return None

    # Whatever was on screen before — the demo, usually — had different
    # people at these indices. Its corrections, notes and the pending offer
    # go with it (D-65); clear_built is what does that.
    clear_built(store)
    set_built(result, store)
    st.success(f"{result.people} connections placed.")
    note = intake_note(result)
    if note:
        st.caption(note)
    st.caption(classified_note(result) if has_key else KEYLESS_NOTE)
    if on_built is not None:
        on_built()
    return result
