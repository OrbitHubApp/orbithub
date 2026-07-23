from dataclasses import dataclass


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

    def to_tle(self) -> str:
        """
        Wandelt den Datensatz wieder in klassischen TLE-Text um.
        """
        return f"{self.name}\n{self.line1}\n{self.line2}\n"
