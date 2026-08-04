"""SatNOGS-DB-Alias-Abgleich fuer Satellitennamen.

Ganz neue Satelliten haben in der aktiven TLE-Quelle (Space-Track oder
SatNOGS-Bulk-TLEs) oft noch keinen richtigen Namen, sondern nur einen
generischen Platzhalter wie "OBJECT S". Die SatNOGS-DB-Weboberflaeche
pflegt dagegen von der Amateurfunk-Community zugeordnete Namen -- haeufig
gerade aus TinyGS-Empfangsdaten abgeleitet.

Dieses Modul laedt periodisch die vollstaendige Satellitenliste von
https://db.satnogs.org/api/satellites/ und baut daraus eine
norad_cat_id -> Name Zuordnung, die beim Parsen der aktiven TLE-Datei
verwendet wird, um Platzhalternamen um den bekannten Community-Namen zu
ergaenzen (z. B. "Kosar 1.5 (OBJECT S)").
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

SATNOGS_SATELLITES_URL = "https://db.satnogs.org/api/satellites/?format=json"

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


def load_satnogs_aliases(path: Path) -> dict[str, str]:
    """Liest die zwischengespeicherten SatNOGS-Aliase, gecacht anhand der
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


async def fetch_and_save_satnogs_aliases(path: Path) -> dict[str, Any]:
    """Laedt die vollstaendige SatNOGS-Satellitenliste und speichert eine
    norad_cat_id -> Name Zuordnung als JSON-Cache unter `path`.

    Gibt ein kleines Status-Dict zurueck (aehnlich dem TLE-Update-Log),
    das der Aufrufer optional protokollieren kann.
    """
    started_utc = datetime.now(timezone.utc)

    timeout = httpx.Timeout(30.0, connect=15.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.get(SATNOGS_SATELLITES_URL)
        response.raise_for_status()
        satellites = response.json()

    aliases: dict[str, str] = {}
    for satellite in satellites:
        norad_cat_id = satellite.get("norad_cat_id")
        name = (satellite.get("name") or "").strip()
        if norad_cat_id is None or not name:
            continue
        aliases[str(norad_cat_id)] = name

    payload = {
        "fetched_utc": started_utc.isoformat(),
        "source": SATNOGS_SATELLITES_URL,
        "count": len(aliases),
        "aliases": aliases,
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_file = path.with_suffix(".tmp")
    temporary_file.write_text(json.dumps(payload), encoding="utf-8")
    temporary_file.replace(path)

    _cache["mtime"] = None

    return payload


def enrich_name_with_alias(name: str, norad_id: str, aliases: dict[str, str]) -> str:
    """Ergaenzt `name` um den SatNOGS-Community-Namen, falls `norad_id`
    einen deutlich abweichenden Namen hat, z. B. "Kosar 1.5 (OBJECT S)".

    Ist der SatNOGS-Name bereits (case-insensitiv) in `name` enthalten
    oder umgekehrt, wird nichts veraendert, um bei ohnehin eindeutigen
    Namen (z. B. "ISS (ZARYA)") keine unnoetige Dopplung zu erzeugen.
    """
    alias = aliases.get(norad_id)
    if not alias:
        return name

    alias = alias.strip()
    name_stripped = name.strip()
    if not alias or not name_stripped:
        return name

    alias_lower = alias.lower()
    name_lower = name_stripped.lower()
    if alias_lower in name_lower or name_lower in alias_lower:
        return name

    return f"{alias} ({name_stripped})"
