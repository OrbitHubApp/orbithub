"""Erkennung neu aufgetauchter, amateurfunk-relevanter Satelliten.

Die Bulk-TLE-Quellen (Space-Track, SatNOGS) enthalten so gut wie jedes
katalogisierte Objekt -- auch druckfrische Nutzlasten, die offiziell
noch keinen Namen haben und nur als "OBJECT XX" oder "TBA - TO BE
ASSIGNED" auftauchen. Bahndaten sind fuer solche Objekte also meist
schon vorhanden, sie sind nur unauffindbar, solange man die NORAD-ID
nicht kennt.

Communities wie TinyGS identifizieren genau solche Objekte oft
innerhalb weniger Tage per Funkempfang (siehe tinygs_aliases.py), und
SatNOGS DB uebernimmt bestaetigte Namen etwas spaeter (siehe
satnogs_aliases.py). Dieses Modul beobachtet den regulaeren TLE-Abgleich
(siehe update_tle() in main.py) und haelt fest, welche neu
aufgetauchten NORAD-IDs bereits einen von der Community zugeordneten
Namen haben -- das sind die Kandidaten fuer die "Neue Satelliten"-Seite.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

NEW_SATELLITE_MAX_AGE_DAYS = 60


def _read_store(path: Path) -> list:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    if not isinstance(payload, list):
        return []
    return payload


def _write_store(path: Path, entries: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_file = path.with_suffix(".tmp")
    temporary_file.write_text(
        json.dumps(entries, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary_file.replace(path)


def load_new_satellites(path: Path) -> list:
    """Laedt die erkannten neuen Satelliten, neueste zuerst."""
    entries = _read_store(path)
    return sorted(
        entries,
        key=lambda entry: entry.get("first_seen_utc", ""),
        reverse=True,
    )


def _is_recent_launch(
    norad_id: str,
    satnogs_launched: dict,
    max_age_days: int = NEW_SATELLITE_MAX_AGE_DAYS,
) -> bool:
    """Prueft, ob ein Objekt laut SatNOGS-Startdatum jung genug ist,
    um noch als 'neu entdeckt' zu gelten. Ohne bekanntes Startdatum
    wird das Objekt sicherheitshalber ausgeschlossen."""
    launched_at = satnogs_launched.get(norad_id)
    if not launched_at:
        return False
    try:
        launched_dt = datetime.fromisoformat(
            launched_at.replace("Z", "+00:00")
        )
    except ValueError:
        return False
    age_days = (datetime.now(timezone.utc) - launched_dt).days
    return 0 <= age_days <= max_age_days


def record_new_satellites(
    new_ids,
    new_by_norad: dict,
    satnogs_aliases: dict,
    tinygs_aliases: dict,
    satnogs_launched: dict,
    path: Path,
) -> list:
    """Prueft neu aufgetauchte NORAD-IDs auf einen bekannten
    Community-Namen (TinyGS zuerst, dann SatNOGS DB) und ergaenzt den
    persistenten Kandidaten-Speicher. Gibt die tatsaechlich neu
    hinzugefuegten Eintraege zurueck.

    Objekte ohne bekannten Community-Namen (die grosse Mehrheit --
    Raketenstufen, Trip-/Debris-Objekte, frisch gestartete Starlinks
    usw.) werden bewusst NICHT aufgenommen, damit die Seite eine kurze,
    relevante Liste bleibt statt im taeglichen Katalograuschen unterzugehen.
    """
    existing = _read_store(path)
    known_ids = {entry.get("norad_id") for entry in existing}

    added: list = []
    now_iso = datetime.now(timezone.utc).isoformat()

    for norad_id in sorted(new_ids):
        if norad_id in known_ids:
            continue

        alias_name = tinygs_aliases.get(norad_id)
        source = "tinygs"
        if not alias_name:
            alias_name = satnogs_aliases.get(norad_id)
            source = "satnogs"

        if not alias_name:
            continue

        if not _is_recent_launch(norad_id, satnogs_launched):
            continue

        record = new_by_norad.get(norad_id)
        if record is None:
            continue

        entry = {
            "norad_id": norad_id,
            "name": record.name,
            "alias": alias_name,
            "source": source,
            "line1": record.line1,
            "line2": record.line2,
            "first_seen_utc": now_iso,
            "reviewed": False,
        }
        existing.append(entry)
        added.append(entry)

    if added:
        _write_store(path, existing)

    return added


def mark_reviewed(path: Path, norad_id: str) -> list:
    """Markiert einen Kandidaten als gesichtet (z. B. nach dem
    Uebernehmen in die Favoriten)."""
    entries = _read_store(path)
    changed = False
    for entry in entries:
        if entry.get("norad_id") == norad_id and not entry.get("reviewed"):
            entry["reviewed"] = True
            changed = True

    if changed:
        _write_store(path, entries)

    return entries
