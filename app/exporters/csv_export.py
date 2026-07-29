import csv
import io
from collections.abc import Iterable

from app.models.tle_record import TLERecord


class CsvExporter:
    """Exportiert TLE-Datensaetze als CSV-Tabelle.

    Spalten: name, norad_id, epoch_utc, line1, line2.
    """

    def export(self, records: Iterable[TLERecord]) -> str:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["name", "norad_id", "epoch_utc", "line1", "line2"])

        for record in records:
            epoch = record.epoch_datetime
            writer.writerow(
                [
                    record.name,
                    record.norad_id,
                    epoch.isoformat() if epoch else "",
                    record.line1,
                    record.line2,
                ]
            )

        return buffer.getvalue()
