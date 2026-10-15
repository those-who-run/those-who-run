"""Pick a phrase for a callout: one template, or one of several variants.

Any template key in the rules config may hold a list instead of a string. A
variant is picked at random, never the one spoken last for that key, so a long
race does not hear the same sentence lap after lap. ``first`` returns the first
key that is configured, which is how a rule prefers a situational pool
("template_gained_lead") and falls back to the general one.
"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from typing import Any


class Phrasebook:
    def __init__(self, cfg: Mapping[str, Any], rng: random.Random | None = None) -> None:
        self.cfg = cfg
        self.rng = rng or random.Random()
        self._last: dict[str, str] = {}

    def has(self, key: str) -> bool:
        value = self.cfg.get(key)
        return bool(value) if isinstance(value, list) else value is not None

    def pick(self, key: str, default: str) -> str:
        value = self.cfg.get(key, default)
        if not isinstance(value, Sequence) or isinstance(value, str):
            return str(value)
        variants = [str(v) for v in value]
        if not variants:
            return default
        fresh = [v for v in variants if v != self._last.get(key)] or variants
        choice = self.rng.choice(fresh)
        self._last[key] = choice
        return choice

    def first(self, keys: Sequence[str], default: str) -> str:
        for key in keys:
            if self.has(key):
                return self.pick(key, default)
        return default
