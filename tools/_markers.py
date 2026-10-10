"""tools/_markers.py - shared parsing for `# <tag>: <reason>` exemption markers.

Two checkers let a site opt out with a reasoned comment at the site itself:

    tools/check_single_loader.py    # loader-exempt: <reason>
    tools/sweep_count_surfaces.py   # count-exempt: <reason>

Both parse markers here, identically. They APPLY them differently, on purpose,
because they detect different things (D-39):

  loader-exempt  covers only its own line. That checker scans lines of text
                 for a data-path name, so the offence is a line.
  count-exempt   covers the line above a construction, or any line it spans.
                 That checker finds AST nodes (f-strings), which can span
                 several lines, so the marker goes wherever reads best.

A marker placed where its checker does not look simply does not exempt, so a
misplaced marker fails the check rather than passing it.
"""
from __future__ import annotations

import io
import re
import tokenize


def comment_markers(text: str, tag: str) -> dict[int, str]:
    """Line number -> reason, for every `# <tag>: <reason>` comment in `text`.

    tokenize rather than a line scan: a '#' inside a string literal is not a
    comment, and this repo names data paths and writes prompt prose inside
    strings. Source that fails to tokenize returns the markers found before
    the failure; both callers report parse failures themselves.
    """
    pattern = re.compile(rf"#\s*{re.escape(tag)}:\s*(\S.*?)\s*$")
    found: dict[int, str] = {}
    try:
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.type == tokenize.COMMENT:
                match = pattern.search(token.string)
                if match:
                    found[token.start[0]] = match.group(1)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    return found
