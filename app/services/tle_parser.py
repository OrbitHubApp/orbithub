from pathlib import Path

from app.models.tle_record import TLERecord

from app.config import SATNOGS_ALIASES_FILE, TINYGS_ALIASES_FILE
from app.services.satnogs_aliases import (
    enrich_name_with_alias,
    load_satnogs_aliases,
)
from app.services.tinygs_aliases import load_tinygs_aliases


class TLEParser:
    """
    Zerlegt klassischen 3-Zeilen-TLE-Text in TLERecord-Objekte.

    Erwartetes Format:
    Satellitenname
    Zeile 1
    Zeile 2
    """

    def parse_text(self, text: str) -> list[TLERecord]:
        lines = [line.rstrip("\r\n") for line in text.splitlines()]

        records: list[TLERecord] = []
        index = 0

        while index < len(lines):
            name = lines[index].strip()
            if name.startswith("0 "):
                name = name[2:].strip()

            if not name:
                index += 1
                continue

            if index + 2 >= len(lines):
                break

            line1 = lines[index + 1]
            line2 = lines[index + 2]

            if line1.startswith("1 ") and line2.startswith("2 "):
                records.append(
                    TLERecord(
                        name=name,
                        line1=line1,
                        line2=line2,
                    )
                )
                index += 3
                continue

            index += 1

        aliases = {
            **load_satnogs_aliases(SATNOGS_ALIASES_FILE),
            **load_tinygs_aliases(TINYGS_ALIASES_FILE),
        }
        if aliases:
            records = [
                TLERecord(
                    name=enrich_name_with_alias(
                        record.name,
                        record.norad_id,
                        aliases,
                    ),
                    line1=record.line1,
                    line2=record.line2,
                )
                for record in records
            ]

        return records

    def parse_file(self, path: str | Path) -> list[TLERecord]:
        file_path = Path(path)
        text = file_path.read_text(encoding="utf-8")
        return self.parse_text(text)
