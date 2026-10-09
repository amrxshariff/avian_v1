from __future__ import annotations

import html

import plotly.express as px
import plotly.graph_objects as go
import pandas as pd

from src.onet import MAJOR_GROUP_NAMES
from src.dashboard.state import (
    STATE_CLASSIFIED,
    STATE_NEEDS_REVIEW,
    STATE_NOT_CLASSIFIED,
    STATE_NOT_OCCUPATION,
    require_known_state,
)

# --- palette -----------------------------------------------------------------

# 23 SOC major groups -> 24-colour qualitative palette, assigned in sorted code
# order so the mapping is stable and reproducible across every render and every
# user's network. Built from the taxonomy (MAJOR_GROUP_NAMES), never from the
# data present, so a group that nobody currently holds still has its colour ready.
_PALETTE = px.colors.qualitative.Dark24  # 24 saturated hues
SOC_COLOURS: dict[str, str] = {
    code: _PALETTE[i] for i, code in enumerate(sorted(MAJOR_GROUP_NAMES))
}

# Neutral greys, deliberately desaturated and low-chroma so no Dark24 hue is
# near them. Lighter = unreviewed (still needs a human); darker = resolved as
# not-an-occupation (a human looked and there is no job here).
NEEDS_REVIEW_GREY = "#9AA0A6"
NOT_OCCUPATION_GREY = "#5F6368"

# P2.9b's fourth state. It needs to be distinguishable from the two resolved
# greys without reading as a group colour, so it carries both a darker slate
# and its own shape.
#
# It was an OPEN circle first, on the reasoning that a hollow marker reads as
# an empty slot — which is exactly what the state means. Plotly's 3D renderer
# draws "circle-open" as nothing at all: the points were in the figure and
# hoverable the whole time, invisible at every colour and size we tried. A
# filled diamond is the nearest shape that actually renders.
NOT_CLASSIFIED_GREY = "#48525E"
MARKER_SYMBOL = "circle"
NOT_CLASSIFIED_SYMBOL = "diamond"
NOT_CLASSIFIED_SIZE_BONUS = 2

# Marker geometry. Uncertain nodes are NOT shrunk or faded in the default view —
# they must stay as visible as classified ones (P2.1). The only size variation
# is the highlight ring and the small bump given to search matches.
BASE_MARKER_SIZE = 4
MATCH_MARKER_SIZE = 5
HIGHLIGHT_MARKER_SIZE = 9

# Opacity for the two-trace search view. Matched nodes stay at the default;
# everything else fades so the match set pops out of the cloud. Kept as scalar
# per-trace opacity (reliable on Scatter3d) rather than per-point rgba alpha
# (which renders inconsistently in 3D).
FULL_OPACITY = 0.9
FADED_OPACITY = 0.12

REQUIRED_COLUMNS = (
    "person_index", "name", "role", "soc_major", "soc_major_name",
    "display_state", "umap_3d_x", "umap_3d_y", "umap_3d_z",
)

_HOVER = (
    "<b>%{customdata[1]}</b><br>"
    "%{customdata[2]}<br>"
    "<i>%{customdata[3]}</i>"
    "<extra></extra>"
)

# --- selected-node label (P2.5 DoD-8) ----------------------------------------

# Scene annotations are drawn in the SVG overlay layer above the WebGL canvas,
# so the label cannot be occluded by markers sitting in front of the selected
# node. A text trace would be occluded — which is the whole reason this is an
# annotation and not another Scatter3d.
LABEL_OFFSET_Y = -46          # pixels above the node; leader line spans the gap
LABEL_MAX_CHARS = 26          # truncate long titles rather than let them sprawl
GROUP_LABEL_FONT_SIZE = 12    # group labels sit behind the node label in weight


def _truncate(text: str, limit: int = LABEL_MAX_CHARS) -> str:
    text = str(text or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _selection_annotation(row: pd.Series) -> dict:
    """A scene annotation naming the selected node, anchored at its coordinates.

    Name and role are HTML-escaped: they come from a user-supplied CSV and
    Plotly renders a subset of HTML in annotation text, so an unescaped '&' or
    '<' in a job title would corrupt the label.

    # Known limitation: near the plot edge the box can clip. The annotation's
    # screen position is computed client-side from the camera, so Python
    # cannot detect the case and flip the offset inward. Margins mitigate;
    # rotation resolves it.
    """
    name = html.escape(_truncate(row.get("name", "")))
    role = html.escape(_truncate(row.get("role", "")))
    text = f"<b>{name}</b>" + (f"<br>{role}" if role else "")
    return dict(
        x=float(row["umap_3d_x"]),
        y=float(row["umap_3d_y"]),
        z=float(row["umap_3d_z"]),
        text=text,
        showarrow=True,
        arrowhead=0,
        arrowwidth=1,
        arrowcolor="rgba(32,33,36,0.55)",
        ax=0,
        ay=LABEL_OFFSET_Y,
        font=dict(size=11, color="#202124"),
        bgcolor="rgba(255,255,255,0.88)",
        bordercolor="rgba(32,33,36,0.25)",
        borderwidth=1,
        borderpad=4,
        align="left",
    )


def _group_annotations(df: pd.DataFrame, codes: set[str]) -> list[dict]:
    """One label per selected group, anchored at the centroid of its members.

    Computed from the FULL frame, not the match set, so a group stays labelled
    while a search narrows what is lit inside it — that is what "outer group
    labels remain visible" asks for (P2.6a DoD-2).

    # Known limitation: the centroid of a group split across two regions of the
    # projection lands between them, in empty space. UMAP does not guarantee a
    # group is contiguous. Acceptable at group granularity; if it proves
    # distracting, the fix is the largest connected component, not the mean.
    """
    out: list[dict] = []
    for code in sorted(codes):
        members = df[df["soc_major"].astype(str) == str(code)]
        if members.empty:          # a group nobody in this network holds
            continue
        colour = SOC_COLOURS.get(str(code), "#202124")
        out.append(dict(
            x=float(members["umap_3d_x"].mean()),
            y=float(members["umap_3d_y"].mean()),
            z=float(members["umap_3d_z"].mean()),
            text=f"<b>{html.escape(MAJOR_GROUP_NAMES.get(str(code), str(code)))}</b>",
            showarrow=False,
            # Label carries its group's hue in text and border, so the mapping
            # from label to cluster is readable without a legend. Bg stays near
            # opaque white — Dark24 is uniformly dark, but a saturated hue on a
            # translucent panel over a dense point cloud loses contrast.
            font=dict(size=GROUP_LABEL_FONT_SIZE, color=colour),
            bgcolor="rgba(255,255,255,0.92)",
            bordercolor=colour,
            borderwidth=1,
            borderpad=3,
        ))
    return out


def _point_colour(row: pd.Series) -> str:
    """Colour for one node: grey for the three unresolved states, else its hue.

    Exhaustive over ALL_STATES (D-54). There is no trailing `else` meaning
    "probably classified": an unknown state raises rather than borrowing the
    needs-review grey, which is what this function used to do.
    """
    state = require_known_state(row["display_state"])
    if state == STATE_NEEDS_REVIEW:
        return NEEDS_REVIEW_GREY
    if state == STATE_NOT_OCCUPATION:
        return NOT_OCCUPATION_GREY
    if state == STATE_NOT_CLASSIFIED:
        return NOT_CLASSIFIED_GREY
    # STATE_CLASSIFIED: soc_major is one of the 23 real codes. The fallback
    # guards a malformed row rather than inventing a hue.
    assert state == STATE_CLASSIFIED
    return SOC_COLOURS.get(str(row["soc_major"]), NEEDS_REVIEW_GREY)


def _point_size(row: pd.Series, base: int) -> int:
    """An open ring needs a larger radius to carry the same weight as a disc."""
    if require_known_state(row["display_state"]) == STATE_NOT_CLASSIFIED:
        return base + NOT_CLASSIFIED_SIZE_BONUS
    return base


def _point_symbol(row: pd.Series) -> str:
    """Open circle for a person the classifier never answered for, else solid."""
    if require_known_state(row["display_state"]) == STATE_NOT_CLASSIFIED:
        return NOT_CLASSIFIED_SYMBOL
    return MARKER_SYMBOL


def _node_trace(sub: pd.DataFrame, opacity: float, size: int,
                name: str, hover: bool = True) -> go.Scatter3d:
    """A markers trace for a subset of nodes at a given opacity/size.

    Factored out so the plain view (one call) and the search view (a faded
    'other' trace under a full 'matches' trace) share identical marker config,
    hover, and customdata — only opacity, size, and hover differ.
    """
    colours = sub.apply(_point_colour, axis=1).tolist()
    symbols = sub.apply(_point_symbol, axis=1).tolist()
    sizes = sub.apply(_point_size, axis=1, base=size).tolist()
    hover_kwargs = dict(hovertemplate=_HOVER) if hover else dict(hoverinfo="skip")
    return go.Scatter3d(
        x=sub["umap_3d_x"], y=sub["umap_3d_y"], z=sub["umap_3d_z"],
        mode="markers",
        marker=dict(
            size=sizes,
            color=colours,
            symbol=symbols,
            line=dict(width=0.5, color="rgba(255,255,255,0.4)"),
            opacity=opacity,
        ),
        customdata=sub[["person_index", "name", "role", "soc_major_name"]].to_numpy(),
        name=name,
        showlegend=False,
        **hover_kwargs,
    )


def build_figure(df: pd.DataFrame,
                 highlight_index: int | None = None,
                 match_indices: set[int] | None = None,
                 label_groups: set[str] | None = None) -> go.Figure:
    """Return the 3D network figure for `df` (the corrected display table).

    match_indices: person_index values matched by the current search. When it is
    None or empty, the whole network renders at full opacity (unfiltered view).
    When it is a non-empty set, matched nodes render full while every other node
    fades to FADED_OPACITY, so a broad search ("finance", "computer") lights the
    whole group in place rather than a single node.

    highlight_index: person_index of the ONE node the list panel has selected,
    drawn larger with a dark ring and carrying a scene annotation naming the
    person, so the user can pinpoint their selection — including within a lit
    match set. None draws no ring and no label.

    The axes are hidden because UMAP coordinates have no interpretable scale —
    only relative position carries meaning.
    """
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise KeyError(
            f"build_figure requires {missing} — did app.py merge the 3D sidecar "
            "into the display table before calling?"
        )

    # None = no filter active. An EMPTY set = a filter is active and nothing
    # satisfies it, which must fade the network rather than un-fade it. The
    # distinction is why this tests `is not None` and not truthiness.
    match_set = {int(i) for i in match_indices} if match_indices is not None else None

    if match_set is not None:
        is_match = df["person_index"].astype(int).isin(match_set)
        faded, matched = df[~is_match], df[is_match]
        traces: list[go.Scatter3d] = []
        if not faded.empty:
            traces.append(_node_trace(faded, FADED_OPACITY, BASE_MARKER_SIZE, "other", hover=False))
        if not matched.empty:
            traces.append(_node_trace(matched, FULL_OPACITY, MATCH_MARKER_SIZE, "matches"))
    else:
        traces = [_node_trace(df, FULL_OPACITY, BASE_MARKER_SIZE, "network")]

    annotations: list[dict] = _group_annotations(df, label_groups) if label_groups else []
    if highlight_index is not None:
        sel = df[df["person_index"] == int(highlight_index)]
        if not sel.empty:
            r = sel.iloc[0]
            traces.append(go.Scatter3d(
                x=[r["umap_3d_x"]], y=[r["umap_3d_y"]], z=[r["umap_3d_z"]],
                mode="markers",
                marker=dict(
                    size=HIGHLIGHT_MARKER_SIZE,
                    color=_point_colour(r),
                    symbol=_point_symbol(r),
                    line=dict(width=3, color="rgba(20,20,20,0.9)"),
                    opacity=1.0,
                ),
                hoverinfo="skip",
                name="selected",
                showlegend=False,
            ))
            annotations.append(_selection_annotation(r))

    _hidden_axis = dict(
        showgrid=False, zeroline=False, showticklabels=False,
        title="", showbackground=False, showspikes=False,
    )
    fig = go.Figure(data=traces)
    fig.update_layout(
        scene=dict(xaxis=_hidden_axis, yaxis=_hidden_axis, zaxis=_hidden_axis,
                   aspectmode="data", annotations=annotations),
        margin=dict(l=48, r=48, t=40, b=16),
        showlegend=False,
    )
    return fig
