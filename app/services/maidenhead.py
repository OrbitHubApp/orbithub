"""Conversion helpers between Maidenhead grid locators and lat/lon."""

from __future__ import annotations

UPPER_FIELD = "ABCDEFGHIJKLMNOPQR"
SUBSQUARE = "abcdefghijklmnopqrstuvwx"


def locator_to_latlon(locator: str) -> tuple[float, float]:
    """Convert a Maidenhead locator (e.g. "JO62PL") to (latitude, longitude).

    Returns the coordinates of the centre of the smallest square that the
    locator describes. Raises ValueError for malformed input.
    """
    value = locator.strip().upper()

    if len(value) < 4 or len(value) % 2 != 0:
        raise ValueError("Locator must have an even length of at least 4.")

    if value[0] not in UPPER_FIELD or value[1] not in UPPER_FIELD:
        raise ValueError("Invalid locator field characters.")

    if not value[2].isdigit() or not value[3].isdigit():
        raise ValueError("Invalid locator square digits.")

    longitude = (
        UPPER_FIELD.index(value[0]) * 20.0
        + int(value[2]) * 2.0
        - 180.0
    )
    latitude = (
        UPPER_FIELD.index(value[1]) * 10.0
        + int(value[3]) * 1.0
        - 90.0
    )

    longitude_step = 2.0
    latitude_step = 1.0

    if len(value) >= 6:
        subsquare = value[4:6].lower()

        if subsquare[0] not in SUBSQUARE or subsquare[1] not in SUBSQUARE:
            raise ValueError("Invalid locator subsquare characters.")

        longitude += SUBSQUARE.index(subsquare[0]) * (longitude_step / 24.0)
        latitude += SUBSQUARE.index(subsquare[1]) * (latitude_step / 24.0)
        longitude_step /= 24.0
        latitude_step /= 24.0

    # Centre the point within the resolved square/subsquare.
    longitude += longitude_step / 2.0
    latitude += latitude_step / 2.0

    return round(latitude, 5), round(longitude, 5)
