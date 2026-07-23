from pathlib import Path

from app.models.tle_record import TLERecord


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

        return records

    def parse_file(self, path: str | Path) -> list[TLERecord]:
        file_path = Path(path)
        text = file_path.read_text(encoding="utf-8")
        return self.parse_text(text)
