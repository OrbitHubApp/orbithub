from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx


DEFAULT_SOURCE_ID = "satnogs"

SPACETRACK_LOGIN_URL = (
    "https://www.space-track.org/ajaxauth/login"
)


def load_source_settings(
    settings_file: Path,
) -> dict[str, Any]:
    if not settings_file.exists():
        return {
            "preferred_source_id": DEFAULT_SOURCE_ID,
        }

    try:
        payload = json.loads(
            settings_file.read_text(
                encoding="utf-8"
            )
        )
    except (
        OSError,
        json.JSONDecodeError,
    ):
        return {
            "preferred_source_id": DEFAULT_SOURCE_ID,
        }

    preferred_source_id = payload.get(
        "preferred_source_id",
        DEFAULT_SOURCE_ID,
    )

    return {
        "preferred_source_id": preferred_source_id,
    }


def save_preferred_source(
    settings_file: Path,
    source_id: str,
) -> None:
    settings_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_file = settings_file.with_suffix(
        ".tmp"
    )

    temporary_file.write_text(
        json.dumps(
            {
                "preferred_source_id": source_id,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    temporary_file.replace(settings_file)


def load_custom_sources(
    sources_file: Path,
) -> list[dict[str, str]]:
    if not sources_file.exists():
        return []

    try:
        payload = json.loads(
            sources_file.read_text(
                encoding="utf-8"
            )
        )
    except (
        OSError,
        json.JSONDecodeError,
    ):
        return []

    raw_sources = payload.get("sources", [])

    if not isinstance(raw_sources, list):
        return []

    valid_sources: list[dict[str, str]] = []

    for source in raw_sources:
        if not isinstance(source, dict):
            continue

        required_fields = (
            "id",
            "name",
            "description",
            "type",
            "url",
        )

        if not all(
            isinstance(source.get(field), str)
            and source[field].strip()
            for field in required_fields
        ):
            continue

        if source["type"] not in {
            "tle",
            "satnogs_json",
        }:
            continue

        valid_sources.append(
            {
                "id": source["id"].strip(),
                "name": source["name"].strip(),
                "description": (
                    source["description"].strip()
                ),
                "type": source["type"].strip(),
                "url": source["url"].strip(),
                "custom": True,
            }
        )

    return valid_sources


def save_custom_sources(
    sources_file: Path,
    sources: list[dict[str, str]],
) -> None:
    sources_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_file = sources_file.with_suffix(
        ".tmp"
    )

    temporary_file.write_text(
        json.dumps(
            {
                "sources": sources,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    temporary_file.replace(sources_file)


def find_source(
    sources: list[dict[str, str]],
    source_id: str,
) -> dict[str, str] | None:
    for source in sources:
        if source["id"] == source_id:
            return source

    return None


def ordered_sources(
    sources: list[dict[str, str]],
    preferred_source_id: str,
) -> list[dict[str, str]]:
    preferred = find_source(
        sources,
        preferred_source_id,
    )

    if preferred is None:
        return list(sources)

    return [
        preferred,
        *[
            source
            for source in sources
            if source["id"] != preferred_source_id
        ],
    ]


async def _fetch_spacetrack_response(
    client: httpx.AsyncClient,
    source: dict[str, str],
    spacetrack_credentials: dict[str, str] | None,
) -> httpx.Response:
    if not spacetrack_credentials:
        raise ValueError(
            "Fuer Space-Track sind noch keine Zugangsdaten "
            "hinterlegt. Bitte auf der Seite Daten & Quellen "
            "Benutzername und Passwort eingeben."
        )

    login_response = await client.post(
        SPACETRACK_LOGIN_URL,
        data={
            "identity": spacetrack_credentials["identity"],
            "password": spacetrack_credentials["password"],
        },
    )

    body_text = login_response.text.strip()
    login_failed = True
    failure_detail = ""

    if login_response.status_code == 200:
        try:
            parsed_body = json.loads(body_text) if body_text else ""
        except ValueError:
            parsed_body = body_text

        if parsed_body in ("", None):
            # Space-Track antwortet bei Erfolg mit HTTP 200 und
            # entweder komplett leerem Body oder dem JSON-Leerstring
            # '""' - beides bedeutet: Anmeldung erfolgreich.
            login_failed = False
        elif isinstance(parsed_body, dict) and "Login" in parsed_body:
            failure_detail = str(parsed_body["Login"])
        else:
            failure_detail = body_text[:300]
    else:
        failure_detail = body_text[:300]

    if login_failed:
        detail = (
            "Anmeldung bei Space-Track fehlgeschlagen "
            f"(HTTP {login_response.status_code})"
        )
        if failure_detail:
            detail += f": {failure_detail}"
        raise ValueError(detail)

    return await client.get(source["url"])


async def fetch_source_text(
    client: httpx.AsyncClient,
    source: dict[str, str],
    spacetrack_credentials: dict[str, str] | None = None,
) -> str:
    if source["type"] == "spacetrack":
        response = await _fetch_spacetrack_response(
            client,
            source,
            spacetrack_credentials,
        )
    else:
        response = await client.get(source["url"])
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        body_preview = response.text.strip()
        if (
            response.status_code == 403
            and "has not updated since" in body_preview.lower()
        ):
            raise ValueError(
                "CelesTrak hat diese Daten erst kürzlich aktualisiert "
                "und blockiert kurzfristig wiederholte Abfragen "
                "(eigenes Rate-Limit von CelesTrak, alle 2 Stunden). "
                "Das ist kein Fehler in OrbitHub - bitte später "
                "erneut versuchen."
            ) from exc

        detail = f"HTTP {response.status_code}"
        if body_preview:
            detail += f": {body_preview[:300]}"
        raise ValueError(detail) from exc

    source_type = source["type"]

    if source_type in ("tle", "spacetrack"):
        candidate_text = response.text.strip()

    elif source_type == "satnogs_json":
        payload = response.json()
        tle_lines: list[str] = []

        if not isinstance(payload, list):
            raise ValueError(
                "SatNOGS lieferte kein JSON-Array."
            )

        for item in payload:
            if not isinstance(item, dict):
                continue

            tle0 = item.get("tle0")
            tle1 = item.get("tle1")
            tle2 = item.get("tle2")

            if tle0 and tle1 and tle2:
                tle_lines.extend(
                    [
                        str(tle0),
                        str(tle1),
                        str(tle2),
                    ]
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

    if "\n1 " not in f"\n{candidate_text}":
        raise ValueError(
            "Die empfangenen Daten sehen "
            "nicht wie TLE-Daten aus."
        )

    return candidate_text


def load_spacetrack_credentials(
    credentials_file: Path,
) -> dict[str, str] | None:
    """Load Space-Track credentials, or None if unavailable."""
    if not credentials_file.exists():
        return None

    try:
        payload = json.loads(
            credentials_file.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return None

    identity = str(payload.get("identity", "")).strip()
    password = str(payload.get("password", "")).strip()

    if not identity or not password:
        return None

    return {"identity": identity, "password": password}


def save_spacetrack_credentials(
    credentials_file: Path,
    identity: str,
    password: str,
) -> None:
    """Persist Space-Track credentials to disk."""
    credentials_file.parent.mkdir(parents=True, exist_ok=True)

    temporary_file = credentials_file.with_suffix(".tmp")
    temporary_file.write_text(
        json.dumps(
            {
                "identity": identity,
                "password": password,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    temporary_file.replace(credentials_file)


def delete_spacetrack_credentials(
    credentials_file: Path,
) -> None:
    """Remove stored Space-Track credentials, if any."""
    credentials_file.unlink(missing_ok=True)


def has_spacetrack_credentials(
    credentials_file: Path,
) -> bool:
    """Return True if usable Space-Track credentials exist."""
    return (
        load_spacetrack_credentials(credentials_file) is not None
    )
