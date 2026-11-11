"""app/services/satnogs_tle.py

Ersatz-Bahndaten von SatNOGS fuer Satelliten, die (noch) nicht im
Haupt-TLE-Katalog (z. B. Space-Track "aktiv") stehen.

Typischer Fall: ein frisch gestarteter Amateurfunksatellit hat noch keine
offizielle NORAD-Nummer. SatNOGS fuehrt ihn dann unter einer vorlaeufigen
Nummer (98xxx) und veroeffentlicht trotzdem Bahndaten - oft vom Betreiber
oder aus eigenen Messungen. Ebenso hilft SatNOGS bei Objekten, die im
Aktiv-Satz der Hauptquelle fehlen.

Die Liste (https://db.satnogs.org/api/tle/, ~1.700 Eintraege, ~0,5 MB)
wird taeglich zusammen mit dem SatNOGS-Namensabgleich geholt. Veraltete
Bahndaten (Epoche aelter als MAX_EPOCH_AGE_DAYS) werden ignoriert - meist
ist der Satellit dann verglueht oder die Daten sind unbrauchbar.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from app.models.tle_record import TLERecord

SATNOGS_TLE_URL = "https://db.satnogs.org/api/tle/?format=json"
MAX_EPOCH_AGE_DAYS = 30

_cache: dict[str, Any] = {"mtime": None, "value": {}}


async def fetch_and_save_satnogs_tles(path: Path) -> int:
    """Laedt alle SatNOGS-TLEs und speichert sie als JSON-Cache. Gibt die Anzahl zurueck."""
    timeout = httpx.Timeout(60.0, connect=15.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.get(SATNOGS_TLE_URL)
        response.raise_for_status()
        items = response.json()

    tles = {}
    for item in items:
        norad = item.get("norad_cat_id")
        line1 = (item.get("tle1") or "").strip()
        line2 = (item.get("tle2") or "").strip()
        if norad is None or not line1.startswith("1 ") or not line2.startswith("2 "):
            continue
        name = (item.get("tle0") or "").strip()
        if name.startswith("0 "):
            name = name[2:]
        tles[str(norad)] = {
            "name": name or f"NORAD {norad}",
            "line1": line1,
            "line2": line2,
            "source": item.get("tle_source"),
            "updated": item.get("updated"),
        }

    payload = {
        "fetched_utc": datetime.now(timezone.utc).isoformat(),
        "source": SATNOGS_TLE_URL,
        "count": len(tles),
        "tles": tles,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_file = path.with_suffix(".tmp")
    temporary_file.write_text(json.dumps(payload), encoding="utf-8")
    temporary_file.replace(path)
    _cache["mtime"] = None
    return len(tles)


def load_satnogs_tles(path: Path) -> dict[str, dict[str, Any]]:
    """norad_cat_id -> {name, line1, line2, ...}, gecacht anhand der Datei-mtime."""
    if not path.exists():
        return {}
    mtime = path.stat().st_mtime
    if _cache["mtime"] == mtime:
        return _cache["value"]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        tles = payload.get("tles", {})
        if not isinstance(tles, dict):
            tles = {}
    except (OSError, json.JSONDecodeError):
        tles = {}
    _cache["mtime"] = mtime
    _cache["value"] = tles
    return tles


def satnogs_record(norad_id: str | None, path: Path) -> TLERecord | None:
    """Ersatz-TLE-Datensatz von SatNOGS, sofern vorhanden und nicht veraltet."""
    if not norad_id:
        return None
    item = load_satnogs_tles(path).get(str(norad_id))
    if not item:
        return None
    record = TLERecord(name=item["name"], line1=item["line1"], line2=item["line2"])
    epoch = record.epoch_datetime
    if epoch is None:
        return None
    age_days = (datetime.now(timezone.utc) - epoch).total_seconds() / 86400
    if age_days > MAX_EPOCH_AGE_DAYS:
        return None
    return record
