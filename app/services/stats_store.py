"""
Persistenter Speicher für Statistik-Daten.

Hält zwei JSON-Lines-Protokolle:
- Verlauf der System-Metriken des Raspberry Pi (CPU, RAM, Temperatur, ...)
- Verlauf der TLE-Aktualisierungen (Quelle, Erfolg, Dauer, Fehlermeldung)

Beide Protokolle werden regelmäßig auf eine Aufbewahrungsfrist gekürzt,
damit die Dateien auf dem Pi nicht unbegrenzt wachsen.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.config import DATA_DIR

SYSTEM_METRICS_LOG = DATA_DIR / "system_metrics_log.jsonl"
TLE_UPDATE_LOG = DATA_DIR / "tle_update_log.jsonl"

SYSTEM_METRICS_RETENTION_DAYS = 30
TLE_UPDATE_RETENTION_DAYS = 90


def _append_entry(path: Path, entry: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _read_entries(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    entries: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    return entries


def _entry_timestamp(entry: dict[str, Any]) -> datetime | None:
    raw = entry.get("timestamp_utc")
    if not raw:
        return None

    try:
        value = datetime.fromisoformat(raw)
    except ValueError:
        return None

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)

    return value


def _prune_log(path: Path, retention_days: int) -> None:
    entries = _read_entries(path)
    if not entries:
        return

    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    kept = [
        entry
        for entry in entries
        if _entry_timestamp(entry) is None or _entry_timestamp(entry) >= cutoff
    ]

    if len(kept) == len(entries):
        return

    tmp_path = path.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8") as fh:
        for entry in kept:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    tmp_path.replace(path)


def append_system_metrics_sample(sample: dict[str, Any]) -> None:
    """Fügt eine System-Metriken-Momentaufnahme zum Verlauf hinzu."""
    entry = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        **sample,
    }
    _append_entry(SYSTEM_METRICS_LOG, entry)


def append_tle_update_event(event: dict[str, Any]) -> None:
    """Fügt das Ergebnis einer TLE-Aktualisierung zum Verlauf hinzu."""
    entry = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        **event,
    }
    _append_entry(TLE_UPDATE_LOG, entry)


def read_system_metrics(hours: int = 24) -> list[dict[str, Any]]:
    """Liefert die System-Metriken-Samples der letzten `hours` Stunden."""
    entries = _read_entries(SYSTEM_METRICS_LOG)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    return [
        entry
        for entry in entries
        if _entry_timestamp(entry) is not None and _entry_timestamp(entry) >= cutoff
    ]


def read_tle_update_events(days: int = 7) -> list[dict[str, Any]]:
    """Liefert die TLE-Aktualisierungs-Ereignisse der letzten `days` Tage."""
    entries = _read_entries(TLE_UPDATE_LOG)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return [
        entry
        for entry in entries
        if _entry_timestamp(entry) is not None and _entry_timestamp(entry) >= cutoff
    ]


def prune_old_entries() -> None:
    """Kürzt beide Protokolle auf ihre jeweilige Aufbewahrungsfrist."""
    _prune_log(SYSTEM_METRICS_LOG, SYSTEM_METRICS_RETENTION_DAYS)
    _prune_log(TLE_UPDATE_LOG, TLE_UPDATE_RETENTION_DAYS)
