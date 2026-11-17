"""Länderzuordnung von Rufzeichen über cty.dat (country-files.com, AD1C).

Die Datei wird bei Bedarf nach ~/digimode/cty.dat geladen und alle 14 Tage
erneuert. Auswertung wie in WSJT-X/N1MM: exakte Rufzeichen (=CALL) vor dem
längsten passenden Präfix; bei Rufzeichen mit „/“ zählt der Präfixteil.
"""
from __future__ import annotations

import logging
import re
import threading
import time
import urllib.request
from pathlib import Path

CTY_URL = "https://www.country-files.com/cty/cty.dat"
MAX_AGE = 14 * 86400

log = logging.getLogger("digimode")

# Deutsche Namen für häufige DXCC-Gebiete (sonst englischer Name aus cty.dat)
DE_NAMES = {
    "Fed. Rep. of Germany": "Deutschland", "Austria": "Österreich", "Switzerland": "Schweiz",
    "Netherlands": "Niederlande", "Belgium": "Belgien", "Luxembourg": "Luxemburg", "France": "Frankreich",
    "Italy": "Italien", "Spain": "Spanien", "Portugal": "Portugal", "England": "England",
    "Scotland": "Schottland", "Wales": "Wales", "Northern Ireland": "Nordirland", "Ireland": "Irland",
    "Denmark": "Dänemark", "Sweden": "Schweden", "Norway": "Norwegen", "Finland": "Finnland",
    "Poland": "Polen", "Czech Republic": "Tschechien", "Slovak Republic": "Slowakei", "Hungary": "Ungarn",
    "Slovenia": "Slowenien", "Croatia": "Kroatien", "Serbia": "Serbien", "Romania": "Rumänien",
    "Bulgaria": "Bulgarien", "Greece": "Griechenland", "Lithuania": "Litauen", "Latvia": "Lettland",
    "Estonia": "Estland", "Ukraine": "Ukraine", "European Russia": "Russland (Europa)",
    "Asiatic Russia": "Russland (Asien)", "Kaliningrad": "Kaliningrad", "Belarus": "Belarus",
    "Iceland": "Island", "Turkey": "Türkei", "Cyprus": "Zypern", "Malta": "Malta", "Moldova": "Moldau",
    "Bosnia-Herzegovina": "Bosnien-Herzegowina", "North Macedonia": "Nordmazedonien",
    "Montenegro": "Montenegro", "Albania": "Albanien", "Liechtenstein": "Liechtenstein",
    "Monaco": "Monaco", "Andorra": "Andorra", "San Marino": "San Marino", "Vatican City": "Vatikan",
    "Gibraltar": "Gibraltar", "Faroe Islands": "Färöer", "Greenland": "Grönland",
    "Canary Islands": "Kanarische Inseln", "Balearic Islands": "Balearen", "Azores": "Azoren",
    "Madeira Islands": "Madeira", "Sardinia": "Sardinien", "Sicily": "Sizilien",
    "Corsica": "Korsika", "Crete": "Kreta", "Jersey": "Jersey", "Guernsey": "Guernsey",
    "Isle of Man": "Isle of Man", "United States": "USA", "Canada": "Kanada", "Brazil": "Brasilien",
    "Argentina": "Argentinien", "Japan": "Japan", "China": "China", "India": "Indien",
    "Australia": "Australien", "New Zealand": "Neuseeland", "South Africa": "Südafrika",
    "Israel": "Israel", "Egypt": "Ägypten", "Morocco": "Marokko", "Kazakhstan": "Kasachstan",
    "Georgia": "Georgien", "Armenia": "Armenien", "Azerbaijan": "Aserbaidschan", "Mexico": "Mexiko",
}

_SUFFIX_IGNORE = {"P", "M", "MM", "AM", "QRP", "A", "B", "LH", "J"}


class Cty:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.prefixes: dict[str, dict] = {}
        self.exact: dict[str, dict] = {}
        self.loaded_at = 0.0
        self.lock = threading.Lock()
        threading.Thread(target=self._ensure, name="cty", daemon=True).start()

    def _ensure(self) -> None:
        try:
            if not self.path.exists() or time.time() - self.path.stat().st_mtime > MAX_AGE:
                req = urllib.request.Request(CTY_URL, headers={"User-Agent": "OrbitHub-Digimode"})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = resp.read()
                if b"Germany" in data:
                    tmp = self.path.with_suffix(".tmp")
                    tmp.write_bytes(data)
                    tmp.replace(self.path)
        except Exception as exc:  # noqa: BLE001
            log.warning("cty.dat nicht ladbar: %s", exc)
        if self.path.exists():
            self._parse(self.path.read_text(encoding="latin-1"))

    def _parse(self, text: str) -> None:
        prefixes, exact = {}, {}
        for block in text.split(";"):
            block = block.strip()
            if not block or ":" not in block:
                continue
            head, _, tail = block.rpartition(":")
            fields = [f.strip() for f in head.split(":")]
            if len(fields) < 8:
                continue
            name, cq, itu, cont, lat, lon = fields[0], fields[1], fields[2], fields[3], fields[4], fields[5]
            try:
                base = {"country": DE_NAMES.get(name, name), "country_en": name, "cont": cont,
                        "cq": int(cq), "lat": float(lat), "lon": -float(lon)}
            except ValueError:
                continue
            for item in tail.replace("\n", " ").split(","):
                item = item.strip()
                if not item:
                    continue
                key = re.split(r"[(\[<{~]", item, 1)[0]
                if key.startswith("="):
                    exact[key[1:].upper()] = base
                else:
                    prefixes[key.upper()] = base
        with self.lock:
            self.prefixes, self.exact = prefixes, exact
            self.loaded_at = time.time()
        log.info("cty.dat: %d Präfixe, %d Einzelrufzeichen", len(prefixes), len(exact))

    def lookup(self, call: str | None) -> dict | None:
        if not call:
            return None
        call = call.upper().strip("<>")
        with self.lock:
            if not self.prefixes:
                return None
            if call in self.exact:
                return self.exact[call]
            base = call
            if "/" in call:
                parts = [p for p in call.split("/") if p and p not in _SUFFIX_IGNORE and not p.isdigit()]
                if len(parts) >= 2:
                    # kürzerer Teil ist der Präfix (LX/PA1L -> LX, PA1L/LX -> LX)
                    base = min(parts, key=len)
                elif parts:
                    base = parts[0]
            for n in range(len(base), 0, -1):
                hit = self.prefixes.get(base[:n])
                if hit:
                    return hit
        return None
