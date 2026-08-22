"""app/services/transponder_db.py

SatNOGS-DB-Transponder-Cache fuer die Doppler-Korrektur.

Laedt periodisch die vollstaendige Transmitter-Liste von
https://db.satnogs.org/api/transmitters/ und baut daraus eine
norad_cat_id -> Liste-von-Transpondern-Zuordnung (Uplink/Downlink-Frequenzen,
Modus, Invertierung), die fuer die automatische Frequenznachfuehrung
waehrend eines Ueberflugs benoetigt wird.

Folgt demselben Cache-Muster wie `satnogs_aliases.py`: atomarer JSON-Schreib-
vorgang, Laden gecacht anhand der Datei-mtime.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

SATNOGS_TRANSMITTERS_URL = "https://db.satnogs.org/api/transmitters/?format=json"

_cache: dict[str, Any] = {"mtime": None, "value": {}}


def _simplify_transmitter(t: dict[str, Any]) -> dict[str, Any]:
    """Extrahiert die fuer die Doppler-Korrektur relevanten Felder."""
    return {
        "uuid": t.get("uuid"),
        "description": (t.get("description") or "").strip(),
        "mode": t.get("mode"),
        "uplink_mode": t.get("uplink_mode"),
        "invert": bool(t.get("invert")),
        "downlink_low": t.get("downlink_low"),
        "downlink_high": t.get("downlink_high"),
        "uplink_low": t.get("uplink_low"),
        "uplink_high": t.get("uplink_high"),
        "baud": t.get("baud"),
        "status": t.get("status"),
        "alive": bool(t.get("alive")),
    }


async def fetch_and_save_transponders(path: Path) -> dict[str, Any]:
    """Laedt die vollstaendige SatNOGS-Transmitter-Liste und speichert eine
    norad_cat_id -> Transponder-Liste Zuordnung als JSON-Cache unter `path`.

    Gibt ein kleines Status-Dict zurueck (aehnlich dem TLE-Update-Log), das
    der Aufrufer optional protokollieren kann.
    """
    started_utc = datetime.now(timezone.utc)

    timeout = httpx.Timeout(30.0, connect=15.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.get(SATNOGS_TRANSMITTERS_URL)
        response.raise_for_status()
        transmitters = response.json()

    transponders: dict[str, list[dict[str, Any]]] = {}
    for t in transmitters:
        norad_cat_id = t.get("norad_cat_id")
        if norad_cat_id is None:
            continue
        # Ohne mindestens eine Downlink-Frequenz ist der Eintrag fuer die
        # Doppler-Korrektur nutzlos.
        if t.get("downlink_low") is None:
            continue
        key = str(norad_cat_id)
        transponders.setdefault(key, []).append(_simplify_transmitter(t))

    payload = {
        "fetched_utc": started_utc.isoformat(),
        "source": SATNOGS_TRANSMITTERS_URL,
        "satellite_count": len(transponders),
        "transmitter_count": sum(len(v) for v in transponders.values()),
        "transponders": transponders,
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_file = path.with_suffix(".tmp")
    temporary_file.write_text(json.dumps(payload), encoding="utf-8")
    temporary_file.replace(path)

    _cache["mtime"] = None

    return payload


def _read_cache_file(path: Path) -> dict[str, list[dict[str, Any]]]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    transponders = payload.get("transponders", {})
    if not isinstance(transponders, dict):
        return {}
    return transponders


def load_transponders(path: Path) -> dict[str, list[dict[str, Any]]]:
    """Liest die zwischengespeicherten SatNOGS-Transponder
    (norad_cat_id -> Liste von Transponder-Dicts mit Uplink-/Downlink-
    Frequenzen, Modus und Invertierung), gecacht anhand der Datei-mtime.
    """
    if not path.exists():
        return {}

    mtime = path.stat().st_mtime
    if _cache["mtime"] == mtime:
        return _cache["value"]

    transponders = _read_cache_file(path)
    _cache["mtime"] = mtime
    _cache["value"] = transponders
    return transponders


def best_downlink_transponder(
    transponders: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Waehlt aus mehreren Transpondern eines Satelliten einen sinnvollen
    Standard-Transponder aus: bevorzugt 'alive' und Status 'active', sonst
    den ersten Eintrag mit einer Downlink-Frequenz.
    """
    if not transponders:
        return None

    def score(t: dict[str, Any]) -> tuple[int, int]:
        return (1 if t.get("status") == "active" else 0, 1 if t.get("alive") else 0)

    return max(transponders, key=score)
