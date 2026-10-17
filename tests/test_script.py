"""The bundled script, and how variants are picked."""

import random
import re
import string

import pytest

from those_who_run.config import DEFAULT_RULES, ConfigError, load_rules_config, load_script
from those_who_run.phrasing import Phrasebook
from those_who_run.verbalise import tidy_sentence

# Placeholders each key is formatted with, and the situational pools a rule knows.
WORDS = {
    "lap": "two",
    "time": "one oh four point six",
    "delta": "zero point eight",
    "gap": "zero point eight",
    "laps": "two laps",
    "position": "fifth",
    "p": "five",
    "total": "sixteen",
    "track": "Sportsland SUGO",
    "best": "Best lap one oh one point two.",
    "fuel": "thirty percent",
    "fuel_left": "seventy percent",
    "stints": "seventy percent, then sixty percent",
    "corners": "Front left tyre",
}
PLACEHOLDERS = {
    "lap_time": {
        "template": {"lap", "time", "delta"},
        "template_new_best": {"lap", "time", "gap", "delta"},
        "template_new_best_small": {"lap", "time", "gap", "delta"},
        "delta_slower": {"delta"},
        "delta_slower_small": {"delta"},
        "delta_slower_large": {"delta"},
        "delta_faster": {"delta"},
        "delta_equal": set(),
    },
    "fuel": {
        "template": {"laps"},
        "template_critical": set(),
        "template_pit": set(),
        "template_last_lap_enough": set(),
    },
    "final_lap": {"template": set()},
    "position": {
        key: {"position", "p"}
        for key in (
            "template_gained",
            "template_gained_lead",
            "template_gained_podium",
            "template_lost",
            "template_lost_lead",
        )
    },
    "start_brief": {
        "template_track": {"track"},
        "template_laps": {"laps"},
        "template_laps_to_go": {"laps"},
        "template_timed": set(),
        "template_position": {"p", "position", "total"},
    },
    "race_summary": {
        "template": {"position", "best", "fuel"},
        "template_position": {"position", "p"},
        "template_position_win": {"position", "p"},
        "template_position_podium": {"position", "p"},
        "template_best": {"time"},
        "template_fuel": {"fuel", "fuel_left"},
        "template_fuel_stints": {"stints", "fuel_left"},
        "template_quit": {"laps", "best"},
    },
    "temps": {
        "template_tyre_hot": {"corners"},
        "template_tyres_cold": set(),
        "template_water": set(),
        "template_oil": set(),
    },
    "telemetry": {"template_lost": set(), "template_back": set()},
}
SCRIPT = load_script()["rules"]
VARIANTS = [
    (rule, key, text)
    for rule, keys in SCRIPT.items()
    for key, texts in keys.items()
    for text in texts
]


def test_script_only_has_keys_the_rules_read():
    for rule, keys in SCRIPT.items():
        assert rule in PLACEHOLDERS, rule
        assert set(keys) <= set(PLACEHOLDERS[rule]), (rule, set(keys) - set(PLACEHOLDERS[rule]))


def test_every_plain_template_key_has_a_script_list():
    for rule, keys in PLACEHOLDERS.items():
        for key in keys:
            if key in DEFAULT_RULES["rules"][rule]:
                assert key in SCRIPT[rule], (rule, key)


@pytest.mark.parametrize(("rule", "key", "text"), VARIANTS)
def test_variant_is_speakable(rule, key, text):
    used = {f for _, f, _, _ in string.Formatter().parse(text) if f}
    assert used <= PLACEHOLDERS[rule][key], f"{rule}.{key}: unknown slot in {text!r}"
    spoken = tidy_sentence(text.format(**WORDS))
    assert not re.search(r"\d", spoken), spoken
    assert ".." not in spoken and ". ." not in spoken, spoken
    assert len(spoken.split()) <= 20, spoken


def test_script_lists_lead_with_the_built_in_phrase():
    for rule, keys in SCRIPT.items():
        for key, texts in keys.items():
            default = DEFAULT_RULES["rules"][rule].get(key)
            if default:
                assert tidy_sentence(texts[0]) == tidy_sentence(default), (rule, key)


def test_rules_config_layers_the_script_and_the_file_wins(tmp_path):
    assert isinstance(load_rules_config(None)["rules"]["final_lap"]["template"], list)
    f = tmp_path / "rules.yaml"
    f.write_text('rules:\n  final_lap:\n    template: "Last one."\n')
    cfg = load_rules_config(f)
    assert cfg["rules"]["final_lap"]["template"] == "Last one."
    assert isinstance(cfg["rules"]["fuel"]["template_pit"], list)
    f.write_text("script: false\n")
    assert load_rules_config(f)["rules"]["final_lap"]["template"] == "Final lap."


def test_phrasebook_never_repeats_the_last_variant():
    book = Phrasebook({"k": ["a", "b", "c"]}, random.Random(1))
    picks = [book.pick("k", "x") for _ in range(200)]
    assert set(picks) == {"a", "b", "c"}
    assert all(a != b for a, b in zip(picks, picks[1:], strict=False))


def test_phrasebook_strings_lists_and_fallbacks():
    book = Phrasebook({"one": "only", "single": ["just"], "empty": [], "pool": ["p"]})
    assert book.pick("one", "x") == "only"
    assert [book.pick("single", "x") for _ in range(3)] == ["just"] * 3
    assert book.pick("empty", "fallback") == "fallback"
    assert book.pick("missing", "fallback") == "fallback"
    assert book.first(["missing", "empty", "pool"], "d") == "p"
    assert book.first(["missing"], "d") == "d"


GAINED = ("template_gained", "template_gained_lead", "template_gained_podium")
LOST = ("template_lost", "template_lost_lead")


def test_gaining_and_losing_a_place_never_sound_the_same():
    pos = SCRIPT["position"]
    gained = {tidy_sentence(t).lower(): k for k in GAINED for t in pos.get(k, [])}
    lost = {tidy_sentence(t).lower(): k for k in LOST for t in pos.get(k, [])}
    shared = set(gained) & set(lost)
    assert not shared, {t: (gained[t], lost[t]) for t in shared}


@pytest.mark.parametrize(
    ("key", "words"),
    [
        ("template_gained", {"up", "move", "moved", "moving", "pass", "taking", "into"}),
        ("template_gained_podium", {"up", "moved", "into"}),
        ("template_lost", {"down", "fell", "dropped", "lost"}),
        ("template_lost_lead", {"lost", "dropped", "fell"}),
    ],
)
def test_every_place_change_variant_says_which_way(key, words):
    for text in SCRIPT["position"][key]:
        said = set(re.findall(r"[a-z]+", text.lower()))
        assert said & words, f"position.{key}: {text!r} does not say gained or lost"


def test_phrasebook_null_is_the_default():
    book = Phrasebook({"k": None, "pool": [None, "p"], "nulls": [None]})
    assert book.pick("k", "d") == "d"
    assert not book.has("k")
    assert book.pick("pool", "d") == "p"
    assert book.pick("nulls", "d") == "d"
    assert book.first(["k", "nulls", "pool"], "d") == "p"


def test_rules_config_null_template_falls_back_to_the_built_in(tmp_path):
    f = tmp_path / "rules.yaml"
    f.write_text("rules:\n  final_lap:\n    template:\n")
    cfg = load_rules_config(f)
    assert cfg["rules"]["final_lap"]["template"] is None
    assert Phrasebook(cfg["rules"]["final_lap"]).pick("template", "Final lap.") == "Final lap."


@pytest.mark.parametrize("value", ["{a: b}", "42", "[Final lap., {a: b}]", "[1, 2]"])
def test_rules_config_rejects_a_template_that_is_not_text(tmp_path, value):
    f = tmp_path / "rules.yaml"
    f.write_text(f"rules:\n  final_lap:\n    template: {value}\n")
    with pytest.raises(ConfigError, match=r"rules\.final_lap\.template"):
        load_rules_config(f)
