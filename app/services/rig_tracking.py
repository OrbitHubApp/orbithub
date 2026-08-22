"""app/services/rig_tracking.py

Hintergrund-Tracking-Loop fuer die Doppler-korrigierte IC-705-Fernsteuerung
waehrend eines aktiven Satelliten-Ueberflugs.

Es gibt genau eine aktive Tracking-Sitzung gleichzeitig (ein Funkgeraet kann
ohnehin nur einen Satelliten gleichzeitig verfolgen) - ein neuer Start
beendet automatisch eine evtl. laufende Sitzung. Der Loop laeuft als
asyncio-Task im bestehenden FastAPI-Event-Loop; alle blockierenden
rigctld-Aufrufe (RigControl aus rig_control.py ist synchron) werden ueber
asyncio.to_thread() ausgelagert, damit der einzige uvicorn-Worker dabei
nicht blockiert wird.

Getunt wird ausschliesslich die aktuelle VFO-Empfangsfrequenz (RX). Die
korrigierte Sendefrequenz (TX) wird berechnet und im Status angezeigt,
aber nicht automatisch gesetzt - dafuer waere Split-/Duplex-Steuerung
(VFO A/B einzeln ansprechen) noetig, die der aktuelle rigctld-Client nicht
unterstuetzt. Bei einem klassischen FM-Transponder mit identischer
Uplink-/Downlink-Frequenz (z. B. der ISS-APRS-Digipeater) ist das ohnehin
irrelevant.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.services.doppler import corrected_transponder_frequencies, range_rate_km_s
from app.services.rig_control import RigControlError, rig_control

logger = logging.getLogger(__name__)

UPDATE_INTERVAL_SECONDS = 3.0


@dataclass
class TrackingStatus:
    """Momentaufnahme des Tracking-Zustands, ueber die Status-API abrufbar."""

    active: bool = False
    norad_id: str = ""
    satellite_name: str = ""
    transponder_description: str = ""
    transponder_mode: str = ""
    range_rate_km_s: float | None = None
    rx_frequency_hz: float | None = None
    tx_frequency_hz: float | None = None
    last_update_utc: str | None = None
    error: str | None = None


class TrackingSession:
    """Haelt genau eine laufende Doppler-Tracking-Sitzung."""

    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._status = TrackingStatus()

    @property
    def status(self) -> TrackingStatus:
        return self._status

    def start(
        self,
        *,
        norad_id: str,
        satellite: Any,
        observer: Any,
        timescale: Any,
        transponder: dict[str, Any],
    ) -> None:
        """Startet eine neue Tracking-Sitzung; eine laufende wird zuvor gestoppt."""
        self.stop()
        self._status = TrackingStatus(
            active=True,
            norad_id=norad_id,
            satellite_name=getattr(satellite, "name", "") or norad_id,
            transponder_description=str(transponder.get("description") or ""),
            transponder_mode=str(transponder.get("mode") or ""),
        )
        self._task = asyncio.create_task(
            self._loop(satellite, observer, timescale, transponder)
        )

    def stop(self) -> None:
        """Stoppt eine laufende Tracking-Sitzung (falls vorhanden)."""
        if self._task is not None and not self._task.done():
            self._task.cancel()
        self._task = None
        self._status = TrackingStatus(active=False)

    async def _loop(
        self,
        satellite: Any,
        observer: Any,
        timescale: Any,
        transponder: dict[str, Any],
    ) -> None:
        try:
            while True:
                try:
                    t = timescale.now()
                    rate = await asyncio.to_thread(
                        range_rate_km_s, satellite, observer, t
                    )
                    freqs = corrected_transponder_frequencies(transponder, rate)
                    rx_hz = round(freqs["rx_frequency_hz"])

                    await asyncio.to_thread(rig_control.set_frequency, rx_hz)

                    self._status.range_rate_km_s = rate
                    self._status.rx_frequency_hz = freqs["rx_frequency_hz"]
                    self._status.tx_frequency_hz = freqs["tx_frequency_hz"]
                    self._status.last_update_utc = datetime.now(timezone.utc).isoformat()
                    self._status.error = None
                except RigControlError as exc:
                    logger.warning("Doppler-Tracking: rigctld-Fehler: %r", exc)
                    self._status.error = str(exc)
                except Exception as exc:  # noqa: BLE001 - der Loop soll nicht sterben
                    logger.exception("Doppler-Tracking: unerwarteter Fehler")
                    self._status.error = str(exc)

                await asyncio.sleep(UPDATE_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            raise


# Modulweite Standardinstanz - es gibt ohnehin nur eine Sitzung gleichzeitig.
tracking_session = TrackingSession()
