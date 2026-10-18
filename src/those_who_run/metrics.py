"""Prometheus metrics. :mod:`those_who_run.server` serves them on /metrics."""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

from those_who_run.sessionkind import SessionKind
from those_who_run.state import RaceState
from those_who_run.trackdetect import TrackMatch


class Metrics:
    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self.registry = registry or CollectorRegistry()
        r = self.registry
        self.packets_total = Counter(
            "gt7_telemetry_packets_total", "Telemetry packets received", registry=r
        )
        self.telemetry_connected = Gauge(
            "gt7_telemetry_connected", "1 when packets arrived recently", registry=r
        )
        self.voice_connected = Gauge(
            "gt7_voice_connected", "1 when joined to the Discord voice channel", registry=r
        )
        self.in_race = Gauge("gt7_in_race", "1 while a race is in progress", registry=r)
        self.callouts_total = Counter(
            "gt7_callouts_total", "Callouts queued by rule", ["rule"], registry=r
        )
        self.callouts_dropped_total = Counter(
            "gt7_callouts_dropped_total", "Callouts dropped as stale", registry=r
        )
        self.current_lap = Gauge("gt7_current_lap", "Current lap", registry=r)
        self.total_laps = Gauge("gt7_total_laps", "Total laps (0 for timed races)", registry=r)
        self.fuel_level = Gauge("gt7_fuel_level", "Fuel level", registry=r)
        self.fuel_capacity = Gauge("gt7_fuel_capacity", "Fuel capacity", registry=r)
        self.fuel_laps_remaining = Gauge(
            "gt7_fuel_laps_remaining", "Estimated laps of fuel remaining", registry=r
        )
        self.last_lap_seconds = Gauge("gt7_last_lap_seconds", "Last lap time", registry=r)
        self.best_lap_seconds = Gauge("gt7_best_lap_seconds", "Best lap time", registry=r)
        self.speed_kph = Gauge("gt7_speed_kph", "Speed", registry=r)
        self.track_id = Gauge("gt7_track_id", "Detected track id (0 = unknown)", registry=r)
        self.results_posts_total = Counter(
            "gt7_results_posts_total",
            "Results cards: ok, failed (after retries) or skipped (no full lap)",
            ["result"],
            registry=r,
        )
        self.session_info = Gauge(
            "gt7_session_info",
            "Detected session kind, 1 with kind, fuel use and start type as labels",
            ["kind", "fuel_use", "start"],
            registry=r,
        )
        self.track_info = Gauge(
            "gt7_track_info",
            "Detected track, 1 with name and confidence as labels",
            ["track_id", "name", "confidence"],
            registry=r,
        )
        self.speech_seconds = Histogram(
            "gt7_speech_seconds",
            "Time to synthesise a callout",
            buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5),
            registry=r,
        )
        self._dropped_seen = 0

    def observe_state(self, state: RaceState) -> None:
        self.packets_total.inc()
        self.in_race.set(1 if state.in_race else 0)
        self.current_lap.set(max(state.current_lap, 0))
        self.total_laps.set(state.total_laps)
        self.fuel_level.set(state.fuel_level)
        self.fuel_capacity.set(state.fuel_capacity)
        self.last_lap_seconds.set(state.last_lap_ms / 1000 if state.last_lap_ms > 0 else 0)
        self.best_lap_seconds.set(state.best_lap_ms / 1000 if state.best_lap_ms > 0 else 0)
        self.speed_kph.set(state.speed_kph)

    def set_track(self, match: TrackMatch) -> None:
        self.track_id.set(match.track_id or 0)
        self.track_info.clear()
        self.track_info.labels(
            str(match.track_id or 0), match.name or "unknown", match.confidence
        ).set(1)

    def set_session(self, kind: SessionKind) -> None:
        fuel = "unknown" if kind.fuel_use is None else ("on" if kind.fuel_use else "off")
        self.session_info.clear()
        self.session_info.labels(kind.kind, fuel, kind.start).set(1)

    def observe_dropped(self, dropped_total: int) -> None:
        delta = dropped_total - self._dropped_seen
        if delta > 0:
            self.callouts_dropped_total.inc(delta)
            self._dropped_seen = dropped_total

    def render(self) -> bytes:
        return generate_latest(self.registry)
