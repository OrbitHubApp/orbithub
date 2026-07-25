from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx


DEFAULT_SOURCE_ID = "satnogs"


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


async def fetch_source_text(
    client: httpx.AsyncClient,
    source: dict[str, str],
) -> str:
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

    if source_type == "tle":
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
