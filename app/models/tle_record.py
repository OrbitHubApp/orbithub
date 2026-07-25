from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass(frozen=True, slots=True)
class TLERecord:
    """
    Repräsentiert einen einzelnen klassischen 3-Zeilen-TLE-Datensatz.

    Ein Datensatz besteht aus:
    - Satellitenname
    - TLE-Zeile 1
    - TLE-Zeile 2
    """

    name: str
    line1: str
    line2: str

    @property
    def norad_id(self) -> str:
        """
        Liefert die NORAD-Katalognummer aus TLE-Zeile 1.

        Klassische TLEs verwenden dafür die Zeichenpositionen 3 bis 7.
        """
        if len(self.line1) < 7:
            return ""

        return self.line1[2:7].strip()

    @property
    def epoch_datetime(self) -> "datetime | None":
        """
        Liefert den Epochen-Zeitpunkt (Datenstand der Bahndaten) aus
        TLE-Zeile 1 als UTC-Datetime.

        TLE-Zeile 1 kodiert die Epoche als zweistelliges Jahr
        (Zeichen 19-20) und Tag des Jahres inklusive Bruchteil
        (Zeichen 21-32). Liefert None, wenn sich die Epoche nicht
        auswerten laesst.
        """
        if len(self.line1) < 32:
            return None

        try:
            year_two_digit = int(self.line1[18:20])
            day_of_year = float(self.line1[20:32])
        except ValueError:
            return None

        year = (
            2000 + year_two_digit
            if year_two_digit < 57
            else 1900 + year_two_digit
        )

        return datetime(
            year, 1, 1, tzinfo=timezone.utc
        ) + timedelta(days=day_of_year - 1)

    def to_tle(self) -> str:
        """
        Wandelt den Datensatz wieder in klassischen TLE-Text um.
        """
        return f"{self.name}\n{self.line1}\n{self.line2}\n"
