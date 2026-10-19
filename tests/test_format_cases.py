"""The format cases the web app shares with Python (#294 R7, ADR 0004 point 5).

``tests/fixtures/format-cases.json`` lists how ``web/src/lib/format.ts`` writes
numbers; Vitest checks every case there (``web/src/lib/format.test.ts``). A case
naming a Python formatter is checked here too, so the results card and the pit wall
never show the same lap differently.
"""

from __future__ import annotations

import importlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

CASES_FILE = Path(__file__).parent / "fixtures" / "format-cases.json"
CASES: list[dict[str, Any]] = json.loads(CASES_FILE.read_text(encoding="utf-8"))["cases"]
PYTHON = [c for c in CASES if c.get("python")]


def formatter(dotted: str) -> Callable[..., Any]:
    """``results.race_time`` -> those_who_run.results.race_time."""
    module, name = dotted.rsplit(".", 1)
    return getattr(importlib.import_module(f"those_who_run.{module}"), name)


@pytest.mark.parametrize(
    "case", PYTHON, ids=[f"{c['python']}({', '.join(map(str, c['args']))})" for c in PYTHON]
)
def test_python_writes_what_the_web_app_writes(case):
    assert formatter(case["python"])(*case["args"]) == case["out"]


def test_the_cases_cover_the_card_times():
    """AC4: the three shapes of a time, each checked on both sides."""
    checked = {c["out"] for c in PYTHON if c["python"] == "results.race_time"}
    assert {"49.677", "1:36.595", "1:02:03.456"} <= checked
    assert {c["fn"] for c in PYTHON} == {"lapTime", "raceTime"}


def test_a_changed_python_formatter_fails(monkeypatch):
    from those_who_run import results

    monkeypatch.setattr(results, "race_time", lambda ms: f"{ms / 1000:.3f}")
    wrong = [c for c in PYTHON if formatter(c["python"])(*c["args"]) != c["out"]]
    assert wrong, "a formatter that writes 96.595 for 1:36.595 must fail a case"


def test_every_case_is_well_formed():
    for c in CASES:
        assert set(c) <= {"fn", "args", "out", "python"}, c
        assert isinstance(c["fn"], str) and isinstance(c["args"], list) and "out" in c, c
