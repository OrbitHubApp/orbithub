from pathlib import Path
import os


APP_NAME = "OrbitHub"
APP_SLOGAN = "Your Local Satellite Orbit Service"
APP_DESCRIPTION = "Self-hosted satellite orbit data service"

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path("/app/data")

TLE_FILE = DATA_DIR / "all-active.tle"
SOURCE_SETTINGS_FILE = DATA_DIR / "source-settings.json"
CUSTOM_SOURCES_FILE = DATA_DIR / "custom-sources.json"

DASHBOARD_REFRESH_SECONDS = 60

TLE_REFRESH_HOURS = int(
    os.getenv("ORBITHUB_REFRESH_HOURS", "6")
)

SOURCE_URLS = [
    {
        "id": "satnogs",
        "name": "SatNOGS",
        "description": (
            "Offene Satellitendatenbank der "
            "Amateurfunk-Community"
        ),
        "type": "satnogs_json",
        "url": (
            "https://db.satnogs.org/api/tle/"
            "?format=json"
        ),
    },
    {
        "id": "celestrak",
        "name": "CelesTrak",
        "description": (
            "Aktive Satelliten aus dem "
            "NORAD-Katalog"
        ),
        "type": "tle",
        "url": (
            "https://celestrak.org/NORAD/elements/"
            "gp.php?GROUP=ACTIVE&FORMAT=TLE"
        ),
    },
    {
        "id": "celestrak-www",
        "name": "CelesTrak WWW",
        "description": (
            "Alternativer CelesTrak-Endpunkt"
        ),
        "type": "tle",
        "url": (
            "https://www.celestrak.org/NORAD/"
            "elements/gp.php?"
            "GROUP=ACTIVE&FORMAT=TLE"
        ),
    },
]
