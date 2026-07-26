from app.models.tle_record import TLERecord


class SatGazerExporter:
    """
    Exportiert TLE-Datensätze im SatGazer-kompatiblen
    3LE-Format.

    Format:

    0 NAME
    1 ....
    2 ....
    """

    def export(self, records: list[TLERecord]) -> str:
        return "".join(
            f"0 {record.name}\n"
            f"{record.line1}\n"
            f"{record.line2}\n"
            for record in records
        )
