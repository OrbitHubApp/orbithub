"""app/services/doppler.py

Doppler-Korrektur fuer die IC-705-Fernsteuerung waehrend eines Ueberflugs.

Berechnet aus der radialen Relativgeschwindigkeit (Skyfield) die tatsaechlich
zu tunende Empfangs-/Sendefrequenz, sowohl fuer einfache FM-Transponder
(nur Downlink-Korrektur noetig) als auch fuer lineare/SSB-Transponder
(synchronisierte Uplink+Downlink-Korrektur, ggf. mit invertiertem Passband
gemaess dem SatNOGS-Feld `invert` aus transponder_db.py).

Klassische (nicht-relativistische) Doppler-Formel, ausreichend genau fuer
LEO-Satelliten (v << c):

    f_empfangen = f_gesendet * (1 - v_radial / c)

wobei v_radial die Aenderungsrate der Entfernung Beobachter<->Satellit ist
(positiv = Objekt entfernt sich, negativ = Objekt naehert sich).
"""
from __future__ import annotations

from typing import Any

from skyfield.api import EarthSatellite, wgs84

SPEED_OF_LIGHT_KM_S = 299792.458


def range_rate_km_s(satellite: EarthSatellite, observer: wgs84.latlon, t: Any) -> float:
    """Radiale Relativgeschwindigkeit Beobachter<->Satellit in km/s.

    Positiv, wenn sich der Satellit vom Beobachter entfernt (Distanz nimmt
    zu), negativ beim Naehern. `observer` ist ein wgs84.latlon(...)-Objekt
    wie in pass_predictor.PassPredictor.observer, `t` ein Skyfield-Zeitpunkt
    (z.B. aus timescale.now() oder timescale.from_datetime(...)).
    """
    difference = satellite - observer
    topocentric = difference.at(t)
    _, _, _, _, _, rate = topocentric.frame_latlon_and_rates(observer)
    return rate.km_per_s


def doppler_shifted_frequency(nominal_hz: float, rate_km_s: float, *, direction: str) -> float:
    """Doppler-korrigierte Frequenz fuer eine Uplink- oder Downlink-Strecke.

    direction="downlink": der Satellit sendet auf `nominal_hz`; Rueckgabe ist
        die Frequenz, auf die der Empfaenger am Boden abgestimmt werden muss.
    direction="uplink": der Satellit soll `nominal_hz` empfangen; Rueckgabe
        ist die Frequenz, auf der die Bodenstation senden muss.
    """
    beta = rate_km_s / SPEED_OF_LIGHT_KM_S
    if direction == "downlink":
        return nominal_hz * (1.0 - beta)
    if direction == "uplink":
        return nominal_hz / (1.0 - beta)
    raise ValueError(f"Unbekannte Richtung: {direction!r}")


def _center(low: float | None, high: float | None) -> float | None:
    """Mittenfrequenz aus einer Low-/High-Grenze; deckt auch feste Einzelfrequenzen ab."""
    if low is None:
        return None
    if high is None or high == low:
        return low
    return (low + high) / 2.0


def transponder_center_frequencies(transponder: dict[str, Any]) -> dict[str, float | None]:
    """Nominal-Mittenfrequenzen (Hz, unkorrigiert) eines Transponder-Dicts aus transponder_db.py."""
    return {
        "downlink_hz": _center(transponder.get("downlink_low"), transponder.get("downlink_high")),
        "uplink_hz": _center(transponder.get("uplink_low"), transponder.get("uplink_high")),
    }


def corrected_transponder_frequencies(
    transponder: dict[str, Any],
    rate_km_s: float,
    *,
    downlink_offset_hz: float = 0.0,
) -> dict[str, float | None]:
    """Doppler-korrigierte RX-/TX-Frequenzen (Hz) fuer einen Transponder.

    `downlink_offset_hz` erlaubt, eine bestimmte Stelle innerhalb eines
    linearen/SSB-Passbands zu verfolgen (z.B. eine laufende QSO-Frequenz),
    relativ zur Mittenfrequenz des Downlinks. Bei einem invertierenden
    Transponder (`invert=True`) wird der Uplink-Offset gespiegelt, bei einem
    nicht-invertierenden gleichsinnig verschoben - so bleibt die relative
    Position im Passband erhalten, waehrend beide Seiten unabhaengig
    Doppler-korrigiert nachgefuehrt werden.

    Gibt {"rx_frequency_hz": float, "tx_frequency_hz": float | None} zurueck.
    `tx_frequency_hz` ist None, wenn der Transponder keinen Uplink hat
    (z.B. eine reine Bake/Downlink-only-Sender).
    """
    centers = transponder_center_frequencies(transponder)
    downlink_center = centers["downlink_hz"]
    uplink_center = centers["uplink_hz"]

    if downlink_center is None:
        raise ValueError("Transponder hat keine Downlink-Frequenz")

    downlink_nominal = downlink_center + downlink_offset_hz
    rx_frequency_hz = doppler_shifted_frequency(downlink_nominal, rate_km_s, direction="downlink")

    tx_frequency_hz = None
    if uplink_center is not None:
        invert = bool(transponder.get("invert"))
        uplink_offset_hz = -downlink_offset_hz if invert else downlink_offset_hz
        uplink_nominal = uplink_center + uplink_offset_hz
        tx_frequency_hz = doppler_shifted_frequency(uplink_nominal, rate_km_s, direction="uplink")

    return {"rx_frequency_hz": rx_frequency_hz, "tx_frequency_hz": tx_frequency_hz}
