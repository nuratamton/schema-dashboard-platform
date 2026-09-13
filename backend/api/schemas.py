"""Schema endpoints.

    POST /schema          FR-1
    GET  /schema          FR-5.1
    GET  /schema/{name}   FR-5.2

Parse, delegate to core, format. No logic here.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from backend.api.dependencies import RepositoryDep
from backend.core.errors import UnknownSchema
from backend.core.models import SchemaRequest
from backend.core.validation import register_schema

router = APIRouter(tags=["schemas"])


@router.post("/schema", status_code=201)
def create_schema(payload: SchemaRequest, repository: RepositoryDep) -> dict[str, Any]:
    """Register a schema (FR-1).

    Every rejection -- 409 for a taken name, 422 for an inconsistent definition
    -- is raised by core and formatted by the handlers in ``main.py``.
    """
    return register_schema(payload, repository).model_dump()


@router.get("/schema")
def list_schemas(repository: RepositoryDep) -> list[str]:
    """List registered schema names (FR-5.1)."""
    return repository.list_schemas()


@router.get("/schema/{name}")
def read_schema(name: str, repository: RepositoryDep) -> dict[str, Any]:
    """Return one schema, or 404 (FR-5.2).

    The store reports absence and says nothing about what it means (DECISION-7);
    turning that into a 404 is this layer's decision to make.
    """
    schema: SchemaRequest | None = repository.get_schema(name)
    if schema is None:
        raise UnknownSchema(name)
    return schema.model_dump()
