#!/usr/bin/env python3
"""Fuegt einen Eintrag zur OrbitHub-Aenderungshistorie hinzu (data/history.json).

Aufruf: python3 history_log.py "Kurzbeschreibung der Aenderung"

Soll nach jeder abgeschlossenen Aenderung ausgefuehrt werden (idealerweise
zusammen mit git commit), damit die Historie-Seite in der App automatisch
aktuell bleibt. data/ ist als Volume gemountet, ein Docker-Rebuild ist dafuer
nicht noetig.
"""
import json
import sys
from datetime import datetime
from pathlib import Path

HISTORY_FILE = Path(__file__).resolve().parent / "data" / "history.json"


def main() -> None:
    if len(sys.argv) < 2:
        print('Nutzung: python3 history_log.py "Beschreibung der Aenderung"')
        raise SystemExit(1)

    message = " ".join(sys.argv[1:])
    now = datetime.now()

    entries = []
    if HISTORY_FILE.exists():
        try:
            entries = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            entries = []

    entries.insert(0, {
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M"),
        "message": message,
    })

    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(
        json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"Eintrag hinzugefuegt: {now.strftime('%Y-%m-%d %H:%M')} - {message}")


if __name__ == "__main__":
    main()
