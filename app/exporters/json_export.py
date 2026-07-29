import json
from collections.abc import Iterable

from app.models.tle_record import TLERecord


class JsonExporter:
    """Exportiert TLE-Datensaetze als JSON-Array."""

    def export(self, records: Iterable[TLERecord]) -> str:
        data = []
        for record in records:
            epoch = record.epoch_datetime
            data.append(
                {
                    "name": record.name,
                    "norad_id": record.norad_id,
                    "epoch_utc": epoch.isoformat() if epoch else None,
                    "line1": record.line1,
                    "line2": record.line2,
                }
            )

        return json.dumps(data, ensure_ascii=False, indent=2) + "\n"
