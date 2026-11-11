"""app/services/amsat_status.py

AMSAT Live OSCAR Satellite Status (https://status.amsat.org/).

Funkamateure melden dort nach jedem Ueberflug, ob ein Satellit in einer
bestimmten Betriebsart gehoert wurde ("Heard"), nur Telemetrie/Bake sendete
("Telemetry Only") oder stumm blieb ("Not Heard"). Die Eintraege heissen
z. B. "ISS_[FM]", "RS-44_[V/u]" oder "AO-7_[V/a]" - der Teil in eckigen
Klammern ist die Betriebsart.

Dieses Modul
- holt die Berichte ueber die offizielle JSON-API (/api/v1/reports.php),
  mit kurzem In-Memory-Cache, um den AMSAT-Server zu schonen,
- fasst sie je Satellit + Betriebsart zusammen (letzter Status, Zaehler,
  wer zuletzt gemeldet hat),
- ordnet jeder Betriebsart den passenden SatNOGS-Transponder und die
  IC-705-Betriebsart zu (fuer den Knopf "IC-705").
"""
from __future__ import annotations

import logging
import re
import time
from collections import defaultdict
from datetime import datetime
from typing import Any

import httpx

from app.services.rig_control import rig_mode_for

logger = logging.getLogger(__name__)

AMSAT_REPORTS_URL = "https://status.amsat.org/api/v1/reports.php"
CACHE_TTL_SECONDS = 600  # AMSAT-Daten hoechstens alle 10 Minuten neu holen

_cache: dict[int, tuple[float, list[dict[str, Any]]]] = {}

# Amateurfunkbaender, die der IC-705 abdeckt, je Buchstabe der AMSAT-Notation
_BANDS_HZ = {
    "h": (21_000_000, 21_450_000),
    "a": (28_000_000, 29_700_000),
    "v": (144_000_000, 148_000_000),
    "u": (430_000_000, 440_000_000),
}
IC705_MAX_HZ = 470_000_000

_STATUS_LABELS = {
    "Heard": "Aktiv",
    "Crew Active": "Crew aktiv",
    "Telemetry Only": "Nur Bake/TLM",
    "Not Heard": "Nicht gehört",
}

_NAME_RE = re.compile(r"^(?P<sat>.+?)_\[(?P<mode>.+)\]$")


async def fetch_reports(hours: int = 24) -> list[dict[str, Any]]:
    """Berichte der letzten `hours` Stunden (neueste zuerst), gecacht."""
    hours = max(1, min(int(hours), 72))
    now = time.time()
    cached = _cache.get(hours)
    if cached and cached[0] > now:
        return cached[1]

    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
        response = await client.get(
            AMSAT_REPORTS_URL,
            params={"hours": hours, "limit": 500},
            headers={"User-Agent": "OrbitHub (DL7AG) amsat-live"},
        )
        response.raise_for_status()
        data = response.json().get("data") or []

    _cache[hours] = (now + CACHE_TTL_SECONDS, data)
    return data


def split_name(name: str) -> tuple[str, str]:
    """'RS-44_[V/u]' -> ('RS-44', 'V/u'); Unterstriche werden zu Leerzeichen."""
    match = _NAME_RE.match(name or "")
    if not match:
        return (name or "").replace("_", " "), ""
    return match.group("sat").replace("_", " "), match.group("mode").replace("_", " ")


def summarize(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fasst Berichte je AMSAT-Eintrag (Satellit + Betriebsart) zusammen."""
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for report in reports:
        if report.get("name"):
            groups[report["name"]].append(report)

    entries = []
    for name, items in groups.items():
        items.sort(key=lambda r: r.get("observation_time") or "", reverse=True)
        latest = items[0]
        counts: dict[str, int] = defaultdict(int)
        for r in items:
            counts[r.get("report") or "?"] += 1
        last_heard = next(
            (r for r in items if r.get("report") in ("Heard", "Crew Active", "Telemetry Only")),
            None,
        )
        sat, mode = split_name(name)
        entries.append(
            {
                "name": name,
                "satellite": sat,
                "mode": mode,
                "display_name": latest.get("satellite_display_name") or f"{sat} [{mode}]",
                "norad_id": str(latest["norad_cat_id"]) if latest.get("norad_cat_id") else None,
                "status": latest.get("report"),
                "status_label": _STATUS_LABELS.get(latest.get("report"), latest.get("report")),
                "latest_time": latest.get("observation_time"),
                "latest_callsign": latest.get("callsign"),
                "latest_grid": latest.get("grid_square"),
                "last_heard_time": last_heard.get("observation_time") if last_heard else None,
                "last_heard_callsign": last_heard.get("callsign") if last_heard else None,
                "count_heard": counts.get("Heard", 0) + counts.get("Crew Active", 0),
                "count_tlm": counts.get("Telemetry Only", 0),
                "count_not_heard": counts.get("Not Heard", 0),
                "count_total": len(items),
            }
        )
    return entries


def _in_band(hz: float | None, band: str) -> bool:
    if hz is None:
        return False
    low, high = _BANDS_HZ[band]
    return low <= hz <= high


def _ham_band_of(hz: float | None) -> str | None:
    for band in _BANDS_HZ:
        if _in_band(hz, band):
            return band
    return None


def match_transponder(mode: str, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Waehlt fuer eine AMSAT-Betriebsart den passenden SatNOGS-Transponder.

    Gibt {"transponder": ..., "rig_mode": "FM", "downlink_hz": ..., "note": ...}
    oder None zurueck, wenn nichts Passendes im IC-705-Bereich gefunden wurde.
    """
    tag = (mode or "").strip()
    tag_upper = tag.upper()
    if "DVB" in tag_upper or tag_upper in ("NB", "WB"):
        return None  # Digital-TV bzw. QO-100: mit dem IC-705 nicht empfangbar
    usable = [
        t for t in candidates
        if t.get("downlink_low") and t["downlink_low"] <= IC705_MAX_HZ
    ]
    if not usable:
        return None

    def base_score(t: dict[str, Any]) -> int:
        score = 0
        if t.get("status") == "active":
            score += 4
        if t.get("alive"):
            score += 2
        if _ham_band_of(t.get("downlink_low")):
            score += 3
        return score

    def tmode(t: dict[str, Any]) -> str:
        return (t.get("mode") or "").upper()

    def desc(t: dict[str, Any]) -> str:
        return (t.get("description") or "").upper()

    rig_mode: str | None = None
    scored: list[tuple[int, dict[str, Any]]] = []

    linear = re.fullmatch(r"([A-Za-z])/([A-Za-z])", tag)
    if linear:
        # Uplink/Downlink, z. B. V/u -> Downlink im 70-cm-Band
        band = linear.group(2).lower()
        if band not in _BANDS_HZ:
            return None
        for t in usable:
            if not _in_band(t.get("downlink_low"), band):
                continue
            s = base_score(t)
            if tmode(t) in ("USB", "LSB", "SSB") or "LIN" in desc(t) or "TRANSPONDER" in desc(t):
                s += 10
            if tmode(t) in ("USB", "LSB", "SSB"):
                s += 2  # SSB-Transponder vor CW-Variante bei gleicher Frequenz
            if t.get("uplink_low"):
                s += 3
            if tmode(t) == "CW" and "BEACON" in desc(t):
                s -= 5
            scored.append((s, t))
        rig_mode = "USB"
    elif tag_upper in ("FM", "CREW"):
        for t in usable:
            s = base_score(t)
            if tmode(t) in ("FM", "FMN"):
                s += 10
            if tag_upper == "FM":
                if t.get("uplink_low"):
                    s += 6
                if "REPEATER" in desc(t) or "VOICE" in desc(t) or "TRANSCEIVER" in desc(t):
                    s += 3
            else:  # Crew: Sprechfunk der Besatzung auf 145,800 MHz
                if _in_band(t.get("downlink_low"), "v"):
                    s += 8
                if abs((t.get("downlink_low") or 0) - 145_800_000) < 5_000:
                    s += 8
            scored.append((s, t))
        rig_mode = "FM"
    elif "SSTV" in tag_upper or "SSDV" in tag_upper:
        for t in usable:
            s = base_score(t)
            if "SSTV" in tmode(t) or "SSTV" in desc(t) or "IMAG" in desc(t) or "SSDV" in desc(t):
                s += 10
            if _in_band(t.get("downlink_low"), "v"):
                s += 2
            scored.append((s, t))
        rig_mode = "FM"
    elif "DIGI" in tag_upper:
        band = "u" if "UHF" in tag_upper else "v" if "VHF" in tag_upper else None
        for t in usable:
            if band and not _in_band(t.get("downlink_low"), band):
                continue
            s = base_score(t)
            if "APRS" in desc(t) or "DIGI" in desc(t):
                s += 10
            if tmode(t) in ("AFSK", "FSK", "GFSK", "GMSK"):
                s += 4
            scored.append((s, t))
        rig_mode = "FM"
    elif "TLM" in tag_upper or "BEACON" in tag_upper:
        band = "u" if "UHF" in tag_upper else "v" if "VHF" in tag_upper else None
        for t in usable:
            if band and not _in_band(t.get("downlink_low"), band):
                continue
            s = base_score(t)
            if "BEACON" in desc(t) or "TLM" in desc(t) or "TELEMETRY" in desc(t):
                s += 8
            scored.append((s, t))
    else:
        # Music, CODEC2, ... - bestes aktives Amateurfunk-Signal
        for t in usable:
            s = base_score(t)
            if tag_upper.split()[0] in desc(t) or tag_upper.split()[0] in tmode(t):
                s += 8
            scored.append((s, t))

    if not scored:
        return None
    scored.sort(key=lambda item: item[0], reverse=True)
    best = scored[0][1]
    if rig_mode is None:
        rig_mode, _ = rig_mode_for(best.get("mode") or "")
    return {
        "transponder": best,
        "rig_mode": rig_mode,
        "downlink_hz": best.get("downlink_low"),
        "uplink_hz": best.get("uplink_low"),
    }


def normalize_name(name: str) -> str:
    """'Foresail-1p' / 'FORESAIL 1P' -> 'FORESAIL1P' fuer den Namensabgleich."""
    return re.sub(r"[^A-Z0-9]", "", (name or "").upper())


# AMSAT-OSCAR-Bezeichnungen, die weder AMSAT (keine NORAD-ID im Bericht) noch
# SatNOGS (fehlt in "names") einem Satelliten zuordnen. Ergaenzbar ueber
# data/amsat-name-map.json, z. B. {"SO-127": "68446"}.
AMSAT_NAME_OVERRIDES = {
    "SO-127": "68446",  # HADES-SA (SpinnyONE), PocketQube, AMSAT-EA
}


def load_name_overrides(path: Any) -> dict[str, str]:
    """Eingebaute Zuordnungen + optionale Datei (Datei hat Vorrang)."""
    import json

    merged = {normalize_name(k): str(v) for k, v in AMSAT_NAME_OVERRIDES.items()}
    try:
        if path is not None and path.exists():
            extra = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(extra, dict):
                merged.update({normalize_name(k): str(v) for k, v in extra.items()})
    except (OSError, ValueError) as exc:
        logger.warning("amsat-name-map.json nicht lesbar: %r", exc)
    return merged


def resolve_follow_id(norad_id: str | None, follow_ids: dict[str, str]) -> str | None:
    """Vorlaeufige SatNOGS-Nummer (98xxx) -> echte NORAD-Nummer, falls bekannt."""
    if not norad_id:
        return norad_id
    seen = set()
    while norad_id in follow_ids and norad_id not in seen:
        seen.add(norad_id)
        norad_id = follow_ids[norad_id]
    return norad_id


def build_name_index(
    records: list[Any],
    alt_names: dict[str, str],
    aliases: dict[str, str],
    follow_ids: dict[str, str] | None = None,
) -> dict[str, str]:
    """Normalisierter Satellitenname -> NORAD-ID (nur eindeutige Namen).

    Quellen: TLE-Katalogname (ohne Klammerzusatz), SatNOGS-Name und
    SatNOGS-Alternativnamen (z. B. Amateurfunk-Bezeichnungen wie "RS95S").
    Vorlaeufige SatNOGS-Nummern werden vorher auf die echte Nummer umgesetzt,
    damit z. B. "Marina" nicht wegen zweier Nummern als mehrdeutig gilt.
    """
    index: dict[str, set[str]] = defaultdict(set)
    follow_ids = follow_ids or {}

    def add(name: str, norad_id: str) -> None:
        key = normalize_name(name)
        if len(key) >= 3:
            index[key].add(resolve_follow_id(str(norad_id), follow_ids))

    for record in records:
        add(record.name.split("(")[0], record.norad_id)
    for norad_id, name in (aliases or {}).items():
        add(str(name), str(norad_id))
    for norad_id, raw in (alt_names or {}).items():
        for part in re.split(r"[,;/]", str(raw)):
            add(part, str(norad_id))
    return {key: next(iter(ids)) for key, ids in index.items() if len(ids) == 1}


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
