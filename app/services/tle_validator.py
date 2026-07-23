from dataclasses import dataclass

from app.models.tle_record import TLERecord


@dataclass(frozen=True, slots=True)
class ValidationResult:
    valid: bool
    errors: tuple[str, ...]


class TLEValidator:
    """
    Prüft die grundlegende Struktur eines klassischen TLE-Datensatzes.
    """

    def validate(self, record: TLERecord) -> ValidationResult:
        errors: list[str] = []

        if not record.name.strip():
            errors.append("Satellitenname fehlt")

        if not record.line1.startswith("1 "):
            errors.append("Zeile 1 beginnt nicht mit '1 '")

        if not record.line2.startswith("2 "):
            errors.append("Zeile 2 beginnt nicht mit '2 '")

        if len(record.line1) != 69:
            errors.append(
                f"Zeile 1 hat {len(record.line1)} statt 69 Zeichen"
            )

        if len(record.line2) != 69:
            errors.append(
                f"Zeile 2 hat {len(record.line2)} statt 69 Zeichen"
            )

        line1_norad = record.line1[2:7].strip() if len(record.line1) >= 7 else ""
        line2_norad = record.line2[2:7].strip() if len(record.line2) >= 7 else ""

        if not line1_norad:
            errors.append("NORAD-ID in Zeile 1 fehlt")

        if not line2_norad:
            errors.append("NORAD-ID in Zeile 2 fehlt")

        if line1_norad and line2_norad and line1_norad != line2_norad:
            errors.append(
                f"NORAD-ID stimmt nicht überein: {line1_norad} != {line2_norad}"
            )

        return ValidationResult(
            valid=not errors,
            errors=tuple(errors),
        )
