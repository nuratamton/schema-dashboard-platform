"""Ingestion endpoint.

    POST /ingest          FR-2

All-or-nothing: a single invalid row rejects the batch and nothing is stored
(FR-2.8, DECISION-1). The error response reports every failing row (FR-2.9).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from backend.api.dependencies import RepositoryDep
from backend.core.models import IngestRequest
from backend.core.validation import ingest_rows

router = APIRouter(tags=["ingestion"])


@router.post("/ingest", status_code=201)
def ingest(payload: IngestRequest, repository: RepositoryDep) -> dict[str, Any]:
    """Validate and store a batch of rows (FR-2).

    Pydantic checks the envelope only -- a schema name and a non-empty list of
    objects. Row *contents* are checked by the engine in ``core/validation.py``,
    because a model here would coerce ``"1000"`` into ``1000`` and FR-2.4 would
    never fire (DECISION-6).
    """
    ingested = ingest_rows(payload, repository)
    return {
        "schema": payload.schema_name,
        "ingested": ingested,
        "rowCount": repository.count_rows(payload.schema_name),
    }
