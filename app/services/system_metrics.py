from __future__ import annotations

import os
import shutil
import time
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class SystemMetrics:
    cpu_percent: float | None
    memory_percent: float | None
    temperature_celsius: float | None
    uptime_seconds: int | None
    disk_percent: float | None

    def to_dict(self) -> dict[str, float | int | None]:
        return asdict(self)


def _read_cpu_times() -> tuple[int, int] | None:
    try:
        fields = Path("/proc/stat").read_text(
            encoding="utf-8"
        ).splitlines()[0].split()

        if not fields or fields[0] != "cpu":
            return None

        values = [int(value) for value in fields[1:]]

        idle = values[3]
        if len(values) > 4:
            idle += values[4]

        total = sum(values)
        return idle, total
    except (OSError, ValueError, IndexError):
        return None


def read_cpu_percent(
    sample_seconds: float = 0.15,
) -> float | None:
    first = _read_cpu_times()

    if first is None:
        return None

    time.sleep(sample_seconds)

    second = _read_cpu_times()

    if second is None:
        return None

    idle_delta = second[0] - first[0]
    total_delta = second[1] - first[1]

    if total_delta <= 0:
        return None

    usage = (
        1.0 - idle_delta / total_delta
    ) * 100.0

    return round(
        max(0.0, min(100.0, usage)),
        1,
    )


def read_memory_percent() -> float | None:
    try:
        values: dict[str, int] = {}

        for line in Path("/proc/meminfo").read_text(
            encoding="utf-8"
        ).splitlines():
            key, raw_value = line.split(":", 1)
            values[key] = int(raw_value.split()[0])

        total = values["MemTotal"]
        available = values.get(
            "MemAvailable",
            values.get("MemFree", 0),
        )

        if total <= 0:
            return None

        used_percent = (
            1.0 - available / total
        ) * 100.0

        return round(
            max(0.0, min(100.0, used_percent)),
            1,
        )
    except (
        OSError,
        ValueError,
        KeyError,
        IndexError,
    ):
        return None


def read_temperature_celsius() -> float | None:
    candidates = (
        Path(
            "/sys/class/thermal/"
            "thermal_zone0/temp"
        ),
        Path(
            "/sys/class/hwmon/hwmon0/"
            "temp1_input"
        ),
    )

    for path in candidates:
        try:
            value = float(
                path.read_text(
                    encoding="utf-8"
                ).strip()
            )

            if value > 1000:
                value /= 1000.0

            return round(value, 1)
        except (OSError, ValueError):
            continue

    return None


def read_uptime_seconds() -> int | None:
    try:
        value = Path("/proc/uptime").read_text(
            encoding="utf-8"
        ).split()[0]

        return int(float(value))
    except (
        OSError,
        ValueError,
        IndexError,
    ):
        return None


def read_disk_percent(
    path: str | os.PathLike[str] = "/",
) -> float | None:
    try:
        usage = shutil.disk_usage(path)

        if usage.total <= 0:
            return None

        return round(
            usage.used / usage.total * 100.0,
            1,
        )
    except OSError:
        return None


def collect_system_metrics() -> SystemMetrics:
    return SystemMetrics(
        cpu_percent=read_cpu_percent(),
        memory_percent=read_memory_percent(),
        temperature_celsius=(
            read_temperature_celsius()
        ),
        uptime_seconds=read_uptime_seconds(),
        disk_percent=read_disk_percent(),
    )


def format_uptime(
    seconds: int | None,
) -> str:
    if seconds is None:
        return "Nicht verfügbar"

    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)

    if days:
        return f"{days} T. {hours} Std."

    if hours:
        return f"{hours} Std. {minutes} Min."

    return f"{minutes} Min."
