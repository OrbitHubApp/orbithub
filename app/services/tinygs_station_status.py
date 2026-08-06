"""Verweis auf die eigene TinyGS-Empfangsstation.

Der TinyGS-Betreiber stellt bewusst keine offene API fuer den Live-Status
einzelner Stationen bereit (der frueher von der Community genutzte
Endpunkt ist verschwunden, der aktuelle liegt hinter einem Bot-Schutz,
der keine automatisierten Abfragen zulaesst). Deshalb wird hier nur noch
der Link zur jeweiligen Stationsseite gebaut, kein Live-Status abgefragt.
"""

from __future__ import annotations


def tinygs_station_page_url(station_id: str) -> str:
    """Baut den Link zur TinyGS-Stationsseite (Web-App)."""
    return f"https://app.tinygs.com/station/{station_id}"
