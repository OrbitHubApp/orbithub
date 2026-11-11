"""app/services/live_observer.py

Live-Beobachtung: der IC-705 hoert automatisch die Satelliten mit, die auf
AMSAT Live als "gehoert" gemeldet sind - jeweils den, der gerade am hoechsten
steht.

Ablauf (alle CHECK_INTERVAL_SECONDS):
1. Kandidatenliste (von main.py geliefert, alle REFRESH_INTERVAL_SECONDS neu):
   AMSAT-Eintraege im gewaehlten Zeitraum, letzter Bericht nicht "nicht
   gehoert", mit zugeordnetem Transponder und Bahndaten.
2. Fuer jeden Kandidaten die aktuelle Elevation berechnen. Hoerbar ist er ab
   MIN_ELEVATION_DEG (10 Grad), mindestens aber ab dem Funk-Horizontprofil
   in seiner Richtung.
3. Der hoechste hoerbare Satellit wird per Doppler-Tracking eingestellt.
   Damit bei zwei fast gleich hohen Satelliten nicht staendig hin und her
   geschaltet wird, wechselt die Beobachtung erst, wenn der andere um
   SWITCH_MARGIN_DEG hoeher steht oder der aktuelle unter die Schwelle faellt.
4. Ist keiner hoerbar, wird das Tracking angehalten (der IC-705 bleibt auf
   der letzten Frequenz) und der naechste hoerbare Ueberflug angezeigt.

Der Zustand (an/aus, Zeitraum) wird in data/live-observer.json gespeichert,
damit die Beobachtung einen Neustart des Containers uebersteht.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from app.services.rig_tracking import tracking_session

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 10.0
REFRESH_INTERVAL_SECONDS = 600.0
MIN_ELEVATION_DEG = 10.0
SWITCH_MARGIN_DEG = 5.0

# Liefert {"candidates": [...], "observer": ..., "observer_settings": ..., "timescale": ...}
CandidateProvider = Callable[[int], Awaitable[dict[str, Any]]]


@dataclass
class LiveObserverStatus:
    active: bool = False
    hours: int = 24
    min_elevation_deg: float = MIN_ELEVATION_DEG
    started_at: str | None = None
    candidates_count: int = 0
    candidates_refreshed_at: str | None = None
    current: dict[str, Any] | None = None
    visible: list[dict[str, Any]] = field(default_factory=list)
    next_up: dict[str, Any] | None = None
    switches: int = 0
    error: str | None = None


class LiveObserver:
    def __init__(self, state_file: Path) -> None:
        self._state_file = state_file
        self._task: asyncio.Task[None] | None = None
        self._status = LiveObserverStatus()
        self._provider: CandidateProvider | None = None

    @property
    def status(self) -> LiveObserverStatus:
        return self._status

    @property
    def active(self) -> bool:
        return self._task is not None and not self._task.done()

    # ---------------------------------------------------------------- Zustand
    def _save_state(self) -> None:
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            self._state_file.write_text(
                json.dumps({"active": self._status.active, "hours": self._status.hours}),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning("Live-Beobachtung: Zustand nicht gespeichert: %r", exc)

    def saved_state(self) -> dict[str, Any]:
        try:
            data = json.loads(self._state_file.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    # ------------------------------------------------------------ Start/Stop
    def start(self, hours: int, provider: CandidateProvider) -> None:
        self.stop(stop_tracking=False, persist=False)
        self._provider = provider
        self._status = LiveObserverStatus(
            active=True,
            hours=hours,
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        self._save_state()
        self._task = asyncio.create_task(self._loop())

    def stop(self, *, stop_tracking: bool = True, persist: bool = True) -> None:
        was_active = self.active
        if self._task is not None and not self._task.done():
            self._task.cancel()
        self._task = None
        hours = self._status.hours
        self._status = LiveObserverStatus(active=False, hours=hours)
        if was_active and stop_tracking:
            tracking_session.stop()
        if persist:
            self._save_state()

    # ------------------------------------------------------------------ Loop
    async def _loop(self) -> None:
        candidates: list[dict[str, Any]] = []
        context: dict[str, Any] = {}
        refreshed = 0.0
        current_key: str | None = None
        try:
            while True:
                try:
                    if not candidates or time.monotonic() - refreshed > REFRESH_INTERVAL_SECONDS:
                        assert self._provider is not None
                        context = await self._provider(self._status.hours)
                        candidates = context.get("candidates", [])
                        refreshed = time.monotonic()
                        self._status.candidates_count = len(candidates)
                        self._status.candidates_refreshed_at = datetime.now(timezone.utc).isoformat()

                    positions = await asyncio.to_thread(self._positions, candidates, context)
                    audible = [p for p in positions if p["audible"]]
                    audible.sort(key=lambda p: p["el"], reverse=True)
                    self._status.visible = [
                        {k: p[k] for k in ("key", "name", "mode", "el", "az", "rig_mode", "downlink_hz")}
                        for p in audible
                    ]

                    choice = audible[0] if audible else None
                    current = next((p for p in audible if p["key"] == current_key), None)
                    if choice and current and choice is not current:
                        if choice["el"] < current["el"] + SWITCH_MARGIN_DEG:
                            choice = current  # Hysterese: nicht wegen 1-2 Grad wechseln

                    tracking = tracking_session.status
                    if choice is None:
                        if current_key is not None:
                            tracking_session.stop()
                            current_key = None
                        self._status.current = None
                    else:
                        candidate = choice["candidate"]
                        if (
                            choice["key"] != current_key
                            or not tracking.active
                            or tracking.norad_id != candidate["norad_id"]
                        ):
                            tracking_session.start(
                                norad_id=candidate["norad_id"],
                                satellite=candidate["satellite"],
                                observer=context["observer"],
                                timescale=context["timescale"],
                                transponder=candidate["transponder"],
                            )
                            if current_key is not None and choice["key"] != current_key:
                                self._status.switches += 1
                            current_key = choice["key"]
                            logger.info("Live-Beobachtung: %s (%.0f Grad)", choice["name"], choice["el"])
                        self._status.current = {
                            k: choice[k]
                            for k in ("key", "name", "mode", "el", "az", "rig_mode", "downlink_hz", "set")
                        }

                    self._status.next_up = self._next_up(candidates, audible)
                    self._status.error = None
                except Exception as exc:  # noqa: BLE001 - der Loop soll weiterlaufen
                    logger.exception("Live-Beobachtung: Fehler")
                    self._status.error = str(exc)
                    if not candidates:
                        refreshed = 0.0
                await asyncio.sleep(CHECK_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            raise

    @staticmethod
    def _positions(candidates: list[dict[str, Any]], context: dict[str, Any]) -> list[dict[str, Any]]:
        observer = context.get("observer")
        timescale = context.get("timescale")
        settings = context.get("observer_settings")
        if observer is None or timescale is None:
            return []
        t = timescale.now()
        now = datetime.now(timezone.utc)
        result = []
        for candidate in candidates:
            alt, az, _ = (candidate["satellite"] - observer).at(t).altaz()
            el = float(alt.degrees)
            azimuth = float(az.degrees)
            threshold = MIN_ELEVATION_DEG
            if settings is not None:
                threshold = max(threshold, settings.minimum_elevation_at(azimuth))
            current_pass = next(
                (p for p in candidate.get("passes", []) if p["rise"] <= now <= p["set"]),
                None,
            )
            result.append(
                {
                    "key": candidate["key"],
                    "name": candidate["name"],
                    "mode": candidate["mode"],
                    "rig_mode": candidate["rig_mode"],
                    "downlink_hz": candidate["downlink_hz"],
                    "el": round(el, 1),
                    "az": round(azimuth, 0),
                    "audible": el >= threshold,
                    "set": current_pass["set"].isoformat() if current_pass else None,
                    "candidate": candidate,
                }
            )
        return result

    @staticmethod
    def _next_up(candidates: list[dict[str, Any]], audible: list[dict[str, Any]]) -> dict[str, Any] | None:
        now = datetime.now(timezone.utc)
        audible_keys = {p["key"] for p in audible}
        best = None
        for candidate in candidates:
            if candidate["key"] in audible_keys:
                continue
            for p in candidate.get("passes", []):
                if p["rise"] > now and p["max_el"] >= MIN_ELEVATION_DEG:
                    if best is None or p["rise"] < best[1]["rise"]:
                        best = (candidate, p)
                    break
        if best is None:
            return None
        candidate, p = best
        return {
            "name": candidate["name"],
            "mode": candidate["mode"],
            "rise": p["rise"].isoformat(),
            "set": p["set"].isoformat(),
            "max_el": round(p["max_el"], 0),
        }


live_observer = LiveObserver(Path("/app/data/live-observer.json"))
