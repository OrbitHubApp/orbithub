from collections.abc import Iterable

from app.models.tle_record import TLERecord


class StandardExporter:
    '''Exportiert TLE-Datensaetze im normalen 3-Zeilen-Format (mit 0-Praefix).'''

    def export(self, records: Iterable[TLERecord]) -> str:
        lines: list[str] = []

        for record in records:
            lines.extend(
                [
                    f'0 {record.name}',
                    record.line1,
                    record.line2,
                ]
            )

        return '\n'.join(lines) + '\n'
