"""The pit wall page: sessions, a session's laps and lap compare.

Run by ``those-who-run web`` through ``streamlit run``; the only module that
imports Streamlit. Everything it shows comes from ``pitwall.data``. One page,
two views, chosen by the ``session`` query parameter, so a session has a link
of its own (``?session=20261017-162118``) for the results cards to use later
(#116). Laid out in one column so it reads on a phone straight after a race.
"""

from __future__ import annotations

from datetime import tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo

import altair as alt
import pandas as pd
import streamlit as st

from those_who_run import __version__, brand
from those_who_run.config import Settings
from those_who_run.pitwall import data
from those_who_run.results import race_time
from those_who_run.sessionkind import LABELS

PAGE_SIZE = 25  # sessions shown before "Show more"

# Lap A in the accent, lap B in white, on the deep black background.
LAP_COLOURS = [brand.hex_colour(brand.ADVAN_RED), brand.hex_colour(brand.WHITE)]

CHANNELS: tuple[tuple[str, str, str], ...] = (
    # (Trace attribute, axis title, interpolation)
    ("speed_kph", "Speed (km/h)", "linear"),
    ("throttle_pct", "Throttle (%)", "linear"),
    ("brake_pct", "Brake (%)", "linear"),
    ("gear", "Gear", "step-after"),
    ("rpm", "RPM", "linear"),
)


def data_dir() -> Path:
    return Settings.from_env().data_dir


def viewer_tz() -> tzinfo | None:
    """The browser's time zone when Streamlit knows it; the server's otherwise."""
    name = getattr(st.context, "timezone", None)
    try:
        return ZoneInfo(name) if name else None
    except (KeyError, ValueError):
        return None


# Cached on the index's modification time: a new lap or session shows up on the
# next rerun, and nothing is re-read while the engineer is idle.


@st.cache_data(show_spinner=False)
def sessions(root: str, stamp: float) -> list[data.SessionRow]:
    return data.list_sessions(Path(root))


@st.cache_data(show_spinner=False)
def laps(root: str, session_id: str, stamp: float) -> list[data.LapRow]:
    return data.lap_summaries(Path(root), session_id)


@st.cache_data(show_spinner=False)
def trace(root: str, session_id: str, lap: int, stamp: float) -> data.Trace | None:
    return data.lap_trace(Path(root), session_id, lap)


def open_session(session_id: str | None) -> None:
    if session_id is None:
        st.query_params.clear()
    else:
        st.query_params["session"] = session_id


def facts_line(row: data.SessionRow, tz: tzinfo | None) -> str:
    when = row.started(tz).strftime("%a %d %b %Y, %H:%M")
    parts = [when] + [f"{name} {value}" for name, value in row.facts]
    return " · ".join(parts)


# views


def sessions_view(root: str, stamp: float, tz: tzinfo | None) -> None:
    rows = sessions(root, stamp)
    if not rows:
        st.info(f"No sessions in {root} yet. Drive a lap and they appear here.")
        return
    opts = data.filter_options(rows)
    with st.expander("Filter", expanded=False):
        track = st.selectbox("Track", [None, *opts["track"]], format_func=lambda v: v or "Any")
        car = st.selectbox("Car", [None, *opts["car"]], format_func=lambda v: v or "Any")
        kind = st.selectbox(
            "Session kind",
            [None, *opts["kind"]],
            format_func=lambda v: LABELS.get(v, v) if v else "Any",
        )
        days = sorted({r.started(tz).date() for r in rows})
        picked = st.date_input(
            "Dates", value=(days[0], days[-1]), min_value=days[0], max_value=days[-1]
        )
    since, until = (picked + (None,))[:2] if isinstance(picked, tuple) else (picked, picked)
    shown = data.filter_sessions(rows, data.SessionFilter(track, car, kind, since, until), tz)
    st.caption(f"{len(shown)} of {len(rows)} sessions")

    limit = st.session_state.get("limit", PAGE_SIZE)
    for row in shown[:limit]:
        with st.container(border=True):
            st.markdown(f"**{row.title}**")
            st.markdown(row.result)
            st.caption(facts_line(row, tz))
            st.button(
                f"{brand.GLYPH_TIMER} Laps",
                key=f"open-{row.session_id}",
                on_click=open_session,
                args=(row.session_id,),
            )
    if len(shown) > limit and st.button("Show more"):
        st.session_state["limit"] = limit + PAGE_SIZE
        st.rerun()


def session_view(root: str, stamp: float, tz: tzinfo | None, session_id: str) -> None:
    st.button("← Sessions", on_click=open_session, args=(None,))
    all_rows = sessions(root, stamp)
    row = next((r for r in all_rows if r.session_id == session_id), None)
    if row is None:
        st.warning(f"No session {session_id}.")
        return
    st.subheader(row.title)
    st.markdown(row.result)
    st.caption(facts_line(row, tz))

    lap_rows = laps(root, session_id, stamp)
    if not lap_rows:
        st.info("No laps stored for this session.")
        return
    st.markdown(f"#### {brand.GLYPH_TIMER} Laps")
    st.dataframe(lap_frame(lap_rows), hide_index=True)
    st.caption(
        "Pit: fuel went up during the lap. Out: the lap after a pit stop. "
        "Partial: the lap the session ended in. Position only in a field GT7 flags."
    )

    st.markdown("#### Lap compare")
    compare_view(root, stamp, tz, row, lap_rows, all_rows)


def lap_frame(rows: list[data.LapRow]) -> pd.DataFrame:
    best = next((r.time_ms for r in rows if r.best), None)
    return pd.DataFrame(
        {
            "Lap": [r.lap for r in rows],
            "Time": [r.time for r in rows],
            "Gap": [
                f"{(r.time_ms - best) / 1000:+.3f}" if best and r.time_ms and not r.best else ""
                for r in rows
            ],
            "Fuel used": [
                round(r.fuel_used, 1)
                if r.fuel_use and not r.pit and r.fuel_used is not None
                else None
                for r in rows
            ],
            "Fuel left": [
                round(r.fuel_end, 1) if r.fuel_use and r.fuel_end is not None else None
                for r in rows
            ],
            "Pos": [r.position for r in rows],
            "Top km/h": [None if r.top_speed_kph is None else round(r.top_speed_kph) for r in rows],
            "Flags": [r.flags for r in rows],
        }
    )


def compare_view(
    root: str,
    stamp: float,
    tz: tzinfo | None,
    row: data.SessionRow,
    lap_rows: list[data.LapRow],
    all_rows: list[data.SessionRow],
) -> None:
    timed = [r for r in lap_rows if r.time_ms] or lap_rows
    by_time = sorted(timed, key=lambda r: r.time_ms or 1 << 62)
    best = next((r for r in lap_rows if r.best), by_time[0])
    default_b = next((r for r in by_time if r.lap != best.lap), best)

    def lap_label(r: data.LapRow) -> str:
        return f"Lap {r.lap}  {r.time or r.flags}".rstrip()

    lap_no = {r.lap: r for r in lap_rows}
    a = st.selectbox(
        "Lap A",
        [r.lap for r in lap_rows],
        index=[r.lap for r in lap_rows].index(best.lap),
        format_func=lambda n: lap_label(lap_no[n]),
    )

    # Lap B from this session by default, or from another session at the same track.
    others = [r for r in all_rows if r.track == row.track and r.session_id != row.session_id]
    b_session = row.session_id
    if others and st.toggle("Lap B from another session at this track"):
        b_session = st.selectbox(
            "Session for lap B",
            [r.session_id for r in others],
            format_func=lambda sid: next(
                f"{r.started(tz):%d %b %H:%M} · {r.title.split(' · ', 1)[-1]} · {r.car or ''}"
                for r in others
                if r.session_id == sid
            ),
        )
    b_rows = lap_rows if b_session == row.session_id else laps(root, b_session, stamp)
    if not b_rows:
        st.info("No laps in that session.")
        return
    b_no = {r.lap: r for r in b_rows}
    b_default = (
        default_b.lap
        if b_session == row.session_id
        else next((r.lap for r in b_rows if r.best), b_rows[0].lap)
    )
    b = st.selectbox(
        "Lap B",
        [r.lap for r in b_rows],
        index=[r.lap for r in b_rows].index(b_default),
        format_func=lambda n: lap_label(b_no[n]),
    )

    traces = [trace(root, row.session_id, a, stamp), trace(root, b_session, b, stamp)]
    if any(t is None or len(t) == 0 for t in traces):
        st.info("A lap file is missing or still being written.")
        return
    names = [f"A: lap {a}", f"B: lap {b}"]
    times = [lap_no[a].time_ms, b_no[b].time_ms]
    if all(times):
        assert times[0] is not None and times[1] is not None
        st.caption(
            f"A {race_time(times[0])} vs B {race_time(times[1])}, "
            f"A is {(times[0] - times[1]) / 1000:+.3f} s. Traces over time from each lap's start."
        )
    long = pd.concat(
        [
            pd.DataFrame(
                {
                    "Time (s)": t.t,
                    "Lap": name,
                    **{attr: getattr(t, attr) for attr, _, _ in CHANNELS},
                }
            )
            for t, name in zip(traces, names, strict=True)
            if t is not None
        ]
    )
    colour = alt.Color(
        "Lap:N", scale=alt.Scale(domain=names, range=LAP_COLOURS), legend=alt.Legend(orient="top")
    )
    zoom = alt.selection_interval(bind="scales", encodings=["x"])
    for attr, title, interp in CHANNELS:
        chart = (
            alt.Chart(long, height=170)
            .mark_line(interpolate=interp, strokeWidth=1.5)
            .encode(
                x=alt.X("Time (s):Q", title=None),
                y=alt.Y(f"{attr}:Q", title=title),
                color=colour,
                tooltip=["Lap", "Time (s)", alt.Tooltip(f"{attr}:Q", title=title, format=".0f")],
            )
            .add_params(zoom)
            .properties(width="container")
        )
        st.altair_chart(chart)


def main() -> None:
    st.set_page_config(
        page_title=f"Pit wall · {brand.NAME}",
        page_icon=brand.GLYPH_FLAG,
        layout="centered",
    )
    root = str(data_dir())
    stamp = data.index_stamp(Path(root))
    tz = viewer_tz()
    st.markdown(f"### {brand.GLYPH_FLAG} Pit wall")
    session_id = st.query_params.get("session")
    if session_id:
        try:
            session_view(root, stamp, tz, session_id)
        except ValueError as exc:  # a hand-edited link
            st.warning(str(exc))
    else:
        sessions_view(root, stamp, tz)
    st.caption(f"{brand.NAME} {brand.KANJI} {__version__} · read-only view of {root}")


main()
