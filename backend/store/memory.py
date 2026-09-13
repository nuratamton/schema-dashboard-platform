"""In-memory repository implementation.

Requirements: NFR-4, FR-1.9, FR-2.10, FR-3.11.

The only implementation of the store/base.py contract. Dict-backed. No
persistence — the brief explicitly excludes databases.

Ordering (FR-2.10, FR-5.1, FR-5.3) comes free: ``dict`` preserves insertion
order and ``list`` preserves append order.
"""

from __future__ import annotations

from collections.abc import Sequence

from backend.store.base import Repository, Row, StoredDashboard, StoredSchema

__all__ = ["InMemoryRepository"]


class InMemoryRepository(Repository):
    """Dict-backed :class:`Repository`. State lives for the process lifetime only.

    Rows are copied on the way in and on the way out. That keeps FR-4.9
    ("generation never mutates stored data") a property of the store rather than
    a rule every caller has to remember. A shallow ``dict`` copy is sufficient:
    validated row values are scalars of the registered field types, so there is
    no nested structure to share (FR-2.4).

    Schemas and dashboard configs are stored by reference. Copying them would
    require knowing their shape, which is exactly what this layer is forbidden
    to know; ``core`` treats them as immutable once validated.
    """

    def __init__(self) -> None:
        self._schemas: dict[str, StoredSchema] = {}
        self._dashboards: dict[str, StoredDashboard] = {}
        self._rows: dict[str, list[Row]] = {}

    # ------------------------------------------------------------------
    # Schemas (FR-1.9)
    # ------------------------------------------------------------------

    def save_schema(self, name: str, schema: StoredSchema) -> None:
        self._schemas[name] = schema

    def get_schema(self, name: str) -> StoredSchema | None:
        return self._schemas.get(name)

    def has_schema(self, name: str) -> bool:
        return name in self._schemas

    def list_schemas(self) -> list[str]:
        return list(self._schemas)

    # ------------------------------------------------------------------
    # Dashboard configs (FR-3.11)
    # ------------------------------------------------------------------

    def save_dashboard(self, name: str, dashboard: StoredDashboard) -> None:
        self._dashboards[name] = dashboard

    def get_dashboard(self, name: str) -> StoredDashboard | None:
        return self._dashboards.get(name)

    def has_dashboard(self, name: str) -> bool:
        return name in self._dashboards

    def list_dashboards(self) -> list[str]:
        return list(self._dashboards)

    # ------------------------------------------------------------------
    # Row datasets (FR-2.10)
    # ------------------------------------------------------------------

    def append_rows(self, schema_name: str, rows: Sequence[Row]) -> None:
        dataset = self._rows.setdefault(schema_name, [])
        dataset.extend(dict(row) for row in rows)

    def get_rows(self, schema_name: str) -> list[Row]:
        return [dict(row) for row in self._rows.get(schema_name, ())]

    def count_rows(self, schema_name: str) -> int:
        return len(self._rows.get(schema_name, ()))
