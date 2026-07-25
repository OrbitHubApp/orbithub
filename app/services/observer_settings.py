"""Persisted operator/observer configuration: QTH, locator, horizon mask."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

from app.config import DATA_DIR

OBSERVER_SETTINGS_FILE = DATA_DIR / "observer-settings.json"

DEFAULT_SETTINGS = {
    "callsign": "DL7AG",
    "locator": "JO62PL",
    "qth_name": "Berlin",
    "latitude_deg": 52.45,
    "longitude_deg": 13.35,
    "elevation_m": 50.0,
    "default_minimum_elevation_deg": 10.0,
    "horizon_segments": [],
    "time_display": "local",
}


@dataclass(frozen=True, slots=True)
class HorizonSegment:
    azimuth_from_deg: float
    azimuth_to_deg: float
    minimum_elevation_deg: float


@dataclass(frozen=True, slots=True)
class ObserverSettings:
    callsign: str
    locator: str
    qth_name: str
    latitude_deg: float
    longitude_deg: float
    elevation_m: float
    default_minimum_elevation_deg: float
    horizon_segments: tuple[HorizonSegment, ...] = field(
        default_factory=tuple,
    )
    time_display: str = "local"

    def minimum_elevation_at(self, azimuth_deg: float) -> float:
        """Required minimum elevation for a given azimuth, taking the
        configured horizon mask into account."""
        azimuth_deg = azimuth_deg % 360.0

        for segment in self.horizon_segments:
            start = segment.azimuth_from_deg % 360.0
            end = segment.azimuth_to_deg % 360.0

            covered = (
                start <= azimuth_deg <= end
                if start <= end
                else azimuth_deg >= start or azimuth_deg <= end
            )

            if covered:
                return max(
                    segment.minimum_elevation_deg,
                    self.default_minimum_elevation_deg,
                )

        return self.default_minimum_elevation_deg


def _coerce_float(value: object, fallback: float) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback


def load_observer_settings() -> ObserverSettings:
    data: dict = dict(DEFAULT_SETTINGS)

    if OBSERVER_SETTINGS_FILE.exists():
        try:
            stored = json.loads(
                OBSERVER_SETTINGS_FILE.read_text(encoding="utf-8"),
            )
            if isinstance(stored, dict):
                data.update(stored)
        except (json.JSONDecodeError, OSError):
            pass

    raw_segments = data.get("horizon_segments") or []
    segments = tuple(
        HorizonSegment(
            azimuth_from_deg=_coerce_float(
                segment.get("azimuth_from_deg"), 0.0,
            ),
            azimuth_to_deg=_coerce_float(
                segment.get("azimuth_to_deg"), 0.0,
            ),
            minimum_elevation_deg=_coerce_float(
                segment.get("minimum_elevation_deg"), 0.0,
            ),
        )
        for segment in raw_segments
        if isinstance(segment, dict)
    )

    return ObserverSettings(
        callsign=str(data.get("callsign", DEFAULT_SETTINGS["callsign"])),
        locator=str(data.get("locator", DEFAULT_SETTINGS["locator"])),
        qth_name=str(data.get("qth_name", DEFAULT_SETTINGS["qth_name"])),
        latitude_deg=_coerce_float(
            data.get("latitude_deg"), DEFAULT_SETTINGS["latitude_deg"],
        ),
        longitude_deg=_coerce_float(
            data.get("longitude_deg"), DEFAULT_SETTINGS["longitude_deg"],
        ),
        elevation_m=_coerce_float(
            data.get("elevation_m"), DEFAULT_SETTINGS["elevation_m"],
        ),
        default_minimum_elevation_deg=_coerce_float(
            data.get("default_minimum_elevation_deg"),
            DEFAULT_SETTINGS["default_minimum_elevation_deg"],
        ),
        horizon_segments=segments,
        time_display=(
            str(data.get("time_display", DEFAULT_SETTINGS["time_display"]))
            if str(
                data.get("time_display", DEFAULT_SETTINGS["time_display"])
            )
            in ("local", "utc")
            else DEFAULT_SETTINGS["time_display"]
        ),
    )


def save_observer_settings(settings: ObserverSettings) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    payload = {
        "callsign": settings.callsign,
        "locator": settings.locator,
        "qth_name": settings.qth_name,
        "latitude_deg": settings.latitude_deg,
        "longitude_deg": settings.longitude_deg,
        "elevation_m": settings.elevation_m,
        "default_minimum_elevation_deg": (
            settings.default_minimum_elevation_deg
        ),
        "horizon_segments": [
            asdict(segment) for segment in settings.horizon_segments
        ],
        "time_display": settings.time_display,
    }

    OBSERVER_SETTINGS_FILE.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
