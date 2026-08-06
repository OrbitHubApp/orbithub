"""Live-Status einer eigenen TinyGS-Empfangsstation.

Nutzt den (inoffiziellen, aber von der TinyGS-Community fuer
Home-Assistant-Integrationen verwendeten) JSON-Endpunkt
``api.tinygs.com/v1/station/<ID>``. Es gibt dafuer keine offizielle
Dokumentation, das Format wurde anhand oeffentlicher Beispiele
(Home-Assistant-Sensoren) ermittelt.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

TINYGS_STATION_STATUS_URL = "https://api.tinygs.com/v1/station/{station_id}"


def tinygs_station_page_url(station_id: str) -> str:
    """Baut den Link zur oeffentlichen TinyGS-Stationsseite."""
    return f"https://tinygs.com/station/{station_id}"


def _coerce_online(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "on", "online", "ok")
    return False


async def fetch_tinygs_station_status(
    client: httpx.AsyncClient, station_id: str
) -> dict[str, Any]:
    """Fragt den Live-Status einer TinyGS-Station ab.

    Bei jedem Fehler (Timeout, HTTP-Fehler, unerwartete Antwort) wird ein
    Status mit ``online=False`` und passender ``error``-Meldung
    zurueckgegeben, damit das Dashboard niemals wegen einer nicht
    erreichbaren Station abstuerzt.
    """
    fetched_utc = datetime.now(timezone.utc)
    result: dict[str, Any] = {
        "station_id": station_id,
        "page_url": tinygs_station_page_url(station_id),
        "fetched_utc": fetched_utc.isoformat(),
        "online": False,
        "satellite": None,
        "last_packet_time": None,
        "confirmed_packets": None,
        "error": None,
    }

    url = TINYGS_STATION_STATUS_URL.format(station_id=station_id)
    try:
        response = await client.get(url)
        response.raise_for_status()
        data = response.json()
    except Exception as exc:  # noqa: BLE001 - Netzwerk darf nie crashen
        result["error"] = str(exc) or exc.__class__.__name__
        return result

    if not isinstance(data, dict):
        result["error"] = "Unerwartetes Antwortformat"
        return result

    result["online"] = _coerce_online(data.get("status"))
    result["satellite"] = data.get("satellite") or None

    raw_last_packet = data.get("lastPacketTime")
    if raw_last_packet is not None:
        try:
            result["last_packet_time"] = datetime.fromtimestamp(
                float(raw_last_packet) / 1000, tz=timezone.utc
            ).isoformat()
        except (TypeError, ValueError):
            result["last_packet_time"] = None

    try:
        result["confirmed_packets"] = int(data.get("confirmedPackets"))
    except (TypeError, ValueError):
        result["confirmed_packets"] = None

    return result


async def fetch_all_tinygs_station_statuses(
    station_ids: tuple[str, ...],
) -> dict[str, dict[str, Any]]:
    """Fragt den Status mehrerer Stationen ab (jede unabhaengig, Fehler isoliert)."""
    if not station_ids:
        return {}

    timeout = httpx.Timeout(10.0, connect=5.0)
    results: dict[str, dict[str, Any]] = {}
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        for station_id in station_ids:
            results[station_id] = await fetch_tinygs_station_status(client, station_id)

    return results
