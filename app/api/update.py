"""OrbitHub: Pruefung auf neue Version via GitHub.

Vergleicht die lokale app/version.py mit der Version im oeffentlichen
GitHub-Repository (main-Branch). Loest KEINEN automatischen Pull/Rebuild
aus - der Anwender fuehrt das Update weiterhin selbst per SSH aus. Diese
Route liefert lediglich die Information, ob ein Update verfuegbar ist,
plus den passenden Befehl zum Kopieren.
"""

import re

import httpx
from fastapi import APIRouter

from app.version import CODENAME, VERSION

router = APIRouter(
    prefix="/api/update",
    tags=["Update"],
)

GITHUB_VERSION_URL = (
    "https://raw.githubusercontent.com/OrbitHubApp/orbithub/main/app/version.py"
)
GITHUB_COMMITS_URL = "https://github.com/OrbitHubApp/orbithub/commits/main"
UPDATE_COMMAND = "cd ~/orbithub && git pull && docker compose up -d --build"

_VERSION_RE = re.compile(r'VERSION\s*=\s*"([^"]+)"')
_CODENAME_RE = re.compile(r'CODENAME\s*=\s*"([^"]+)"')


@router.get("/check")
async def check_for_update() -> dict:
    timeout = httpx.Timeout(10.0, connect=5.0)

    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": f"OrbitHub/{VERSION}"},
        ) as client:
            response = await client.get(GITHUB_VERSION_URL)
            response.raise_for_status()
            text = response.text
    except Exception as exc:
        return {
            "ok": False,
            "error": f"Pruefung nicht moeglich: {exc}",
            "current_version": VERSION,
            "current_codename": CODENAME,
        }

    version_match = _VERSION_RE.search(text)
    if not version_match:
        return {
            "ok": False,
            "error": "Version auf GitHub konnte nicht gelesen werden.",
            "current_version": VERSION,
            "current_codename": CODENAME,
        }

    codename_match = _CODENAME_RE.search(text)
    latest_version = version_match.group(1)
    latest_codename = codename_match.group(1) if codename_match else None

    return {
        "ok": True,
        "current_version": VERSION,
        "current_codename": CODENAME,
        "latest_version": latest_version,
        "latest_codename": latest_codename,
        "update_available": latest_version != VERSION,
        "update_command": UPDATE_COMMAND,
        "commits_url": GITHUB_COMMITS_URL,
    }
