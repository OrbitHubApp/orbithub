from collections.abc import Iterable

from app.models.tle_record import TLERecord


class StandardExporter:
    """Exportiert TLE-Datensätze im normalen 3-Zeilen-Format."""

    def export(self, records: Iterable[TLERecord]) -> str:
        lines: list[str] = []

        for record in records:
            lines.extend(
                [
                    record.name,
                    record.line1,
                    record.line2,
                ]
            )

        return "\n".join(lines) + "\n"
