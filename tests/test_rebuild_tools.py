"""tests/test_rebuild_tools.py - diff_rebuild and audit_title_churn (D-40).

Both used to hard-code a gitignored snapshot path and crashed with a bare
FileNotFoundError on a clean checkout. They now take the snapshot as --old.
Fixtures are invented people; nothing here reads real data.
"""
from __future__ import annotations

import pandas as pd
import pytest

from tools import audit_title_churn, diff_rebuild


def _table(path, rows):
    pd.DataFrame(rows, columns=["name", "role", "soc_major", "is_uncertain"]).to_csv(path, index=False)
    return str(path)


BEFORE = [("Ada Byron", "Analyst", "13", False),
          ("Alan Stone", "Engineer", "17", False),
          ("Grace Holt", "Nurse", "29", False)]


@pytest.mark.parametrize("tool", [diff_rebuild, audit_title_churn])
def test_old_is_required(tool):
    with pytest.raises(SystemExit) as exc:
        tool.main([])
    assert exc.value.code == 2  # argparse: missing required argument


@pytest.mark.parametrize("tool", [diff_rebuild, audit_title_churn])
def test_missing_snapshot_is_a_clear_message_not_a_traceback(tool, tmp_path):
    new = _table(tmp_path / "new.csv", BEFORE)
    with pytest.raises(SystemExit) as exc:
        tool.main(["--old", str(tmp_path / "absent.csv"), "--new", new])
    assert "not found" in str(exc.value.code) and "--old" in str(exc.value.code)


def test_diff_rebuild_reports_zero_reclassified_for_a_stable_rebuild(tmp_path, capsys):
    old = _table(tmp_path / "old.csv", BEFORE)
    new = _table(tmp_path / "new.csv", BEFORE[:2] + [("Lin Park", "Chef", "35", False)])
    assert diff_rebuild.main(["--old", old, "--new", new]) == 0
    out = capsys.readouterr().out
    assert "reclassified : 0" in out
    assert "left network : 1" in out and "joined       : 1" in out


def test_diff_rebuild_flags_a_settled_title_that_moved(tmp_path, capsys):
    old = _table(tmp_path / "old.csv", BEFORE)
    moved = [("Ada Byron", "Analyst", "15", False)] + BEFORE[1:]
    new = _table(tmp_path / "new.csv", moved)
    diff_rebuild.main(["--old", old, "--new", new])
    assert "reclassified : 1" in capsys.readouterr().out


def test_audit_counts_a_retitled_person_as_still_present(tmp_path, capsys):
    old = _table(tmp_path / "old.csv", BEFORE)
    retitled = [("Ada Byron", "Senior Analyst", "13", False)] + BEFORE[1:2]
    new = _table(tmp_path / "new.csv", retitled)
    assert audit_title_churn.main(["--old", old, "--new", new]) == 0
    out = capsys.readouterr().out
    assert "corrections a restore would drop : 2" in out
    assert "...of people still in the network: 1" in out
    assert "...of people who genuinely left  : 1" in out
