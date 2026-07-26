from collections.abc import Iterable

from app.models.tle_record import TLERecord


class ClassicExporter:
    """
    Exportiert TLE-Datensätze im klassischen 2-Zeilen-Format
    (nur Zeile 1 und Zeile 2, ohne vorangestellte Namenszeile).
    """

    def export(self, records: Iterable[TLERecord]) -> str:
        lines: list[str] = []

        for record in records:
            lines.extend(
                [
                    record.line1,
                    record.line2,
                ]
            )

        return "\n".join(lines) + "\n"
