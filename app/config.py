from pathlib import Path
import os

APP_NAME = "OrbitHub"
APP_SLOGAN = "Your Local Satellite Orbit Service"
APP_DESCRIPTION = "Self-hosted satellite orbit data service"

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path("/app/data")
TLE_FILE = DATA_DIR / "all-active.tle"

DASHBOARD_REFRESH_SECONDS = 60
TLE_REFRESH_HOURS = int(
    os.getenv("ORBITHUB_REFRESH_HOURS", "6")
)

SOURCE_URLS = [
    {
        "name": "CelesTrak",
        "type": "tle",
        "url": (
            "https://celestrak.org/NORAD/elements/"
            "gp.php?GROUP=ACTIVE&FORMAT=TLE"
        ),
    },
    {
        "name": "CelesTrak WWW",
        "type": "tle",
        "url": (
            "https://www.celestrak.org/NORAD/elements/"
            "gp.php?GROUP=ACTIVE&FORMAT=TLE"
        ),
    },
    {
        "name": "SatNOGS",
        "type": "satnogs_json",
        "url": "https://db.satnogs.org/api/tle/?format=json",
    },
]
