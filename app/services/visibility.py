"""
Sichtbarkeits- und Helligkeitsberechnung für die visuelle
Satellitenbeobachtung.

Ein Durchgang gilt als "sichtbar", wenn zwei Bedingungen gleichzeitig
erfüllt sind:
- der Satellit wird von der Sonne beschienen (befindet sich nicht im
  Erdschatten), und
- der Himmel des Beobachters ist dunkel genug (die Sonne steht
  ausreichend tief unter dem Horizont).

Für die geschätzte Helligkeit wird zusätzlich eine sogenannte
Standardmagnitude benötigt - ein Erfahrungswert, wie hell ein
bestimmter Satellit bei 1000 km Entfernung und 90 Grad Phasenwinkel
(halb beleuchtet) erscheint. Dieser Wert steckt nicht in den
TLE-Daten und ist nur für eine kleine Zahl bekannter Objekte
zuverlässig überliefert. Ohne bekannte Standardmagnitude wird die
Sichtbarkeit trotzdem angezeigt, nur die Helligkeit bleibt "unbekannt".
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from skyfield.api import EarthSatellite, Loader, wgs84

from app.config import DATA_DIR
from app.models.tle_record import TLERecord

_loader = Loader(str(DATA_DIR))
_ephemeris = None
_timescale = None

# Sonnenhöhe, ab der der Himmel als dunkel genug für die
# Satellitenbeobachtung gilt (Ende der bürgerlichen / Beginn der
# nautischen Dämmerung). Durchgänge bei helleren Sonnenständen
# werden im Frontend nicht mehr aufgelistet.
SUN_ALTITUDE_THRESHOLD_DEG = -6.0

# Bewusst kleine, konservative Datenbank bekannter Standardmagnituden
# (Helligkeit bei 1000 km Entfernung und 90 Grad Phasenwinkel - die in
# der Beobachter-Community durchgängig genannte "Molczan"-Konvention).
# Nur Werte, für die es einen breiten Konsens gibt, um keine falsche
# Genauigkeit vorzutäuschen. Schlüssel ist die NORAD-Katalognummer.
STANDARD_MAGNITUDES: dict[str, float] = {
    "25544": -1.8,  # ISS (ZARYA)
}

# Namens-Fragmente bekannter, mit blossem Auge auffindbarer Objekte für
# die automatische "heute sichtbar"-Übersicht - unabhängig davon, ob
# eine Standardmagnitude bekannt ist.
KNOWN_BRIGHT_NAME_HINTS: tuple[str, ...] = (
    "ISS (ZARYA)",
    "TIANHE",
    "CSS (",
    "HST",
)


@dataclass(frozen=True, slots=True)
class VisibilityResult:
    visible: bool
    sunlit: bool
    sun_altitude_deg: float
    magnitude: float | None


def _get_ephemeris():
    global _ephemeris
    if _ephemeris is None:
        _ephemeris = _loader("de421.bsp")
    return _ephemeris


def _get_timescale():
    global _timescale
    if _timescale is None:
        _timescale = _loader.timescale()
    return _timescale


def _vector_norm(vector) -> float:
    return math.sqrt(sum(component**2 for component in vector))


def _phase_angle_and_range(
    satellite: EarthSatellite,
    observer,
    ephemeris,
    t,
) -> tuple[float, float]:
    """Liefert (Phasenwinkel in Grad, Entfernung in km) zum Zeitpunkt t."""

    sat_position = satellite.at(t).position.km
    obs_position = observer.at(t).position.km
    sun_position = (ephemeris["sun"] - ephemeris["earth"]).at(t).position.km

    to_observer = obs_position - sat_position
    to_sun = sun_position - sat_position

    range_km = _vector_norm(to_observer)
    norm_sun = _vector_norm(to_sun)

    dot = sum(a * b for a, b in zip(to_observer, to_sun))
    cos_phase = max(-1.0, min(1.0, dot / (range_km * norm_sun)))

    return math.degrees(math.acos(cos_phase)), range_km


def _estimate_magnitude(
    standard_magnitude: float,
    range_km: float,
    phase_deg: float,
) -> float | None:
    phase_rad = math.radians(phase_deg)
    phase_term = (
        math.sin(phase_rad) + (math.pi - phase_rad) * math.cos(phase_rad)
    )

    if phase_term <= 0.0:
        # Satellit ist aus Beobachtersicht praktisch unbeleuchtet -
        # kein sinnvoller Helligkeitswert.
        return None

    return (
        standard_magnitude
        + 5.0 * math.log10(range_km / 1000.0)
        - 2.5 * math.log10(phase_term)
    )


def assess_visibility(
    record: TLERecord,
    latitude_deg: float,
    longitude_deg: float,
    elevation_m: float,
    at_datetime: datetime,
) -> VisibilityResult:
    """
    Bewertet die Sichtbarkeit eines Satelliten zu einem bestimmten
    Zeitpunkt (typischerweise der Kulminationszeitpunkt eines
    Durchgangs) und schätzt - sofern möglich - die Helligkeit.
    """

    timescale = _get_timescale()
    ephemeris = _get_ephemeris()

    satellite = EarthSatellite(
        record.line1,
        record.line2,
        record.name,
        timescale,
    )
    observer = wgs84.latlon(
        latitude_degrees=latitude_deg,
        longitude_degrees=longitude_deg,
        elevation_m=elevation_m,
    )

    t = timescale.from_datetime(at_datetime)

    sunlit = satellite.at(t).is_sunlit(ephemeris)

    topocentric = (ephemeris["earth"] + observer).at(t)
    sun_altitude_deg = (
        topocentric.observe(ephemeris["sun"]).apparent().altaz()[0].degrees
    )

    visible = bool(sunlit) and sun_altitude_deg <= SUN_ALTITUDE_THRESHOLD_DEG

    magnitude = None
    standard_magnitude = STANDARD_MAGNITUDES.get(record.norad_id)
    if visible and standard_magnitude is not None:
        phase_deg, range_km = _phase_angle_and_range(
            satellite, observer, ephemeris, t
        )
        magnitude = _estimate_magnitude(
            standard_magnitude, range_km, phase_deg
        )

    return VisibilityResult(
        visible=visible,
        sunlit=bool(sunlit),
        sun_altitude_deg=round(sun_altitude_deg, 1),
        magnitude=round(magnitude, 1) if magnitude is not None else None,
    )


def is_known_bright_satellite(name: str) -> bool:
    """Grobe Namenserkennung bekannter, mit blossem Auge auffindbarer Objekte."""
    display_name = name[2:] if name.startswith("0 ") else name
    upper_name = display_name.upper()
    return any(hint in upper_name for hint in KNOWN_BRIGHT_NAME_HINTS)
