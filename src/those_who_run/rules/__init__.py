"""Rule registry."""

from __future__ import annotations

from typing import Any

from those_who_run.rules.base import Rule
from those_who_run.rules.final_lap import FinalLapRule
from those_who_run.rules.fuel import FuelRule
from those_who_run.rules.lap_time import LapTimeRule
from those_who_run.rules.position import PositionRule
from those_who_run.rules.race_summary import RaceSummaryRule
from those_who_run.rules.start_brief import StartBriefRule
from those_who_run.rules.temps import TempsRule

REGISTRY: dict[str, type[Rule]] = {
    LapTimeRule.name: LapTimeRule,
    FuelRule.name: FuelRule,
    FinalLapRule.name: FinalLapRule,
    PositionRule.name: PositionRule,
    StartBriefRule.name: StartBriefRule,
    RaceSummaryRule.name: RaceSummaryRule,
    TempsRule.name: TempsRule,
}


def build_rules(rules_cfg: dict[str, Any]) -> list[Rule]:
    """Instantiate every enabled rule from the ``rules:`` section of the config."""
    rules: list[Rule] = []
    for name, cls in REGISTRY.items():
        cfg = dict(rules_cfg.get(name) or {})
        if not cfg.get("enabled", True):
            continue
        rules.append(cls(cfg))
    return rules


__all__ = [
    "REGISTRY",
    "FinalLapRule",
    "FuelRule",
    "LapTimeRule",
    "PositionRule",
    "RaceSummaryRule",
    "Rule",
    "StartBriefRule",
    "TempsRule",
    "build_rules",
]
