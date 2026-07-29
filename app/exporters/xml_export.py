from collections.abc import Iterable
from xml.sax.saxutils import escape

from app.models.tle_record import TLERecord


class XmlExporter:
    """Exportiert TLE-Datensaetze als XML-Dokument."""

    def export(self, records: Iterable[TLERecord]) -> str:
        lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<tle_dataset>"]

        for record in records:
            epoch = record.epoch_datetime
            epoch_text = epoch.isoformat() if epoch else ""
            lines.append("  <satellite>")
            lines.append(f"    <name>{escape(record.name)}</name>")
            lines.append(f"    <norad_id>{escape(record.norad_id)}</norad_id>")
            lines.append(f"    <epoch_utc>{escape(epoch_text)}</epoch_utc>")
            lines.append(f"    <line1>{escape(record.line1)}</line1>")
            lines.append(f"    <line2>{escape(record.line2)}</line2>")
            lines.append("  </satellite>")

        lines.append("</tle_dataset>")
        return "\n".join(lines) + "\n"
