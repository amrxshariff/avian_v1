"""tests/test_remeasure_config_e.py - the D-47 remeasurement, offline (no API).

Invented titles and labels; nothing here reads the real evaluation set.
"""
from __future__ import annotations

import json

import pandas as pd
import pytest

from src.claude_classifier import _cache_key
from tools import remeasure_config_e as rm


@pytest.fixture
def files(tmp_path):
    gold = pd.DataFrame({"title": ["Auditor", "Nurse", "Member", "Welder"],
                         "soc_major_group": ["13", "29", "99", "51"]})
    gold.to_csv(tmp_path / "labels.csv", index=False)
    # The bake-off as recorded: Nurse and Member padded (no prediction).
    report = pd.DataFrame({"config": [rm.CONFIG_E] * 4 + ["A deterministic"],
                           "title": ["Auditor", "Nurse", "Member", "Welder", "Auditor"],
                           "gold": ["13", "29", "99", "51", "13"],
                           "pred": ["13", None, None, "47", "13"],
                           "outcome": ["correct", "missed", "correct_abstain", "wrong", "correct"]})
    report.to_csv(tmp_path / "report.csv", index=False)
    # The cache after the purge: Nurse re-classified; Member now answered wrongly.
    cache = {_cache_key("Auditor", ""): {"soc": "13", "confidence": "high", "why": "x"},
             _cache_key("Nurse", ""): {"soc": "29", "confidence": "high", "why": "x"},
             _cache_key("Member", ""): {"soc": "11", "confidence": "medium", "why": "x"},
             _cache_key("Welder", ""): {"soc": "47", "confidence": "high", "why": "x"}}
    (tmp_path / "cache.json").write_text(json.dumps(cache), encoding="utf-8")
    return ["--labels", str(tmp_path / "labels.csv"), "--report", str(tmp_path / "report.csv"),
            "--cache", str(tmp_path / "cache.json")]


def test_reports_both_measurements_and_every_transition(files, capsys):
    assert rm.main(files) == 0
    out = capsys.readouterr().out
    assert "2 title(s) changed prediction (0 of them re-sampled via the API)" in out
    assert "missed -> correct" in out
    assert "correct_abstain -> FABRICATED" in out


def test_refuses_to_call_the_api_unless_allowed(files, tmp_path, capsys):
    (tmp_path / "cache.json").write_text("{}", encoding="utf-8")
    assert rm.main(files) == 2
    assert "Nothing was measured" in capsys.readouterr().out


def test_missing_report_is_a_plain_message(files, tmp_path):
    (tmp_path / "report.csv").unlink()
    with pytest.raises(SystemExit, match="bake-off report not found"):
        rm.main(files)
