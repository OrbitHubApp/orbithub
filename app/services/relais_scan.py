"""app/services/relais_scan.py

Relais-Scan fuer den IC-705-Handbetrieb: geht die Relais-Speicherliste der
Reihe nach durch und haelt an, sobald die Rauschsperre oeffnet (Signal da).

Ablauf je Kanal: Empfangsfrequenz setzen, kurz einschwingen lassen, dann
den Rauschsperren-Status zweimal frisch abfragen (kappanhang-Erweiterung
``l SQLFRESH``; aeltere kappanhang-Versionen liefern nur den bis zu 1 s alten
Wert ``l SQLSTAT`` - dann wird entsprechend laenger gehorcht).

Signal gefunden -> Pause (PAUSE_SECONDS). Laeuft das Signal am Ende der Pause
noch, wird gewartet, bis es abfaellt - ein laufender Durchgang wird also nicht
abgeschnitten. Waehrend der Pause:
  * hold()  -> auf dem Relais bleiben: Ablage/CTCSS werden vollstaendig
               eingestellt, der Scan endet.
  * skip()  -> sofort weiter zum naechsten Relais.
  * stop()  -> Scan beenden, das Geraet bleibt auf der aktuellen Frequenz.

Beim Scannen wird nur die Empfangsfrequenz gesetzt (schnell); Ablage und Ton
erst beim Bleiben. Doppler-Tracking und Live-Beobachtung beenden den Scan.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from app.services.rig_control import RigControlError, rig_control

logger = logging.getLogger(__name__)

PAUSE_SECONDS = 10.0
SETTLE_SECONDS = 0.25


@dataclass
class ScanStatus:
    active: bool = False
    # scanning | paused | held | stopped | error
    state: str = "stopped"
    band: str = "all"
    channels: int = 0
    index: int = 0
    cycles: int = 0
    current: dict[str, Any] | None = None
    resume_in: float | None = None
    signal: bool = False
    hits: list[dict[str, Any]] = field(default_factory=list)
    note: str | None = None
    error: str | None = None


class RelaisScanner:
    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._status = ScanStatus()
        self._wake: asyncio.Event | None = None
        self._cmd: str | None = None  # "hold" | "skip"
        self._hold_target: dict[str, Any] | None = None
        self._fresh = True  # kappanhang kennt l SQLFRESH

    @property
    def status(self) -> ScanStatus:
        return self._status

    def status_dict(self) -> dict[str, Any]:
        return asdict(self._status)

    @property
    def active(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self, relais: list[dict[str, Any]], band: str) -> None:
        self.stop()
        self._cmd = None
        self._wake = asyncio.Event()
        self._status = ScanStatus(active=True, state="scanning", band=band, channels=len(relais))
        self._task = asyncio.create_task(self._loop(relais))

    def stop(self, note: str | None = None) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
        self._task = None
        if self._status.active:
            self._status.active = False
            self._status.state = "stopped"
            self._status.resume_in = None
            self._status.note = note
        if self._wake is not None:
            self._wake.set()

    def hold(self) -> bool:
        if not self.active or self._status.current is None:
            return False
        # Gehalten wird das Relais, das beim Klick angezeigt wurde - auch wenn
        # der Scan inzwischen schon einen Kanal weiter ist.
        self._hold_target = self._status.current
        self._cmd = "hold"
        if self._wake is not None:
            self._wake.set()
        return True

    def skip(self) -> bool:
        if not self.active:
            return False
        self._cmd = "skip"
        if self._wake is not None:
            self._wake.set()
        return True

    # ------------------------------------------------------------------
    def _squelch_open(self) -> bool:
        if self._fresh:
            try:
                return rig_control._command("l SQLFRESH").splitlines()[0].strip() == "1"
            except RigControlError as exc:
                if "RPRT -11" not in str(exc):
                    raise
                self._fresh = False
                self._status.note = "kappanhang ohne SQLFRESH – Scan etwas langsamer"
        return rig_control._command("l SQLSTAT").splitlines()[0].strip() == "1"

    async def _listen(self) -> bool:
        """Kurz horchen, ob auf dem gerade eingestellten Kanal ein Signal ist."""
        await asyncio.sleep(SETTLE_SECONDS if self._fresh else 1.2)
        for attempt in range(2):
            if await asyncio.to_thread(self._squelch_open):
                return True
            if attempt == 0:
                await asyncio.sleep(0.3 if self._fresh else 0.6)
        return False

    async def _wait(self, seconds: float) -> None:
        assert self._wake is not None
        try:
            await asyncio.wait_for(self._wake.wait(), seconds)
        except asyncio.TimeoutError:
            pass
        self._wake.clear()

    async def _hold(self, r: dict[str, Any]) -> None:
        r = self._hold_target or r
        self._hold_target = None
        self._status.current = r
        await asyncio.to_thread(rig_control.set_frequency, round(float(r["rx_mhz"]) * 1e6))
        shift = r.get("shift") or "0"
        tone = r.get("ctcss_hz")
        await asyncio.to_thread(
            rig_control.set_repeater,
            shift,
            int(float(r.get("offset_khz") or 0) * 1000) if shift != "0" else None,
            "tone" if tone else "off",
            int(round(float(tone) * 10)) if tone else None,
        )
        self._status.state = "held"
        self._status.active = False
        self._status.resume_in = None

    async def _loop(self, relais: list[dict[str, Any]]) -> None:
        st = self._status
        try:
            await asyncio.to_thread(rig_control.set_mode, "FM")
            # waehrend des Scans simplex/ohne Ton - erst beim Bleiben komplett einstellen
            try:
                await asyncio.to_thread(rig_control.set_repeater, "0")
            except RigControlError:
                pass
            while True:
                for i, r in enumerate(relais):
                    st.index = i
                    st.current = r
                    st.signal = False
                    st.resume_in = None
                    st.state = "scanning"
                    await asyncio.to_thread(rig_control.set_frequency, round(float(r["rx_mhz"]) * 1e6))
                    if self._cmd == "hold":
                        self._cmd = None
                        await self._hold(r)
                        return
                    if self._cmd == "skip":
                        self._cmd = None
                    heard = await self._listen()
                    if self._cmd == "hold":
                        self._cmd = None
                        await self._hold(r)
                        return
                    if not heard:
                        continue
                    # Signal -> Pause
                    st.signal = True
                    st.state = "paused"
                    st.hits = ([{"call": r.get("call"), "rx_mhz": r.get("rx_mhz"), "at": time.time()}] + st.hits)[:10]
                    pause_until = time.monotonic() + PAUSE_SECONDS
                    while True:
                        left = pause_until - time.monotonic()
                        st.resume_in = max(0.0, round(left, 1))
                        if self._cmd == "hold":
                            self._cmd = None
                            await self._hold(r)
                            return
                        if self._cmd == "skip":
                            self._cmd = None
                            break
                        if left <= 0:
                            # nur weiter, wenn der Durchgang vorbei ist
                            st.signal = await asyncio.to_thread(self._squelch_open)
                            if not st.signal:
                                break
                            st.resume_in = 0.0
                        await self._wait(min(0.5, max(0.1, left)) if left > 0 else 1.0)
                st.cycles += 1
        except asyncio.CancelledError:
            raise
        except RigControlError as exc:
            logger.warning("Relais-Scan: %r", exc)
            st.state = "error"
            st.active = False
            st.error = f"IC-705 nicht erreichbar – Scan beendet ({exc})"
        except Exception as exc:  # noqa: BLE001
            logger.exception("Relais-Scan: Fehler")
            st.state = "error"
            st.active = False
            st.error = str(exc)


relais_scanner = RelaisScanner()
