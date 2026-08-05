"""TinyGS-Alias-Abgleich fuer Satellitennamen.

Analog zu satnogs_aliases.py: TinyGS identifiziert neu gestartete,
noch nicht offiziell benannte Satelliten oft schneller als SatNOGS DB,
weil die Namen direkt aus den ersten erfolgreichen Funkempfaengen der
Community stammen (z. B. "ET-001A" fuer eine NORAD-ID, bevor SatNOGS DB
oder Space-Track ueberhaupt einen Namen kennen).

Dieses Modul laedt periodisch die vollstaendige, synchron gehaltene
TLE-Liste von https://api.tinygs.com/v1/tinygs_supported.txt und baut
daraus eine norad_cat_id -> Name Zuordnung, die beim Parsen der aktiven
TLE-Datei verwendet wird, um Platzhalternamen zu ergaenzen.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

TINYGS_SUPPORTED_URL = "https://api.tinygs.com/v1/tinygs_supported.txt"

_cache: dict[str, Any] = {"mtime": None, "value": {}}


def _read_cache_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    aliases = payload.get("aliases", {})
    if not isinstance(aliases, dict):
        return {}
    return aliases


def load_tinygs_aliases(path: Path) -> dict[str, str]:
    """Liest die zwischengespeicherten TinyGS-Aliase, gecacht anhand der
    Datei-mtime. Gibt ein leeres Dict zurueck, solange noch kein
    erfolgreicher Abgleich stattgefunden hat."""
    if not path.exists():
        return {}

    mtime = path.stat().st_mtime
    if _cache["mtime"] == mtime:
        return _cache["value"]

    aliases = _read_cache_file(path)
    _cache["mtime"] = mtime
    _cache["value"] = aliases
    return aliases


def _parse_tinygs_supported(text: str) -> dict[str, str]:
    """Parst das TinyGS-3-Zeilen-TLE-Textformat (Name/Zeile1/Zeile2) in
    eine norad_cat_id -> Name Zuordnung."""
    lines = [line.rstrip("\r\n") for line in text.splitlines()]
    aliases: dict[str, str] = {}
    index = 0
    while index < len(lines):
        name = lines[index].strip()
        if not name:
            index += 1
            continue

        if index + 2 >= len(lines):
            break

        line1 = lines[index + 1]
        line2 = lines[index + 2]

        if line1.startswith("1 ") and line2.startswith("2 ") and len(line1) >= 7:
            norad_id = line1[2:7].strip()
            if norad_id:
                aliases[norad_id] = name
            index += 3
            continue

        index += 1

    return aliases


async def fetch_and_save_tinygs_aliases(path: Path) -> dict[str, Any]:
    """Laedt die vollstaendige TinyGS-Satellitenliste und speichert eine
    norad_cat_id -> Name Zuordnung als JSON-Cache unter `path`.

    Gibt ein kleines Status-Dict zurueck (aehnlich dem TLE-Update-Log),
    das der Aufrufer optional protokollieren kann.
    """
    started_utc = datetime.now(timezone.utc)

    timeout = httpx.Timeout(30.0, connect=15.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.get(TINYGS_SUPPORTED_URL)
        response.raise_for_status()
        text = response.text

    aliases = _parse_tinygs_supported(text)

    payload = {
        "fetched_utc": started_utc.isoformat(),
        "source": TINYGS_SUPPORTED_URL,
        "count": len(aliases),
        "aliases": aliases,
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_file = path.with_suffix(".tmp")
    temporary_file.write_text(json.dumps(payload), encoding="utf-8")
    temporary_file.replace(path)

    _cache["mtime"] = None

    return payload
