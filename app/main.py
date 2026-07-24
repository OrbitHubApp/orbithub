from datetime import datetime, timezone
import re
import time
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import FileResponse, RedirectResponse
from app.api.system import router as system_router

from app.config import (
    APP_DESCRIPTION,
    APP_NAME,
    APP_SLOGAN,
    BASE_DIR,
    DASHBOARD_REFRESH_SECONDS,
    CUSTOM_SOURCES_FILE,
    DATA_DIR,
    SOURCE_SETTINGS_FILE,
    SOURCE_URLS,
    TLE_FILE,
)
from app.exporters.satgazer import SatGazerExporter
from app.exporters.standard import StandardExporter
from app.services.tle_parser import TLEParser
from app.services.pass_predictor import PassPredictor
from app.services.source_manager import SourceManager
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

templates = Jinja2Templates(
    directory=str(BASE_DIR / "templates")
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

        print(
            f"OrbitHub update error: {exc!r}"
        )


def format_update_time() -> str:
    updated_utc = status["updated_utc"]

    if not updated_utc:
        return "Noch nie"

    updated_datetime = datetime.fromisoformat(
        updated_utc
    )

    updated_local = updated_datetime.astimezone()

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


@app.on_event("startup")
async def startup_event() -> None:
    await update_tle()


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

        predictor = PassPredictor(
            latitude_deg=52.45,
            longitude_deg=13.35,
            elevation_m=50,
        )

        satellite_passes = predictor.predict(
            selected_record,
            hours=hours,
            minimum_elevation_deg=(
                minimum_elevation
            ),
        )

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
            "observer_name": "Berlin",
            "observer_locator": "JO62PL",
            "minimum_elevation": (
                minimum_elevation
            ),
            "hours": hours,
        },
    )
@app.get("/satellites")
async def satellites_page(request: Request):
    parser = TLEParser()

    records = (
        parser.parse_file(TLE_FILE)
        if TLE_FILE.exists()
        else []
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


@app.post("/api/sources/update")
async def update_selected_source() -> dict:
    await update_tle()
    return status


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

