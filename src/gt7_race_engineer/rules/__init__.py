"""Rule registry."""

from __future__ import annotations

from typing import Any

from gt7_race_engineer.rules.base import Rule
from gt7_race_engineer.rules.final_lap import FinalLapRule
from gt7_race_engineer.rules.fuel import FuelRule
from gt7_race_engineer.rules.lap_time import LapTimeRule
from gt7_race_engineer.rules.position import PositionRule

REGISTRY: dict[str, type[Rule]] = {
    LapTimeRule.name: LapTimeRule,
    FuelRule.name: FuelRule,
    FinalLapRule.name: FinalLapRule,
    PositionRule.name: PositionRule,
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
    "Rule",
    "build_rules",
]
