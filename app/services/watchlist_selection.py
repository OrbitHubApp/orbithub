"""Persistiert, welche Quelle auf der Ueberfluege-Seite aktiv ist:
entweder die eigenen Favoriten ("favorites") oder ein vordefiniertes
Satelliten-Paket ("package:<id>", z. B. "package:tinygs").
"""

from __future__ import annotations

import json

from app.config import DATA_DIR

WATCHLIST_SELECTION_FILE = DATA_DIR / "watchlist-selection.json"

DEFAULT_SELECTION = "favorites"


def load_watchlist_selection() -> str:
    if not WATCHLIST_SELECTION_FILE.exists():
        return DEFAULT_SELECTION
    try:
        data = json.loads(WATCHLIST_SELECTION_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return DEFAULT_SELECTION

    selection = data.get("selection")
    if not isinstance(selection, str) or not selection:
        return DEFAULT_SELECTION
    return selection


def save_watchlist_selection(selection: str) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    WATCHLIST_SELECTION_FILE.write_text(
        json.dumps({"selection": selection}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
