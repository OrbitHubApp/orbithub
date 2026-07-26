from fastapi import APIRouter

from app.services.stats_store import read_system_metrics, read_tle_update_events

router = APIRouter(
    prefix="/api/stats",
    tags=["Statistik"],
)


@router.get("/system")
def get_system_stats(hours: int = 24) -> dict:
    samples = read_system_metrics(hours=hours)
    return {
        "hours": hours,
        "samples": samples,
    }


@router.get("/tle-updates")
def get_tle_update_stats(days: int = 7) -> dict:
    events = read_tle_update_events(days=days)
    total = len(events)
    successful = sum(1 for event in events if event.get("ok"))
    success_rate = round(successful / total * 100, 1) if total else None

    sources: dict[str, dict] = {}
    for event in events:
        source = event.get("source") or "Unbekannt"
        bucket = sources.setdefault(
            source,
            {"total": 0, "successful": 0},
        )
        bucket["total"] += 1
        if event.get("ok"):
            bucket["successful"] += 1

    per_source = [
        {
            "source": source,
            "total": bucket["total"],
            "successful": bucket["successful"],
            "success_rate": round(
                bucket["successful"] / bucket["total"] * 100, 1
            ),
        }
        for source, bucket in sources.items()
    ]

    return {
        "days": days,
        "events": events,
        "total": total,
        "successful": successful,
        "success_rate": success_rate,
        "per_source": per_source,
    }
