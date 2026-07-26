"""Persisted list of favourite satellites shown on the Visuell overview."""

from __future__ import annotations

import json

from app.config import DATA_DIR

FAVORITES_FILE = DATA_DIR / "favorites.json"

# Vorbelegung entspricht der bisherigen fest verdrahteten Liste bekannter
# heller Satelliten (ISS, CSS/Tiangong), damit sich beim Umstieg auf die
# Favoriten-Funktion fuer bestehende Nutzer zunaechst nichts aendert.
DEFAULT_FAVORITE_NORAD_IDS: tuple[str, ...] = ("25544", "48274")


def load_favorite_norad_ids() -> list[str]:
    if not FAVORITES_FILE.exists():
        return list(DEFAULT_FAVORITE_NORAD_IDS)

    try:
        data = json.loads(FAVORITES_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return list(DEFAULT_FAVORITE_NORAD_IDS)

    if not isinstance(data, list):
        return list(DEFAULT_FAVORITE_NORAD_IDS)

    return [str(item) for item in data]


def save_favorite_norad_ids(norad_ids: list[str]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    FAVORITES_FILE.write_text(
        json.dumps(norad_ids, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def add_favorite(norad_id: str) -> list[str]:
    favorites = load_favorite_norad_ids()
    if norad_id not in favorites:
        favorites.append(norad_id)
        save_favorite_norad_ids(favorites)
    return favorites


def remove_favorite(norad_id: str) -> list[str]:
    favorites = load_favorite_norad_ids()
    if norad_id in favorites:
        favorites.remove(norad_id)
        save_favorite_norad_ids(favorites)
    return favorites
