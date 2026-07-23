from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.config import CUSTOM_SOURCES_FILE
from app.services.tle_sources import (
    load_custom_sources,
    save_custom_sources,
)


class SourceManager:
    """Central manager for built-in and custom TLE sources."""

    def __init__(
        self,
        builtin_sources: list[dict[str, Any]],
    ) -> None:
        self._builtin_sources = deepcopy(builtin_sources)

    def get_builtin_sources(
        self,
    ) -> list[dict[str, Any]]:
        """Return all built-in sources."""
        return deepcopy(self._builtin_sources)

    def get_custom_sources(
        self,
    ) -> list[dict[str, Any]]:
        """Return all custom sources stored on disk."""
        return load_custom_sources(CUSTOM_SOURCES_FILE)

    def get_all_sources(
        self,
    ) -> list[dict[str, Any]]:
        """Return built-in and custom sources as one list."""
        return [
            *self.get_builtin_sources(),
            *self.get_custom_sources(),
        ]

    def get_source(
        self,
        source_id: str,
    ) -> dict[str, Any] | None:
        """Return a source by ID or None if it does not exist."""
        for source in self.get_all_sources():
            if source.get("id") == source_id:
                return source

        return None

    def source_exists(
        self,
        source_id: str,
    ) -> bool:
        """Check whether a source exists."""
        return self.get_source(source_id) is not None

    def is_builtin_source(
        self,
        source_id: str,
    ) -> bool:
        """Check whether a source is built in."""
        return any(
            source.get("id") == source_id
            for source in self._builtin_sources
        )

    def add_custom_source(
        self,
        source_data: dict[str, Any],
    ) -> None:
        """Add and persist a custom source."""
        source_id = str(source_data.get("id", "")).strip()

        if not source_id:
            raise ValueError("Source ID is required.")

        if self.source_exists(source_id):
            raise ValueError("Source ID already exists.")

        custom_sources = self.get_custom_sources()
        custom_sources.append(deepcopy(source_data))

        save_custom_sources(
            CUSTOM_SOURCES_FILE,
            custom_sources,
        )

    def update_custom_source(
        self,
        source_id: str,
        source_data: dict[str, Any],
    ) -> None:
        """Update an existing custom source."""
        if self.is_builtin_source(source_id):
            raise ValueError(
                "Built-in sources cannot be modified."
            )

        custom_sources = self.get_custom_sources()

        for index, source in enumerate(custom_sources):
            if source.get("id") != source_id:
                continue

            updated_source = deepcopy(source_data)
            updated_source["id"] = source_id
            custom_sources[index] = updated_source

            save_custom_sources(
                CUSTOM_SOURCES_FILE,
                custom_sources,
            )
            return

        raise KeyError("Custom source not found.")

    def delete_custom_source(
        self,
        source_id: str,
    ) -> None:
        """Delete an existing custom source."""
        if self.is_builtin_source(source_id):
            raise ValueError(
                "Built-in sources cannot be deleted."
            )

        custom_sources = self.get_custom_sources()

        filtered_sources = [
            source
            for source in custom_sources
            if source.get("id") != source_id
        ]

        if len(filtered_sources) == len(custom_sources):
            raise KeyError("Custom source not found.")

        save_custom_sources(
            CUSTOM_SOURCES_FILE,
            filtered_sources,
        )
