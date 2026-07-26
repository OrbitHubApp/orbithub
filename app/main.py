from dataclasses import asdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import json
from math import cos, radians, sin
import re
import asyncio
import time
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import FileResponse, RedirectResponse
from app.api.system import router as system_router
from app.api.stats import router as stats_router

from app.config import (
    APP_DESCRIPTION,
    APP_NAME,
    APP_SLOGAN,
    BASE_DIR,
    DASHBOARD_REFRESH_SECONDS,
    CUSTOM_SOURCES_FILE,
    DATA_DIR,
    HISTORY_FILE,
    SOURCE_SETTINGS_FILE,
    SOURCE_URLS,
    TLE_FILE,
    TLE_REFRESH_HOURS,
)
from app.exporters.satgazer import SatGazerExporter
from app.exporters.standard import StandardExporter
from app.exporters.classic import ClassicExporter
from app.services.stats_store import (
    append_system_metrics_sample,
    append_tle_update_event,
    prune_old_entries,
)
from app.services.system_metrics import collect_system_metrics
from app.services.tle_parser import TLEParser
from app.services.pass_predictor import PassPredictor
from app.services.visibility import (
    assess_visibility,
    is_known_bright_satellite,
    SUN_ALTITUDE_THRESHOLD_DEG,
)
from app.services.source_manager import SourceManager
from app.services.maidenhead import locator_to_latlon
from app.services.observer_settings import (
    HorizonSegment,
    ObserverSettings,
    load_observer_settings,
    save_observer_settings,
)
from app.services.tle_sources import (
    fetch_source_text,
    find_source,
    load_custom_sources,
    load_source_settings,
    ordered_sources,
    save_custom_sources,
    save_preferred_source,
)
from app.version import CODENAME, VERSION


app = FastAPI(
    title=APP_NAME,
    version=VERSION,
    description=APP_DESCRIPTION,
)

app.mount(
    "/static",
    StaticFiles(directory=str(BASE_DIR / "static")),
    name="static",
)

app.include_router(system_router)
app.include_router(stats_router)

templates = Jinja2Templates(
    directory=str(BASE_DIR / "templates")
)


def display_satellite_name(name: str) -> str:
    """Strip the leading 3LE '0 ' marker from a satellite name for display."""
    if name.startswith("0 "):
        return name[2:]

    return name


templates.env.filters["display_name"] = display_satellite_name
templates.env.globals["observer_settings"] = load_observer_settings


def _polarplot_point(azimuth_deg: float, radius: float) -> tuple[float, float]:
    azimuth_rad = radians(azimuth_deg)
    x = 100 + radius * sin(azimuth_rad)
    y = 100 - radius * cos(azimuth_rad)
    return round(x, 2), round(y, 2)


def _horizon_shadow_path(
    azimuth_from_deg: float,
    azimuth_to_deg: float,
    minimum_elevation_deg: float,
) -> str | None:
    """SVG path for the blocked donut-sector of a horizon segment on the polarplot."""
    span = (azimuth_to_deg - azimuth_from_deg) % 360.0
    if span <= 0:
        return None

    minimum_elevation_deg = max(0.0, min(90.0, minimum_elevation_deg))
    radius_outer = 90.0
    radius_inner = 90.0 - minimum_elevation_deg
    if radius_inner >= radius_outer:
        return None

    azimuth_start = azimuth_from_deg % 360.0
    azimuth_end = azimuth_start + span
    large_arc = 1 if span > 180 else 0

    outer_start = _polarplot_point(azimuth_start, radius_outer)
    outer_end = _polarplot_point(azimuth_end, radius_outer)
    inner_end = _polarplot_point(azimuth_end, radius_inner)
    inner_start = _polarplot_point(azimuth_start, radius_inner)

    return (
        f"M {outer_start[0]} {outer_start[1]} "
        f"A {radius_outer} {radius_outer} 0 {large_arc} 1 {outer_end[0]} {outer_end[1]} "
        f"L {inner_end[0]} {inner_end[1]} "
        f"A {radius_inner} {radius_inner} 0 {large_arc} 0 {inner_start[0]} {inner_start[1]} Z"
    )

source_manager = SourceManager(SOURCE_URLS)


def get_all_sources() -> list[dict]:
    return source_manager.get_all_sources()


status = {
    "ok": False,
    "source": None,
    "source_id": None,
    "preferred_source": None,
    "preferred_source_id": None,
    "fallback_used": False,
    "previous_source": None,
    "source_changed": False,
    "updated_utc": None,
    "records": 0,
    "file_size_bytes": 0,
    "new_satellites": 0,
    "updated_satellites": 0,
    "removed_satellites": 0,
    "unchanged_satellites": 0,
    "last_update_duration_ms": 0,
    "error": "Noch keine Aktualisierung durchgeführt",
}


TLE_MAX_AGE_DAYS = 14


def _check_tle_freshness(text: str) -> None:
    """
    Prüft, ob eine frisch abgerufene TLE-Quelle aktuelle Bahndaten
    liefert. Manche Quellen (z. B. SatNOGS) liefern im Fehlerfall oder
    bei Ausfällen teils monatealte, veraltete Datensätze zurück, statt
    einen Fehler zu melden. Ohne diese Prüfung würden solche Daten
    unbemerkt übernommen und alle Vorhersagen (Aufgangs-, Kulminations-
    und Untergangszeiten) wären falsch.

    Nutzt die ISS (NORAD 25544) als Referenz, da sie durchgehend im
    aktiven Katalog geführt und besonders häufig aktualisiert wird.
    Fällt auf den Median-Wert aller Datensätze zurück, falls die ISS
    in der Quelle fehlt.
    """
    records = TLEParser().parse_text(text)
    if not records:
        return

    now = datetime.now(timezone.utc)

    iss_record = next(
        (record for record in records if record.norad_id == "25544"),
        None,
    )
    reference_records = [iss_record] if iss_record else records

    ages_days = sorted(
        (now - record.epoch_datetime).total_seconds() / 86400.0
        for record in reference_records
        if record.epoch_datetime is not None
    )
    if not ages_days:
        return

    median_age_days = ages_days[len(ages_days) // 2]

    if median_age_days > TLE_MAX_AGE_DAYS:
        raise ValueError(
            "Die gelieferten Bahndaten sind zu alt (Epoche ca. "
            f"{median_age_days:.1f} Tage alt, Grenzwert "
            f"{TLE_MAX_AGE_DAYS} Tage). Diese Quelle liefert offenbar "
            "veraltete TLE-Datensätze und wird übersprungen."
        )


def _deduplicate_by_freshness(records):
    """
    Manche Quellen (z. B. SatNOGS) liefern für denselben Satelliten
    (gleiche NORAD-Katalognummer) mehrere, widersprüchliche
    TLE-Datensätze in derselben Antwort - etwa einen aktuellen und
    einen veralteten Karteileichen-Eintrag. Ohne Bereinigung würde
    OrbitHub den Satelliten doppelt in der Auswahlliste anzeigen und
    sich implizit auf die zufällige Reihenfolge der Quelle verlassen,
    welcher der beiden Datensätze tatsächlich für Vorhersagen
    verwendet wird.

    Behält je NORAD-ID nur den Datensatz mit der aktuellsten Epoche.
    Datensätze ohne auswertbare Epoche gelten dabei als am ältesten.
    """
    best_by_norad = {}

    for record in records:
        existing = best_by_norad.get(record.norad_id)
        if existing is None:
            best_by_norad[record.norad_id] = record
            continue

        existing_epoch = existing.epoch_datetime
        candidate_epoch = record.epoch_datetime

        if candidate_epoch is None:
            continue
        if existing_epoch is None or candidate_epoch > existing_epoch:
            best_by_norad[record.norad_id] = record

    return list(best_by_norad.values())


async def update_tle() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    settings = load_source_settings(
        SOURCE_SETTINGS_FILE
    )

    preferred_source_id = settings[
        "preferred_source_id"
    ]

    all_sources = get_all_sources()

    preferred_source = find_source(
        all_sources,
        preferred_source_id,
    )

    if preferred_source is None:
        preferred_source = all_sources[0]
        preferred_source_id = preferred_source["id"]

    try:
        start_time = time.perf_counter()
        timeout = httpx.Timeout(
            45.0,
            connect=30.0,
        )

        text = None
        active_source = None
        source_errors: list[str] = []

        source_order = ordered_sources(
            all_sources,
            preferred_source_id,
        )

        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "OrbitHub/"
                    f"{VERSION} "
                    "(Amateur Radio Satellite Service)"
                )
            },
        ) as client:
            for source in source_order:
                try:
                    candidate_text = (
                        await fetch_source_text(
                            client,
                            source,
                        )
                    )

                    _check_tle_freshness(candidate_text)

                    text = candidate_text
                    active_source = source
                    break

                except Exception as source_exc:
                    source_errors.append(
                        f"{source['name']}: "
                        f"{source_exc!r}"
                    )

        if text is None or active_source is None:
            raise RuntimeError(
                "Keine TLE-Quelle erreichbar: "
                + " | ".join(source_errors)
            )

        parser = TLEParser()

        old_records = []

        if TLE_FILE.exists():
            old_records = parser.parse_file(
                TLE_FILE
            )

        new_records = parser.parse_text(text)

        if not new_records:
            raise ValueError(
                "Die Quelle enthielt keine "
                "verwertbaren TLE-Datensätze."
            )

        new_records = _deduplicate_by_freshness(new_records)
        text = "".join(record.to_tle() for record in new_records)

        old_by_norad = {
            record.norad_id: record
            for record in old_records
        }

        new_by_norad = {
            record.norad_id: record
            for record in new_records
        }

        old_ids = set(old_by_norad)
        new_ids = set(new_by_norad)

        new_satellites = len(
            new_ids - old_ids
        )

        removed_satellites = len(
            old_ids - new_ids
        )

        updated_satellites = 0
        unchanged_satellites = 0

        for norad_id in new_ids & old_ids:
            old_record = old_by_norad[norad_id]
            new_record = new_by_norad[norad_id]

            if (
                old_record.name != new_record.name
                or old_record.line1
                != new_record.line1
                or old_record.line2
                != new_record.line2
            ):
                updated_satellites += 1
            else:
                unchanged_satellites += 1

        temp_file = TLE_FILE.with_suffix(
            ".tmp"
        )

        temp_file.write_text(
            text + "\n",
            encoding="utf-8",
        )

        temp_file.replace(TLE_FILE)

        previous_source = status["source"]

        update_duration_ms = round(
            (
                time.perf_counter()
                - start_time
            )
            * 1000
        )

        fallback_used = (
            active_source["id"]
            != preferred_source_id
        )

        status.update(
            {
                "ok": True,
                "source": active_source["name"],
                "source_id": active_source["id"],
                "preferred_source": (
                    preferred_source["name"]
                ),
                "preferred_source_id": (
                    preferred_source_id
                ),
                "fallback_used": fallback_used,
                "previous_source": previous_source,
                "source_changed": (
                    previous_source is not None
                    and previous_source
                    != active_source["name"]
                ),
                "updated_utc": datetime.now(
                    timezone.utc
                ).isoformat(),
                "records": len(new_records),
                "file_size_bytes": (
                    TLE_FILE.stat().st_size
                ),
                "new_satellites": (
                    new_satellites
                ),
                "updated_satellites": (
                    updated_satellites
                ),
                "removed_satellites": (
                    removed_satellites
                ),
                "unchanged_satellites": (
                    unchanged_satellites
                ),
                "last_update_duration_ms": (
                    update_duration_ms
                ),
                "error": None,
            }
        )

        append_tle_update_event(
            {
                "source": active_source["name"],
                "source_id": active_source["id"],
                "ok": True,
                "duration_ms": update_duration_ms,
                "records": len(new_records),
                "error": None,
            }
        )

    except Exception as exc:
        status.update(
            {
                "ok": TLE_FILE.exists(),
                "preferred_source": (
                    preferred_source["name"]
                ),
                "preferred_source_id": (
                    preferred_source_id
                ),
                "error": repr(exc),
            }
        )

        append_tle_update_event(
            {
                "source": preferred_source["name"],
                "source_id": preferred_source_id,
                "ok": TLE_FILE.exists(),
                "duration_ms": None,
                "records": None,
                "error": repr(exc),
            }
        )

        print(
            f"OrbitHub update error: {exc!r}"
        )


SYSTEM_METRICS_SAMPLE_SECONDS = 300


async def system_metrics_sampler_loop() -> None:
    while True:
        try:
            metrics = collect_system_metrics()
            append_system_metrics_sample(metrics.to_dict())
        except Exception as exc:
            print(f"OrbitHub Metrik-Sampler-Fehler: {exc!r}")

        await asyncio.sleep(SYSTEM_METRICS_SAMPLE_SECONDS)


async def periodic_tle_refresh_loop() -> None:
    while True:
        await asyncio.sleep(TLE_REFRESH_HOURS * 3600)
        await update_tle()
        try:
            prune_old_entries()
        except Exception as exc:
            print(f"OrbitHub Statistik-Bereinigung-Fehler: {exc!r}")


BERLIN_TZ = ZoneInfo("Europe/Berlin")


def _time_display_pref() -> str:
    return load_observer_settings().time_display


def _apply_time_display(value: datetime) -> datetime:
    if _time_display_pref() == "utc":
        return value.astimezone(timezone.utc)

    return value.astimezone(BERLIN_TZ)


def format_time_value(value: datetime, fmt: str) -> str:
    if value is None:
        return ""

    return _apply_time_display(value).strftime(fmt)


def time_zone_label() -> str:
    return "GMT" if _time_display_pref() == "utc" else "Ortszeit"


templates.env.filters["fmt_time"] = format_time_value
templates.env.globals["time_zone_label"] = time_zone_label


def format_update_time() -> str:
    updated_utc = status["updated_utc"]

    if not updated_utc:
        return "Noch nie"

    updated_datetime = datetime.fromisoformat(
        updated_utc
    )

    updated_local = _apply_time_display(updated_datetime)

    return updated_local.strftime(
        "%d.%m.%Y, %H:%M:%S"
    )


def format_duration() -> str:
    total_seconds = (
        status["last_update_duration_ms"] / 1000
    )

    minutes = int(total_seconds // 60)
    remaining_seconds = total_seconds % 60

    if minutes > 0:
        return (
            f"{minutes} Min. "
            f"{remaining_seconds:.1f} Sek."
        )

    return f"{remaining_seconds:.1f} Sek."


def format_tle_file_time() -> str:
    """Format the modification time of the current TLE dataset file."""
    if not TLE_FILE.exists():
        return "Noch nie"

    mtime = datetime.fromtimestamp(
        TLE_FILE.stat().st_mtime,
        tz=timezone.utc,
    )
    local = _apply_time_display(mtime)

    return local.strftime("%d.%m.%Y, %H:%M:%S")


@app.on_event("startup")
async def startup_event() -> None:
    await update_tle()
    asyncio.create_task(system_metrics_sampler_loop())
    asyncio.create_task(periodic_tle_refresh_loop())


@app.get("/")
async def index(request: Request):
    context = {
        "request": request,
        "app_name": APP_NAME,
        "app_slogan": APP_SLOGAN,
        "version": VERSION,
        "codename": CODENAME,
        "refresh_seconds": DASHBOARD_REFRESH_SECONDS,
        "state": (
            "ONLINE"
            if status["ok"]
            else "FEHLER"
        ),
        "state_class": (
            "ok"
            if status["ok"]
            else "error"
        ),
        "source": status["source"] or "Keine",
        "preferred_source": (
            status["preferred_source"] or "Keine"
        ),
        "fallback_used": (
            "Ja"
            if status["fallback_used"]
            else "Nein"
        ),
        "previous_source": (
            status["previous_source"] or "Keine"
        ),
        "source_changed": (
            "Ja"
            if status["source_changed"]
            else "Nein"
        ),
        "records": status["records"],
        "file_size_kib": (
            status["file_size_bytes"] / 1024
        ),
        "file_size_bytes": (
            status["file_size_bytes"]
        ),
        "new_satellites": (
            status["new_satellites"]
        ),
        "updated_satellites": (
            status["updated_satellites"]
        ),
        "removed_satellites": (
            status["removed_satellites"]
        ),
        "unchanged_satellites": (
            status["unchanged_satellites"]
        ),
        "updated_text": format_update_time(),
        "duration_text": format_duration(),
        "error_text": (
            status["error"] or "Kein Fehler"
        ),
    }

    return templates.TemplateResponse(
        name="dashboard.html",
        context=context,
    )

@app.get("/passes")
async def passes_page(
    request: Request,
    satellite: str | None = None,
    hours: int = 24,
    minimum_elevation: float = 10.0,
):
    parser = TLEParser()

    records = (
        parser.parse_file(TLE_FILE)
        if TLE_FILE.exists()
        else []
    )

    allowed_hours = {24, 48, 72}

    if hours not in allowed_hours:
        hours = 24

    minimum_elevation = max(
        0.0,
        min(minimum_elevation, 90.0),
    )

    selected_record = None
    satellite_passes = []

    if records:
        if satellite:
            selected_record = next(
                (
                    record
                    for record in records
                    if record.norad_id == satellite
                ),
                None,
            )

        if selected_record is None:
            selected_record = records[0]

        observer = load_observer_settings()

        predictor = PassPredictor(
            latitude_deg=observer.latitude_deg,
            longitude_deg=observer.longitude_deg,
            elevation_m=observer.elevation_m,
        )

        satellite_passes = predictor.predict(
            selected_record,
            hours=hours,
            minimum_elevation_deg=minimum_elevation,
            observer_settings=observer,
        )

    horizon_shadow_segments = [
        {"d": path}
        for path in (
            _horizon_shadow_path(
                segment.azimuth_from_deg,
                segment.azimuth_to_deg,
                max(
                    segment.minimum_elevation_deg,
                    observer.default_minimum_elevation_deg,
                ),
            )
            for segment in observer.horizon_segments
        )
        if path is not None
    ]

    return templates.TemplateResponse(
        name="passes.html",
        context={
            "request": request,
            "app_name": APP_NAME,
            "app_slogan": APP_SLOGAN,
            "version": VERSION,
            "codename": CODENAME,
            "refresh_seconds": (
                DASHBOARD_REFRESH_SECONDS
            ),
            "records": status["records"],
            "satellites": records,
            "selected_satellite": (
                selected_record
            ),
            "passes": satellite_passes,
            "horizon_shadow_segments": horizon_shadow_segments,
            "observer_name": observer.qth_name,
            "observer_locator": observer.locator,
            "observer_latitude_deg": observer.latitude_deg,
            "observer_longitude_deg": observer.longitude_deg,
            "minimum_elevation": (
                minimum_elevation
            ),
            "hours": hours,
        },
    )
@app.get("/settings")
async def settings_page(request: Request):
    settings = load_observer_settings()

    horizon_segments_json = json.dumps(
        [asdict(segment) for segment in settings.horizon_segments]
    )

    return templates.TemplateResponse(
        name="settings.html",
        context={
            "request": request,
            "app_name": APP_NAME,
            "app_slogan": APP_SLOGAN,
            "version": VERSION,
            "codename": CODENAME,
            "settings": settings,
            "horizon_segments_json": horizon_segments_json,
            "saved": request.query_params.get("saved") == "1",
        },
    )


@app.post("/api/settings/update")
async def update_settings(request: Request) -> dict:
    payload = await request.json()

    def coerce_float(value: object, fallback: float) -> float:
        try:
            return float(str(value).replace(",", "."))
        except (TypeError, ValueError):
            return fallback

    callsign = str(payload.get("callsign", "")).strip().upper() or "DL0AA"
    locator = str(payload.get("locator", "")).strip().upper()
    qth_name = str(payload.get("qth_name", "")).strip() or "QTH"

    time_display = str(payload.get("time_display", "local")).strip().lower()
    if time_display not in ("local", "utc"):
        time_display = "local"

    latitude_deg = None
    longitude_deg = None

    if payload.get("use_locator") and locator:
        try:
            latitude_deg, longitude_deg = locator_to_latlon(locator)
        except ValueError:
            latitude_deg = None
            longitude_deg = None

    if latitude_deg is None or longitude_deg is None:
        latitude_deg = coerce_float(payload.get("latitude_deg"), 52.45)
        longitude_deg = coerce_float(payload.get("longitude_deg"), 13.35)

    elevation_m = coerce_float(payload.get("elevation_m"), 0.0)

    default_minimum_elevation_deg = max(
        0.0,
        min(90.0, coerce_float(payload.get("default_minimum_elevation_deg"), 10.0)),
    )

    horizon_segments = []
    for raw_segment in payload.get("horizon_segments") or []:
        if not isinstance(raw_segment, dict):
            continue

        azimuth_from_deg = coerce_float(raw_segment.get("azimuth_from_deg"), 0.0) % 360.0
        azimuth_to_deg = coerce_float(raw_segment.get("azimuth_to_deg"), 0.0) % 360.0
        segment_minimum_elevation_deg = max(
            0.0,
            min(90.0, coerce_float(raw_segment.get("minimum_elevation_deg"), 0.0)),
        )

        horizon_segments.append(
            HorizonSegment(
                azimuth_from_deg=azimuth_from_deg,
                azimuth_to_deg=azimuth_to_deg,
                minimum_elevation_deg=segment_minimum_elevation_deg,
            )
        )

    settings = ObserverSettings(
        callsign=callsign,
        locator=locator or "JO62QG",
        qth_name=qth_name,
        latitude_deg=latitude_deg,
        longitude_deg=longitude_deg,
        elevation_m=elevation_m,
        default_minimum_elevation_deg=default_minimum_elevation_deg,
        horizon_segments=tuple(horizon_segments),
        time_display=time_display,
    )

    save_observer_settings(settings)

    return {"ok": True}


@app.get("/satellites")
async def satellites_page(request: Request):
    parser = TLEParser()

    records = (
        parser.parse_file(TLE_FILE)
        if TLE_FILE.exists()
        else []
    )

    records = sorted(
        records,
        key=lambda record: display_satellite_name(
            record.name
        ).lower(),
    )

    return templates.TemplateResponse(
        name="satellites.html",
        context={
            "request": request,
            "app_name": APP_NAME,
            "app_slogan": APP_SLOGAN,
            "version": VERSION,
            "codename": CODENAME,
            "refresh_seconds": (
                DASHBOARD_REFRESH_SECONDS
            ),
            "records": status["records"],
            "satellites": records,
        },
    )


@app.get("/sources")
async def sources_page(request: Request):
    settings = load_source_settings(
        SOURCE_SETTINGS_FILE
    )

    preferred_source_id = settings[
        "preferred_source_id"
    ]

    return templates.TemplateResponse(
        name="sources.html",
        context={
            "request": request,
            "app_name": APP_NAME,
            "app_slogan": APP_SLOGAN,
            "version": VERSION,
            "codename": CODENAME,
            "refresh_seconds": (
                DASHBOARD_REFRESH_SECONDS
            ),
            "records": status["records"],
            "sources": [
                source
                for source in get_all_sources()
                if source["id"] != "celestrak-www"
            ],
            "preferred_source_id": (
                preferred_source_id
            ),
            "active_source_id": (
                status["source_id"]
            ),
            "active_source": (
                status["source"] or "Keine"
            ),
            "fallback_used": (
                status["fallback_used"]
            ),
        },
    )


@app.post("/api/sources/add")
async def add_custom_source(
    request: Request,
) -> dict:
    payload = await request.json()

    name = str(
        payload.get("name", "")
    ).strip()

    source_url = str(
        payload.get("url", "")
    ).strip()

    source_type = str(
        payload.get("type", "tle")
    ).strip()

    description = str(
        payload.get("description", "")
    ).strip()

    if not name:
        raise HTTPException(
            status_code=400,
            detail="Bitte einen Namen eingeben.",
        )

    if len(name) > 80:
        raise HTTPException(
            status_code=400,
            detail=(
                "Der Name darf höchstens "
                "80 Zeichen lang sein."
            ),
        )

    parsed_url = urlparse(source_url)

    if (
        parsed_url.scheme not in {"http", "https"}
        or not parsed_url.netloc
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "Bitte eine gültige HTTP- oder "
                "HTTPS-Adresse eingeben."
            ),
        )

    if source_type not in {
        "tle",
        "satnogs_json",
    }:
        raise HTTPException(
            status_code=400,
            detail="Unbekanntes Datenformat.",
        )

    source_id = re.sub(
        r"[^a-z0-9]+",
        "-",
        name.lower(),
    ).strip("-")

    if not source_id:
        raise HTTPException(
            status_code=400,
            detail=(
                "Aus dem Namen konnte keine "
                "gültige Kennung erzeugt werden."
            ),
        )

    source_id = f"custom-{source_id}"

    all_sources = get_all_sources()

    if find_source(all_sources, source_id):
        raise HTTPException(
            status_code=409,
            detail=(
                "Eine Quelle mit diesem Namen "
                "existiert bereits."
            ),
        )

    if any(
        source["url"].rstrip("/")
        == source_url.rstrip("/")
        for source in all_sources
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "Diese Quellenadresse ist bereits "
                "eingetragen."
            ),
        )

    new_source = {
        "id": source_id,
        "name": name,
        "description": (
            description
            or "Benutzerdefinierte TLE-Quelle"
        ),
        "type": source_type,
        "url": source_url,
        "custom": True,
    }

    started = time.perf_counter()

    timeout = httpx.Timeout(
        45.0,
        connect=30.0,
    )

    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "OrbitHub/"
                    f"{VERSION}"
                )
            },
        ) as client:
            candidate_text = (
                await fetch_source_text(
                    client,
                    new_source,
                )
            )

        records = TLEParser().parse_text(
            candidate_text
        )

        if not records:
            raise ValueError(
                "Keine verwertbaren "
                "TLE-Datensätze gefunden."
            )

    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                "Die Quelle konnte nicht "
                "gespeichert werden: "
                f"{exc}"
            ),
        ) from exc

    try:
        source_manager.add_custom_source(
            new_source
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    duration_ms = round(
        (
            time.perf_counter()
            - started
        )
        * 1000
    )

    return {
        "ok": True,
        "source": new_source,
        "records": len(records),
        "duration_ms": duration_ms,
    }


@app.post("/api/sources/update")
async def update_custom_source(
    request: Request,
) -> dict:
    payload = await request.json()

    source_id = str(
        payload.get("source_id", "")
    ).strip()

    name = str(
        payload.get("name", "")
    ).strip()

    source_url = str(
        payload.get("url", "")
    ).strip()

    source_type = str(
        payload.get("type", "tle")
    ).strip()

    description = str(
        payload.get("description", "")
    ).strip()

    if not source_id:
        raise HTTPException(
            status_code=400,
            detail="Keine Quellenkennung angegeben.",
        )

    source = source_manager.get_source(
        source_id
    )

    if source is None:
        raise HTTPException(
            status_code=404,
            detail="Unbekannte TLE-Quelle.",
        )

    if source_manager.is_builtin_source(
        source_id
    ):
        raise HTTPException(
            status_code=403,
            detail=(
                "Eingebaute TLE-Quellen "
                "koennen nicht geaendert werden."
            ),
        )

    if not name:
        raise HTTPException(
            status_code=400,
            detail="Der Quellenname fehlt.",
        )

    if not source_url:
        raise HTTPException(
            status_code=400,
            detail="Die Quellenadresse fehlt.",
        )

    if source_type not in {
        "tle",
        "satnogs_json",
    }:
        raise HTTPException(
            status_code=400,
            detail="Unbekanntes Datenformat.",
        )

    updated_source = {
        "id": source_id,
        "name": name,
        "description": (
            description
            or "Benutzerdefinierte TLE-Quelle"
        ),
        "type": source_type,
        "url": source_url,
        "custom": True,
    }

    started = time.perf_counter()

    timeout = httpx.Timeout(
        45.0,
        connect=30.0,
    )

    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "OrbitHub/"
                    f"{VERSION}"
                )
            },
        ) as client:
            candidate_text = (
                await fetch_source_text(
                    client,
                    updated_source,
                )
            )

        records = TLEParser().parse_text(
            candidate_text
        )

        if not records:
            raise ValueError(
                "Keine verwertbaren "
                "TLE-Datensaetze gefunden."
            )

    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                "Die geaenderte Quelle konnte "
                "nicht gespeichert werden: "
                f"{exc}"
            ),
        ) from exc

    try:
        source_manager.update_custom_source(
            source_id,
            updated_source,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail="Unbekannte eigene TLE-Quelle.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=403,
            detail=str(exc),
        ) from exc

    if source_id == status.get(
        "preferred_source_id"
    ):
        status["preferred_source"] = name

    duration_ms = round(
        (
            time.perf_counter()
            - started
        )
        * 1000
    )

    return {
        "ok": True,
        "source": updated_source,
        "records": len(records),
        "duration_ms": duration_ms,
    }


@app.post("/api/sources/delete")
async def delete_custom_source(
    request: Request,
) -> dict:
    payload = await request.json()

    source_id = str(
        payload.get("source_id", "")
    ).strip()

    if not source_id:
        raise HTTPException(
            status_code=400,
            detail="Keine Quellenkennung angegeben.",
        )

    source = source_manager.get_source(
        source_id
    )

    if source is None:
        raise HTTPException(
            status_code=404,
            detail="Unbekannte TLE-Quelle.",
        )

    if source_manager.is_builtin_source(
        source_id
    ):
        raise HTTPException(
            status_code=403,
            detail=(
                "Eingebaute TLE-Quellen "
                "koennen nicht geloescht werden."
            ),
        )

    if source_id == status.get(
        "preferred_source_id"
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "Die bevorzugte TLE-Quelle "
                "kann nicht geloescht werden. "
                "Waehle zuerst eine andere Quelle."
            ),
        )

    try:
        source_manager.delete_custom_source(
            source_id
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail="Unbekannte eigene TLE-Quelle.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=403,
            detail=str(exc),
        ) from exc

    return {
        "ok": True,
        "source_id": source_id,
        "source_name": source["name"],
    }


@app.post("/api/sources/select")
async def select_source(
    request: Request,
) -> dict:
    payload = await request.json()
    source_id = str(
        payload.get("source_id", "")
    ).strip()

    source = find_source(
        get_all_sources(),
        source_id,
    )

    if source is None:
        raise HTTPException(
            status_code=404,
            detail="Unbekannte TLE-Quelle.",
        )

    save_preferred_source(
        SOURCE_SETTINGS_FILE,
        source_id,
    )

    status["preferred_source"] = (
        source["name"]
    )

    status["preferred_source_id"] = (
        source_id
    )

    return {
        "ok": True,
        "preferred_source_id": source_id,
        "preferred_source": source["name"],
    }


@app.post("/api/sources/test")
async def test_source(
    request: Request,
) -> dict:
    payload = await request.json()
    source_id = str(
        payload.get("source_id", "")
    ).strip()

    source = find_source(
        get_all_sources(),
        source_id,
    )

    if source is None:
        raise HTTPException(
            status_code=404,
            detail="Unbekannte TLE-Quelle.",
        )

    started = time.perf_counter()

    timeout = httpx.Timeout(
        45.0,
        connect=30.0,
    )

    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "OrbitHub/"
                    f"{VERSION}"
                )
            },
        ) as client:
            candidate_text = (
                await fetch_source_text(
                    client,
                    source,
                )
            )

        records = TLEParser().parse_text(
            candidate_text
        )

        duration_ms = round(
            (
                time.perf_counter()
                - started
            )
            * 1000
        )

        return {
            "ok": True,
            "source_id": source_id,
            "source": source["name"],
            "records": len(records),
            "duration_ms": duration_ms,
        }

    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                "Quellentest fehlgeschlagen: "
                f"{exc}"
            ),
        ) from exc


@app.post("/api/sources/refresh")
async def update_selected_source() -> dict:
    await update_tle()
    return status


@app.get("/about")
async def about_page(request: Request):
    settings = load_observer_settings()

    return templates.TemplateResponse(
        name="about.html",
        context={
            "request": request,
            "app_name": APP_NAME,
            "app_slogan": APP_SLOGAN,
            "version": VERSION,
            "codename": CODENAME,
            "observer_name": settings.qth_name,
            "observer_locator": settings.locator,
        },
    )


_GERMAN_MONTHS = [
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
]


def format_history_date(date_str: str) -> str:
    """Formatiert YYYY-MM-DD als deutsches Datum, z. B. 25. Juli 2026."""
    try:
        year, month, day = date_str.split("-")
        return f"{int(day)}. {_GERMAN_MONTHS[int(month) - 1]} {year}"
    except (ValueError, IndexError):
        return date_str


def load_history_entries() -> list[dict]:
    """Lädt die Änderungshistorie aus data/history.json (neueste zuerst)."""
    if not HISTORY_FILE.exists():
        return []
    try:
        raw = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return raw if isinstance(raw, list) else []


@app.get("/map")
async def map_page(request: Request):
    parser = TLEParser()

    records = (
        parser.parse_file(TLE_FILE)
        if TLE_FILE.exists()
        else []
    )

    records = sorted(
        records,
        key=lambda record: display_satellite_name(
            record.name,
        ).lower(),
    )

    observer = load_observer_settings()

    return templates.TemplateResponse(
        name="map.html",
        context={
            "request": request,
            "app_name": APP_NAME,
            "app_slogan": APP_SLOGAN,
            "version": VERSION,
            "codename": CODENAME,
            "satellites": records,
            "observer_name": observer.qth_name,
            "observer_locator": observer.locator,
            "observer_latitude_deg": observer.latitude_deg,
            "observer_longitude_deg": observer.longitude_deg,
            "tle_generated": format_tle_file_time(),
        },
    )


@app.get("/api/satellites/positions")
async def satellite_positions(indices: str = "") -> dict:
    """Liefert die aktuelle Position (Subpunkt) fuer ausgewaehlte Satelliten.

    Die Auswahl erfolgt ueber den Index in der (alphabetisch sortierten)
    Satellitenliste, nicht ueber die NORAD-ID: Manche Kataloge enthalten
    mehrere Eintraege (z. B. verschiedene ISS-Module) mit derselben
    NORAD-ID, die sich sonst nicht eindeutig auseinanderhalten liessen.
    """
    requested_indices: set[int] = set()
    for value in indices.split(","):
        value = value.strip()
        if not value:
            continue
        try:
            requested_indices.add(int(value))
        except ValueError:
            continue

    if not requested_indices:
        return {"positions": []}

    parser = TLEParser()
    records = (
        parser.parse_file(TLE_FILE)
        if TLE_FILE.exists()
        else []
    )
    records = sorted(
        records,
        key=lambda record: display_satellite_name(
            record.name,
        ).lower(),
    )

    observer = load_observer_settings()
    predictor = PassPredictor(
        latitude_deg=observer.latitude_deg,
        longitude_deg=observer.longitude_deg,
        elevation_m=observer.elevation_m,
    )

    positions = []
    for index in sorted(requested_indices):
        if index < 0 or index >= len(records):
            continue

        record = records[index]
        position = predictor.current_position(record)
        positions.append(
            {
                "id": index,
                "norad_id": record.norad_id,
                "name": display_satellite_name(record.name),
                **position,
            }
        )

    return {"positions": positions}


@app.get("/api/satellites/track")
async def satellite_track(
    index: int,
    minutes_back: float = 15.0,
    minutes_forward: float = 45.0,
) -> dict:
    """Liefert die Bodenspur (Ground-Track) eines Satelliten fuer die Kartenansicht."""
    parser = TLEParser()
    records = (
        parser.parse_file(TLE_FILE)
        if TLE_FILE.exists()
        else []
    )
    records = sorted(
        records,
        key=lambda record: display_satellite_name(
            record.name,
        ).lower(),
    )

    if index < 0 or index >= len(records):
        return {"track": []}

    record = records[index]
    observer = load_observer_settings()
    predictor = PassPredictor(
        latitude_deg=observer.latitude_deg,
        longitude_deg=observer.longitude_deg,
        elevation_m=observer.elevation_m,
    )

    track_points = predictor.ground_track(
        record,
        minutes_back=minutes_back,
        minutes_forward=minutes_forward,
    )

    return {
        "track": [
            {
                "timestamp": point.timestamp.isoformat(),
                "lat_deg": point.lat_deg,
                "lon_deg": point.lon_deg,
            }
            for point in track_points
        ],
    }


@app.get("/history")
async def history_page(request: Request):
    entries = load_history_entries()

    days: list[dict] = []
    current_date = None
    for entry in entries:
        date = entry.get("date", "")
        if date != current_date:
            days.append(
                {
                    "date": date,
                    "date_label": format_history_date(date),
                    "entries": [],
                }
            )
            current_date = date
        days[-1]["entries"].append(entry)

    return templates.TemplateResponse(
        name="history.html",
        context={
            "request": request,
            "app_name": APP_NAME,
            "app_slogan": APP_SLOGAN,
            "days": days,
            "total_entries": len(entries),
        },
    )


@app.get("/health")
async def health() -> dict:
    return {
        "status": (
            "ok"
            if status["ok"]
            else "warning"
        ),
        "version": VERSION,
        "codename": CODENAME,
    }


@app.get("/status")
async def get_status() -> dict:
    return status


@app.post("/update")
async def manual_update() -> dict:
    await update_tle()
    return status


@app.get(
    "/tle/all-active.tle",
    response_class=PlainTextResponse,
)
async def all_active_tle():
    if not TLE_FILE.exists():
        raise HTTPException(
            status_code=503,
            detail="Noch keine TLE-Datei verfügbar",
        )

    parser = TLEParser()
    exporter = StandardExporter()

    records = parser.parse_file(TLE_FILE)
    content = exporter.export(records)

    return PlainTextResponse(content)


@app.get(
    "/satgazer/all-active.tle",
    response_class=PlainTextResponse,
)
async def satgazer_all_active():
    if not TLE_FILE.exists():
        raise HTTPException(
            status_code=503,
            detail="Noch keine TLE-Datei verfügbar",
        )

    parser = TLEParser()
    exporter = SatGazerExporter()

    records = parser.parse_file(TLE_FILE)
    content = exporter.export(records)

    return PlainTextResponse(content)

@app.get(
    "/visibility",
    include_in_schema=False,
)
async def visibility_page(
    request: Request,
    satellite: str | None = None,
    hours: int = 72,
    minimum_elevation: float = 10.0,
):
    parser = TLEParser()
    records = (
        parser.parse_file(TLE_FILE)
        if TLE_FILE.exists()
        else []
    )
    records = sorted(
        records,
        key=lambda record: display_satellite_name(record.name).lower(),
    )

    allowed_hours = {24, 48, 72, 168}
    if hours not in allowed_hours:
        hours = 72

    minimum_elevation = max(0.0, min(minimum_elevation, 90.0))

    observer = load_observer_settings()
    predictor = PassPredictor(
        latitude_deg=observer.latitude_deg,
        longitude_deg=observer.longitude_deg,
        elevation_m=observer.elevation_m,
    )

    selected_record = None
    satellite_passes = []

    if records:
        if satellite:
            selected_record = next(
                (
                    record
                    for record in records
                    if record.norad_id == satellite
                ),
                None,
            )

        if selected_record is None:
            selected_record = next(
                (
                    record
                    for record in records
                    if is_known_bright_satellite(record.name)
                ),
                records[0],
            )

        raw_passes = predictor.predict(
            selected_record,
            hours=hours,
            minimum_elevation_deg=minimum_elevation,
            observer_settings=observer,
        )

        for satellite_pass in raw_passes:
            result = assess_visibility(
                selected_record,
                observer.latitude_deg,
                observer.longitude_deg,
                observer.elevation_m,
                satellite_pass.culmination_time,
            )
            if result.sun_altitude_deg > SUN_ALTITUDE_THRESHOLD_DEG:
                continue
            satellite_passes.append(
                {
                    "pass": satellite_pass,
                    "visibility": result,
                }
            )

    bright_entries = []
    upcoming_visible_passes = []
    bright_records = [
        record
        for record in records
        if is_known_bright_satellite(record.name)
    ]

    for record in bright_records:
        candidate_passes = predictor.predict(
            record,
            hours=168,
            minimum_elevation_deg=(
                observer.default_minimum_elevation_deg
            ),
            observer_settings=observer,
        )

        next_visible = None
        for candidate in candidate_passes:
            result = assess_visibility(
                record,
                observer.latitude_deg,
                observer.longitude_deg,
                observer.elevation_m,
                candidate.culmination_time,
            )
            if result.visible:
                visible_entry = {
                    "record": record,
                    "pass": candidate,
                    "visibility": result,
                }
                if next_visible is None:
                    next_visible = visible_entry
                upcoming_visible_passes.append(visible_entry)

        bright_entries.append(
            {
                "record": record,
                "next_visible": next_visible,
            }
        )

    upcoming_visible_passes.sort(key=lambda entry: entry["pass"].rise_time)

    return templates.TemplateResponse(
        name="visibility.html",
        context={
            "request": request,
            "app_name": APP_NAME,
            "app_slogan": APP_SLOGAN,
            "version": VERSION,
            "codename": CODENAME,
            "refresh_seconds": DASHBOARD_REFRESH_SECONDS,
            "satellites": records,
            "selected_satellite": selected_record,
            "satellite_passes": satellite_passes,
            "bright_entries": bright_entries,
            "upcoming_visible_passes": upcoming_visible_passes,
            "hours": hours,
            "minimum_elevation": minimum_elevation,
            "observer_name": observer.qth_name,
            "observer_locator": observer.locator,
        },
    )


@app.get(
    "/downloads",
    include_in_schema=False,
)
async def downloads_page(request: Request):
    parser = TLEParser()
    records = (
        parser.parse_file(TLE_FILE)
        if TLE_FILE.exists()
        else []
    )
    records = sorted(
        records,
        key=lambda record: display_satellite_name(record.name).lower(),
    )
    return templates.TemplateResponse(
        name="downloads.html",
        context={
            "request": request,
            "app_name": APP_NAME,
            "app_slogan": APP_SLOGAN,
            "version": VERSION,
            "codename": CODENAME,
            "refresh_seconds": DASHBOARD_REFRESH_SECONDS,
            "satellites": records,
        },
    )


@app.get(
    "/downloads/tle",
    include_in_schema=False,
)
async def download_tle_export(
    format: str = "neu",
    ids: str = "",
) -> PlainTextResponse:
    from datetime import datetime

    if not TLE_FILE.exists():
        raise HTTPException(
            status_code=404,
            detail="Noch keine TLE-Datei vorhanden.",
        )

    parser = TLEParser()
    records = parser.parse_file(TLE_FILE)

    selected_ids = {
        part.strip()
        for part in ids.split(",")
        if part.strip()
    }
    if selected_ids:
        records = [
            record
            for record in records
            if record.norad_id in selected_ids
        ]
        if not records:
            raise HTTPException(
                status_code=404,
                detail="Keine passenden Satelliten in der Auswahl gefunden.",
            )

    if format == "alt":
        exporter = ClassicExporter()
        format_tag = "2LE"
    else:
        exporter = StandardExporter()
        format_tag = "3LE"

    content = exporter.export(records)
    scope_tag = "Auswahl" if selected_ids else "alle"
    filename = (
        f"OrbitHub-TLE-{scope_tag}-{format_tag}-"
        f"{datetime.now():%Y-%m-%d}.txt"
    )

    return PlainTextResponse(
        content,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@app.get(
    "/statistics",
    include_in_schema=False,
)
async def statistics_page(request: Request):
    return templates.TemplateResponse(
        name="statistics.html",
        context={
            "request": request,
            "app_name": APP_NAME,
            "app_slogan": APP_SLOGAN,
            "version": VERSION,
            "codename": CODENAME,
            "refresh_seconds": DASHBOARD_REFRESH_SECONDS,
        },
    )


@app.get(
    "/downloads/orbithub-tle.txt",
    include_in_schema=False,
)
def download_orbithub_tle_txt() -> FileResponse:
    """Download the current TLE dataset as a TXT file."""
    from datetime import datetime

    if not TLE_FILE.exists():
        raise HTTPException(
            status_code=404,
            detail="Noch keine TLE-Datei vorhanden.",
        )

    filename = (
        "OrbitHub-all-active-"
        f"{datetime.now():%Y-%m-%d}.txt"
    )

    return FileResponse(
        path=str(TLE_FILE),
        media_type="text/plain; charset=utf-8",
        filename=filename,
    )

