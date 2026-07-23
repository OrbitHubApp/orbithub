from datetime import datetime, timezone
import time

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import FileResponse
from app.api.system import router as system_router

from app.config import (
    APP_DESCRIPTION,
    APP_NAME,
    APP_SLOGAN,
    BASE_DIR,
    DASHBOARD_REFRESH_SECONDS,
    DATA_DIR,
    SOURCE_URLS,
    TLE_FILE,
)
from app.exporters.satgazer import SatGazerExporter
from app.exporters.standard import StandardExporter
from app.services.tle_parser import TLEParser
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


status = {
    "ok": False,
    "source": None,
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

    try:
        start_time = time.perf_counter()
        timeout = httpx.Timeout(45.0, connect=30.0)

        text = None
        active_source = None
        source_errors = []

        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
        ) as client:
            for source in SOURCE_URLS:
                source_name = source["name"]
                source_type = source["type"]
                source_url = source["url"]

                try:
                    response = await client.get(source_url)
                    response.raise_for_status()

                    if source_type == "tle":
                        candidate_text = response.text.strip()

                    elif source_type == "satnogs_json":
                        payload = response.json()
                        tle_lines = []

                        for item in payload:
                            tle0 = item.get("tle0")
                            tle1 = item.get("tle1")
                            tle2 = item.get("tle2")

                            if tle0 and tle1 and tle2:
                                tle_lines.extend(
                                    [tle0, tle1, tle2]
                                )

                        candidate_text = "\n".join(
                            tle_lines
                        ).strip()

                    else:
                        raise ValueError(
                            "Unbekannter Quellentyp: "
                            f"{source_type}"
                        )

                    if not candidate_text:
                        raise ValueError(
                            "Quelle lieferte keine TLE-Daten."
                        )

                    text = candidate_text
                    active_source = source_name
                    break

                except Exception as source_exc:
                    source_errors.append(
                        f"{source_name}: {source_exc!r}"
                    )

        if text is None or active_source is None:
            raise RuntimeError(
                "Keine TLE-Quelle erreichbar: "
                + " | ".join(source_errors)
            )

        if "\n1 " not in f"\n{text}":
            raise ValueError(
                "Die empfangenen Daten sehen nicht "
                "wie TLE-Daten aus."
            )

        parser = TLEParser()

        old_records = []

        if TLE_FILE.exists():
            old_records = parser.parse_file(TLE_FILE)

        new_records = parser.parse_text(text)

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

        new_satellites = len(new_ids - old_ids)
        removed_satellites = len(old_ids - new_ids)

        updated_satellites = 0
        unchanged_satellites = 0

        for norad_id in new_ids & old_ids:
            old_record = old_by_norad[norad_id]
            new_record = new_by_norad[norad_id]

            if (
                old_record.name != new_record.name
                or old_record.line1 != new_record.line1
                or old_record.line2 != new_record.line2
            ):
                updated_satellites += 1
            else:
                unchanged_satellites += 1

        temp_file = TLE_FILE.with_suffix(".tmp")

        temp_file.write_text(
            text + "\n",
            encoding="utf-8",
        )

        temp_file.replace(TLE_FILE)

        previous_source = status["source"]

        update_duration_ms = round(
            (time.perf_counter() - start_time) * 1000
        )

        status.update(
            {
                "ok": True,
                "source": active_source,
                "previous_source": previous_source,
                "source_changed": (
                    previous_source is not None
                    and previous_source != active_source
                ),
                "updated_utc": datetime.now(
                    timezone.utc
                ).isoformat(),
                "records": len(new_records),
                "file_size_bytes": TLE_FILE.stat().st_size,
                "new_satellites": new_satellites,
                "updated_satellites": updated_satellites,
                "removed_satellites": removed_satellites,
                "unchanged_satellites": unchanged_satellites,
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
                "error": repr(exc),
            }
        )

        print(f"OrbitHub update error: {exc!r}")


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

