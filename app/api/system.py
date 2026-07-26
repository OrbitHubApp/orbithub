from fastapi import APIRouter

from app.services.system_metrics import (
    collect_system_metrics,
    format_uptime,
)

router = APIRouter(
    prefix="/api/system",
    tags=["System"],
)


@router.get("")
def get_system_metrics() -> dict:
    metrics = collect_system_metrics()
    data = metrics.to_dict()
    data["uptime_text"] = format_uptime(
        metrics.uptime_seconds
    )
    return data
