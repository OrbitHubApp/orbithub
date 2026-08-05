"""Vordefinierte Satelliten-Pakete fuer die Ueberfluege-Uebersicht.

Ein Paket ist eine automatisch gepflegte Liste von NORAD-IDs, die sich
anstelle der eigenen Favoriten auf der Ueberfluege-Seite anzeigen laesst
(z. B. "alle von TinyGS aktuell getrackten Satelliten"). Die eigenen
Favoriten (favorites_store.py) bleiben davon vollstaendig unberuehrt.
"""

from __future__ import annotations

from app.config import TINYGS_ALIASES_FILE
from app.services.tinygs_aliases import load_tinygs_aliases

PACKAGE_LABELS: dict[str, str] = {
    "tinygs": "TinyGS",
}


def load_package_norad_ids(package_id: str) -> list[str]:
    """Liefert die NORAD-IDs eines Pakets. Unbekannte Pakete ergeben eine leere Liste."""
    if package_id == "tinygs":
        aliases = load_tinygs_aliases(TINYGS_ALIASES_FILE)
        return sorted(aliases.keys())
    return []
