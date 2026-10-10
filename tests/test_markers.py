"""tests/test_markers.py - the shared exemption-marker parser (D-39)."""
from tools._markers import comment_markers


def test_marker_and_reason_are_read():
    src = "x = 1  # loader-exempt: reads the sidecar directly\n"
    assert comment_markers(src, "loader-exempt") == {1: "reads the sidecar directly"}


def test_a_hash_inside_a_string_is_not_a_marker():
    src = 's = "# loader-exempt: not a comment"\n'
    assert comment_markers(src, "loader-exempt") == {}


def test_tags_do_not_cross():
    src = "a = 1  # count-exempt: guarded\nb = 2  # loader-exempt: sidecar\n"
    assert comment_markers(src, "count-exempt") == {1: "guarded"}
    assert comment_markers(src, "loader-exempt") == {2: "sidecar"}


def test_a_marker_needs_a_reason():
    assert comment_markers("x = 1  # loader-exempt:\n", "loader-exempt") == {}


def test_unparseable_source_returns_what_was_found():
    src = "a = 1  # count-exempt: ok\nb = (\n"
    assert comment_markers(src, "count-exempt") == {1: "ok"}
