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
    response.raise_for_status()

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
