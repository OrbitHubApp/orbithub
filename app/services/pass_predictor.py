from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from skyfield.api import EarthSatellite, load, wgs84

from app.models.tle_record import TLERecord


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

    def predict(
        self,
        record: TLERecord,
        hours: int = 24,
        minimum_elevation_deg: float = 10.0,
        start_time: datetime | None = None,
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

        times, events = satellite.find_events(
            self.observer,
            start_sf,
            end_sf,
            altitude_degrees=minimum_elevation_deg,
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
                    )
                )

                current_rise = None
                current_rise_azimuth = None
                current_culmination = None
                current_max_elevation = None

        return passes
