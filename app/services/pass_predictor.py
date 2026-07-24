from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from math import cos, radians, sin

from skyfield.api import EarthSatellite, load, wgs84

from app.models.tle_record import TLERecord
from app.services.observer_settings import ObserverSettings


@dataclass(frozen=True, slots=True)
class SatelliteTrackPoint:
    timestamp: datetime
    azimuth_deg: float
    elevation_deg: float
    polar_x: float
    polar_y: float


@dataclass(frozen=True, slots=True)
class SatellitePass:
    satellite_name: str
    norad_id: str
    rise_time: datetime
    culmination_time: datetime
    set_time: datetime
    max_elevation_deg: float
    rise_azimuth_deg: float
    set_azimuth_deg: float
    track_points: tuple[SatelliteTrackPoint, ...]

    @property
    def duration_seconds(self) -> int:
        return int(
            (
                self.set_time
                - self.rise_time
            ).total_seconds()
        )


class PassPredictor:
    def __init__(
        self,
        latitude_deg: float,
        longitude_deg: float,
        elevation_m: float = 0.0,
    ) -> None:
        self.observer = wgs84.latlon(
            latitude_degrees=latitude_deg,
            longitude_degrees=longitude_deg,
            elevation_m=elevation_m,
        )
        self.timescale = load.timescale()

    def _build_track_points(
        self,
        satellite: EarthSatellite,
        rise_time: datetime,
        set_time: datetime,
        sample_count: int = 41,
    ) -> tuple[SatelliteTrackPoint, ...]:
        duration = set_time - rise_time
        points: list[SatelliteTrackPoint] = []

        for index in range(sample_count):
            fraction = index / (sample_count - 1)
            timestamp = rise_time + duration * fraction

            skyfield_time = self.timescale.from_datetime(
                timestamp
            )

            difference = (
                satellite - self.observer
            ).at(skyfield_time)

            altitude, azimuth, _ = difference.altaz()

            azimuth_deg = azimuth.degrees % 360.0
            elevation_deg = max(
                0.0,
                min(90.0, altitude.degrees),
            )

            radius = (
                90.0 - elevation_deg
            ) / 90.0 * 90.0

            azimuth_rad = radians(azimuth_deg)

            polar_x = (
                100.0
                + radius * sin(azimuth_rad)
            )

            polar_y = (
                100.0
                - radius * cos(azimuth_rad)
            )

            points.append(
                SatelliteTrackPoint(
                    timestamp=timestamp,
                    azimuth_deg=round(
                        azimuth_deg,
                        1,
                    ),
                    elevation_deg=round(
                        elevation_deg,
                        1,
                    ),
                    polar_x=round(
                        polar_x,
                        2,
                    ),
                    polar_y=round(
                        polar_y,
                        2,
                    ),
                )
            )

        return tuple(points)

    def predict(
        self,
        record: TLERecord,
        hours: int = 24,
        minimum_elevation_deg: float = 10.0,
        start_time: datetime | None = None,
        observer_settings: ObserverSettings | None = None,
    ) -> list[SatellitePass]:
        start = start_time or datetime.now(
            timezone.utc
        )

        if start.tzinfo is None:
            start = start.replace(
                tzinfo=timezone.utc
            )

        end = start + timedelta(
            hours=hours
        )

        satellite = EarthSatellite(
            record.line1,
            record.line2,
            record.name,
            self.timescale,
        )

        start_sf = self.timescale.from_datetime(
            start
        )
        end_sf = self.timescale.from_datetime(
            end
        )

        search_floor = minimum_elevation_deg
        if observer_settings is not None:
            search_floor = min(
                search_floor,
                observer_settings.default_minimum_elevation_deg,
            )
        search_floor = max(0.0, search_floor)

        times, events = satellite.find_events(
            self.observer,
            start_sf,
            end_sf,
            altitude_degrees=search_floor,
        )

        passes: list[SatellitePass] = []
        current_rise = None
        current_rise_azimuth = None
        current_culmination = None
        current_max_elevation = None

        for event_time, event_code in zip(
            times,
            events,
        ):
            timestamp = (
                event_time.utc_datetime()
                .replace(tzinfo=timezone.utc)
            )

            difference = (
                satellite - self.observer
            ).at(event_time)

            altitude, azimuth, _ = (
                difference.altaz()
            )

            if event_code == 0:
                current_rise = timestamp
                current_rise_azimuth = (
                    azimuth.degrees
                )

            elif event_code == 1:
                current_culmination = timestamp
                current_max_elevation = (
                    altitude.degrees
                )

            elif (
                event_code == 2
                and current_rise is not None
                and current_culmination
                is not None
                and current_max_elevation
                is not None
                and current_rise_azimuth
                is not None
            ):
                track_points = self._build_track_points(
                    satellite,
                    current_rise,
                    timestamp,
                )

                passes.append(
                    SatellitePass(
                        satellite_name=record.name,
                        norad_id=record.norad_id,
                        rise_time=current_rise,
                        culmination_time=(
                            current_culmination
                        ),
                        set_time=timestamp,
                        max_elevation_deg=round(
                            current_max_elevation,
                            1,
                        ),
                        rise_azimuth_deg=round(
                            current_rise_azimuth,
                            1,
                        ),
                        set_azimuth_deg=round(
                            azimuth.degrees,
                            1,
                        ),
                        track_points=track_points,
                    )
                )

                current_rise = None
                current_rise_azimuth = None
                current_culmination = None
                current_max_elevation = None

        if observer_settings is None:
            return passes

        masked_passes: list[SatellitePass] = []
        for satellite_pass in passes:
            masked_passes.extend(
                self._apply_horizon_mask(
                    satellite_pass,
                    minimum_elevation_deg=minimum_elevation_deg,
                    observer_settings=observer_settings,
                )
            )
        return masked_passes

    def _apply_horizon_mask(
        self,
        satellite_pass: SatellitePass,
        minimum_elevation_deg: float,
        observer_settings: ObserverSettings,
    ) -> list[SatellitePass]:
        """Split a pass into the sub-window(s) that clear the local horizon."""

        def required_elevation(azimuth_deg: float) -> float:
            return max(
                minimum_elevation_deg,
                observer_settings.minimum_elevation_at(azimuth_deg),
            )

        runs: list[list[SatelliteTrackPoint]] = []
        current_run: list[SatelliteTrackPoint] = []

        for point in satellite_pass.track_points:
            if point.elevation_deg >= required_elevation(point.azimuth_deg):
                current_run.append(point)
            else:
                if len(current_run) >= 2:
                    runs.append(current_run)
                current_run = []

        if len(current_run) >= 2:
            runs.append(current_run)

        result: list[SatellitePass] = []
        for run in runs:
            peak = max(run, key=lambda point: point.elevation_deg)
            result.append(
                replace(
                    satellite_pass,
                    rise_time=run[0].timestamp,
                    culmination_time=peak.timestamp,
                    set_time=run[-1].timestamp,
                    max_elevation_deg=peak.elevation_deg,
                    rise_azimuth_deg=run[0].azimuth_deg,
                    set_azimuth_deg=run[-1].azimuth_deg,
                    track_points=tuple(run),
                )
            )

        return result
