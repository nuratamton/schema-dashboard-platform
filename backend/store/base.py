"""Repository interface.

Requirements: NFR-4 (storage behind an interface), FR-1.9 (schemas held in
memory), FR-2.10 (rows appended in order), FR-3.11 (dashboard configs held in
memory).

Defines the storage contract so that swapping the in-memory implementation for a
database touches this package only.

Three properties of this port are deliberate and worth stating, because each one
is a place where logic could have leaked downwards:

* **It knows nothing about what it stores.** ``store`` imports nothing from
  ``core`` or ``api`` (NFR-7), so it cannot name the shape of a schema or a
  dashboard config. They are opaque values keyed by name.
* **It owns no error vocabulary.** Lookups return ``None`` for an absent key
  rather than raising. Duplicate-name rejection (FR-1.8, FR-3.1) and unknown-name
  rejection (FR-2.1, FR-3.2, FR-4.1) are the caller's decisions, because only the
  caller knows whether the answer is 404 or 409.
* **It is domain-free.** No method, name, or constant here refers to any use case
  (RULE-0). ``Row`` is a JSON object; the store never looks inside one.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any

__all__ = ["Repository", "Row", "StoredDashboard", "StoredSchema"]


Row = dict[str, Any]
"""One ingested record. A JSON object whose contents the store never inspects.

Row *contents* are validated by ``core`` before they ever reach the store
(FR-2.3-FR-2.5); by the time a row is saved, its values are scalars of the
registered field types.
"""

StoredSchema = Any
"""A validated schema definition. Opaque to the store; ``core`` owns its shape."""

StoredDashboard = Any
"""A validated dashboard config. Opaque to the store; ``core`` owns its shape."""


class Repository(ABC):
    """Storage contract for schemas, dashboard configs, and row datasets.

    Two uniform name-keyed collections (schemas, dashboards), each with
    ``save`` / ``get`` / ``has`` / ``list``, plus one append-only dataset per
    schema.

    Implementations must not hand out references to their own internal state:
    a caller mutating a returned value must not be able to change what is
    stored (FR-4.9).
    """

    # ------------------------------------------------------------------
    # Schemas (FR-1.9)
    # ------------------------------------------------------------------

    @abstractmethod
    def save_schema(self, name: str, schema: StoredSchema) -> None:
        """Store ``schema`` under ``name``, replacing any existing entry.

        The store does not reject duplicates. FR-1.8 requires a ``409``, which is
        a decision about HTTP semantics that the caller makes after consulting
        :meth:`has_schema`.
        """

    @abstractmethod
    def get_schema(self, name: str) -> StoredSchema | None:
        """Return the schema stored under ``name``, or ``None`` if absent."""

    @abstractmethod
    def has_schema(self, name: str) -> bool:
        """Return whether a schema is registered under ``name``."""

    @abstractmethod
    def list_schemas(self) -> list[str]:
        """Return every registered schema name, in registration order (FR-5.1)."""

    # ------------------------------------------------------------------
    # Dashboard configs (FR-3.11)
    # ------------------------------------------------------------------

    @abstractmethod
    def save_dashboard(self, name: str, dashboard: StoredDashboard) -> None:
        """Store ``dashboard`` under ``name``, replacing any existing entry.

        As with :meth:`save_schema`, rejecting duplicates (FR-3.1) is the
        caller's job.
        """

    @abstractmethod
    def get_dashboard(self, name: str) -> StoredDashboard | None:
        """Return the dashboard config stored under ``name``, or ``None``."""

    @abstractmethod
    def has_dashboard(self, name: str) -> bool:
        """Return whether a dashboard config is registered under ``name``."""

    @abstractmethod
    def list_dashboards(self) -> list[str]:
        """Return every registered dashboard name, in registration order (FR-5.3)."""

    # ------------------------------------------------------------------
    # Row datasets (FR-2.10)
    # ------------------------------------------------------------------

    @abstractmethod
    def append_rows(self, schema_name: str, rows: Sequence[Row]) -> None:
        """Append ``rows`` to ``schema_name``'s dataset, preserving order (FR-2.10).

        Callers reach this only once a batch has validated in full: ingestion is
        all-or-nothing (FR-2.8), so a partially valid batch never arrives here.
        """

    @abstractmethod
    def get_rows(self, schema_name: str) -> list[Row]:
        """Return ``schema_name``'s dataset in ingestion order.

        An empty list is returned for a schema with no ingested rows *and* for an
        unknown schema name. The distinction is not the store's to draw: a caller
        that needs to 404 on an unknown schema asks :meth:`has_schema` first.
        """

    @abstractmethod
    def count_rows(self, schema_name: str) -> int:
        """Return the number of rows stored for ``schema_name``.

        Serves ``rowCount`` in the FR-4 dashboard response without materialising
        a defensive copy of the whole dataset.
        """
