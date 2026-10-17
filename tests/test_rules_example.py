"""rules.example.yaml documents every built-in default, and nothing else (#168).

A key commented out in the example (``# template: "..."``) still counts as
documented; its value must match the default too.
"""

import re
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import yaml

from those_who_run.config import DEFAULT_RULES

EXAMPLE = Path(__file__).parent.parent / "rules.example.yaml"


def leaves(tree: Mapping[str, Any], path: tuple[str, ...] = ()) -> Iterator[tuple[str, Any]]:
    for key, value in tree.items():
        if isinstance(value, Mapping):
            yield from leaves(value, (*path, key))
        else:
            yield ".".join((*path, key)), value


def example(text: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """The example's keys as set, and as set or commented out."""
    live = dict(leaves(yaml.safe_load(text)))
    documented = dict(leaves(yaml.safe_load(re.sub(r"(?m)^(\s*)# (\w+:)", r"\1\2", text))))
    return live, documented


def drift(text: str) -> list[str]:
    live, documented = example(text)
    defaults = dict(leaves(DEFAULT_RULES))
    problems = [f"{k}: default not in the example" for k in defaults if k not in documented]
    problems += [f"{k}: in the example, not a default" for k in documented if k not in defaults]
    problems += [
        f"{k}: example {v!r} is not the default {defaults[k]!r}"
        for k, v in documented.items()
        if k in defaults and v != defaults[k]
    ]
    return problems


def test_example_and_defaults_are_in_step():
    text = EXAMPLE.read_text(encoding="utf-8")
    assert drift(text) == []
    live, _ = example(text)
    assert "rules.lap_time.priority" in live  # set, not only commented out


def test_a_key_missing_from_the_example_fails():
    text = EXAMPLE.read_text(encoding="utf-8")
    assert drift(text.replace("    min_fuel: 1.0", "")) == [
        "rules.race_summary.min_fuel: default not in the example"
    ]
    assert drift(text.replace("    # template_pit:", "    # template_pt:")) == [
        "rules.fuel.template_pit: default not in the example",
        "rules.fuel.template_pt: in the example, not a default",
    ]


def test_a_value_out_of_step_fails():
    text = EXAMPLE.read_text(encoding="utf-8")
    assert drift(text.replace("pit_laps: 2 ", "pit_laps: 3 ")) == [
        "rules.fuel.pit_laps: example 3 is not the default 2.0"
    ]
