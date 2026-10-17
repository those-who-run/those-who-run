"""The pit wall page under Streamlit's AppTest: both views and their edges (#168)."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from tests.test_cli_smoke import SUZUKA, fixture, store_session
from those_who_run.pitwall import data
from those_who_run.replay import read_recording

T0 = datetime(2026, 10, 15, 18, 0, tzinfo=UTC).timestamp()

testing = pytest.importorskip("streamlit.testing.v1")


def page(root: Path, monkeypatch, session: str | None = None):
    import those_who_run.pitwall as pitwall

    monkeypatch.setenv("GT7_DATA_DIR", str(root))
    script = str(Path(pitwall.__file__).with_name("app.py"))
    at = testing.AppTest.from_file(script, default_timeout=60).run()
    assert not at.exception
    if session is not None:  # opened from a link: set once the page is up
        at.query_params["session"] = session
        at.run()
        assert not at.exception
    return at


def test_an_empty_store(tmp_path, monkeypatch):
    at = page(tmp_path, monkeypatch)
    assert "No sessions" in at.info[0].value


def test_an_unknown_session_and_a_hand_edited_link(tmp_path, monkeypatch):
    store_session(tmp_path, list(read_recording(fixture(SUZUKA))))
    at = page(tmp_path, monkeypatch, "20990101-000000")
    assert [w.value for w in at.error] == ["No session 20990101-000000."], repr(at)
    at = page(tmp_path, monkeypatch, "../etc")
    assert at.error, repr(at)


def test_open_a_session_and_compare_with_another_at_the_track(tmp_path, monkeypatch):
    frames = list(read_recording(fixture(SUZUKA)))
    store_session(tmp_path, frames, at=T0)
    store_session(tmp_path, frames, at=T0 + 86400)  # the same drive a day later
    rows = data.list_sessions(tmp_path)
    at = page(tmp_path, monkeypatch)
    at.button[0].click().run()  # "Laps" on the newest session
    assert not at.exception and at.query_params["session"] == rows[0].session_id
    assert at.dataframe
    at.toggle[0].set_value(True).run()
    assert not at.exception
    assert [s.label for s in at.selectbox] == ["Lap A", "Session for lap B", "Lap B"]
    at.button[0].click().run()  # back to the sessions
    assert not at.exception and "session" not in at.query_params
