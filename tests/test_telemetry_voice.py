from tests.conftest import make_state
from those_who_run.rules.telemetry import TelemetryVoice
from those_who_run.state import Phase

RACING = make_state(current_lap=3)
PAUSED = make_state(current_lap=3, phase=Phase.PAUSED)
MENU = make_state(current_lap=-1, phase=Phase.MENU)


def texts(voice, ticks):
    out = []
    for i, (connected, last) in enumerate(ticks):
        out += [c.text for c in voice.observe(connected, last, float(i))]
    return out


def test_lost_in_race_then_back():
    v = TelemetryVoice()
    ticks = [(True, RACING)] * 3 + [(False, RACING)] * 4 + [(True, RACING)] * 2
    assert texts(v, ticks) == ["Lost telemetry.", "Telemetry back."]


def test_lost_while_paused_counts():
    assert texts(TelemetryVoice(), [(True, PAUSED), (False, PAUSED), (True, PAUSED)]) == [
        "Lost telemetry.",
        "Telemetry back.",
    ]


def test_silence_in_a_menu_is_normal():
    v = TelemetryVoice()
    assert texts(v, [(True, MENU), (False, MENU), (False, MENU), (True, MENU)]) == []
    assert texts(v, [(False, None), (True, None)]) == [], "nothing seen yet"


def test_first_tick_is_never_a_change():
    assert texts(TelemetryVoice(), [(False, RACING), (True, RACING)]) == []


def test_callout_priority_rule_and_clock():
    v = TelemetryVoice({"priority": 2, "template_lost": "Gone."})
    v.observe(True, RACING, 10.0)
    (c,) = v.observe(False, RACING, 11.0)
    assert (c.text, c.priority, c.rule, c.created_at) == ("Gone.", 2, "telemetry", 11.0)


def test_phases_and_enabled_are_configurable():
    quiet = TelemetryVoice({"enabled": False})
    assert texts(quiet, [(True, RACING), (False, RACING), (True, RACING)]) == []
    only_race = TelemetryVoice({"phases": ["in_race"]})
    assert texts(only_race, [(True, PAUSED), (False, PAUSED), (True, PAUSED)]) == []


def test_telemetry_phrases_can_be_variants():
    voice = TelemetryVoice({"template_lost": ["Data link is down."], "template_back": ["Back."]})
    voice.observe(True, RACING, 0.0)
    assert [c.text for c in voice.observe(False, RACING, 1.0)] == ["Data link is down."]
    assert [c.text for c in voice.observe(True, RACING, 2.0)] == ["Back."]
