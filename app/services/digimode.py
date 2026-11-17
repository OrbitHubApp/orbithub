"""Anbindung an den Digimode-Dienst (tools/digimode/digimode_server.py).

Der Dienst laeuft auf dem Host (PipeWire-Audio von kappanhang, WSJT-X-
Decoder) und wird hier nur per HTTP angesprochen. Ausserdem: Bandplan mit
den ueblichen Frequenzen (Dial, USB) fuer FT8, FT4 und WSPR.
"""
from __future__ import annotations

import os

import httpx

DIGIMODE_URL = os.environ.get("DIGIMODE_URL", "http://host.docker.internal:8767").rstrip("/")


class DigimodeError(Exception):
    pass


# Dial-Frequenzen in Hz (USB). Quelle: WSJT-X-Standardliste, IARU Region 1.
BANDS: list[dict] = [
    {"band": "160m", "FT8": 1_840_000, "WSPR": 1_836_600},
    {"band": "80m", "FT8": 3_573_000, "FT4": 3_575_000, "WSPR": 3_568_600},
    {"band": "60m", "FT8": 5_357_000, "WSPR": 5_364_700},
    {"band": "40m", "FT8": 7_074_000, "FT4": 7_047_500, "WSPR": 7_038_600},
    {"band": "30m", "FT8": 10_136_000, "FT4": 10_140_000, "WSPR": 10_138_700},
    {"band": "20m", "FT8": 14_074_000, "FT4": 14_080_000, "WSPR": 14_095_600},
    {"band": "17m", "FT8": 18_100_000, "FT4": 18_104_000, "WSPR": 18_104_600},
    {"band": "15m", "FT8": 21_074_000, "FT4": 21_140_000, "WSPR": 21_094_600},
    {"band": "12m", "FT8": 24_915_000, "FT4": 24_919_000, "WSPR": 24_924_600},
    {"band": "10m", "FT8": 28_074_000, "FT4": 28_180_000, "WSPR": 28_124_600},
    {"band": "6m", "FT8": 50_313_000, "FT4": 50_318_000, "WSPR": 50_293_000},
    {"band": "2m", "FT8": 144_174_000, "FT4": 144_170_000, "WSPR": 144_489_000},
    {"band": "70cm", "FT8": 432_174_000, "WSPR": 432_300_000},
]

MODES = ("FT8", "FT4", "WSPR")


def dial_for(mode: str, band: str) -> int | None:
    for entry in BANDS:
        if entry["band"] == band:
            return entry.get(mode)
    return None


async def _request(method: str, path: str, payload: dict | None = None, timeout: float = 4.0) -> dict:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.request(method, DIGIMODE_URL + path, json=payload)
    except httpx.HTTPError as exc:
        raise DigimodeError(
            f"Digimode-Dienst nicht erreichbar ({DIGIMODE_URL}): {exc.__class__.__name__}. "
            "Läuft digimode.service auf dem Host?"
        ) from exc
    try:
        data = resp.json()
    except ValueError as exc:
        raise DigimodeError(f"Unerwartete Antwort vom Digimode-Dienst ({resp.status_code}).") from exc
    if resp.status_code >= 400:
        raise DigimodeError(str(data.get("error") or f"Fehler {resp.status_code}"))
    return data


async def status() -> dict:
    return await _request("GET", "/status")


async def decodes(since: int = 0) -> dict:
    return await _request("GET", f"/decodes?since={int(since)}")


async def start(payload: dict) -> dict:
    return await _request("POST", "/start", payload)


async def stop() -> dict:
    return await _request("POST", "/stop", {})


async def configure(payload: dict) -> dict:
    return await _request("POST", "/config", payload)


TX_ACTIONS = ("config", "cq", "call", "next", "halt", "clear")


async def tx(action: str, payload: dict) -> dict:
    if action not in TX_ACTIONS:
        raise DigimodeError("Unbekannte Sendefunktion.")
    return await _request("POST", f"/tx/{action}", payload)


async def qso_log() -> dict:
    return await _request("GET", "/log")


async def adif() -> str:
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(DIGIMODE_URL + "/log.adi")
    except httpx.HTTPError as exc:
        raise DigimodeError(f"Digimode-Dienst nicht erreichbar: {exc.__class__.__name__}") from exc
    return resp.text


async def stop_quietly() -> bool:
    """Beendet den Digimode-Empfang, falls er laeuft (z. B. bei Doppler-Start).
    Fehler werden ignoriert. Gibt True zurueck, wenn er lief."""
    try:
        state = await _request("GET", "/status", timeout=1.5)
        if state.get("running"):
            await _request("POST", "/stop", {}, timeout=1.5)
            return True
    except DigimodeError:
        pass
    return False
