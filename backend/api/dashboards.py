"""Dashboard endpoints.

    POST /dashboard          FR-3
    GET  /dashboard          FR-5.3
    GET  /dashboard/{name}   FR-4
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from backend.api.dependencies import RepositoryDep
from backend.core.dashboards import generate_dashboard, register_dashboard
from backend.core.models import DashboardRequest

router = APIRouter(tags=["dashboards"])


@router.post("/dashboard", status_code=201)
def create_dashboard(
    payload: DashboardRequest, repository: RepositoryDep
) -> dict[str, Any]:
    """Register a dashboard config, fully validated against its schema (FR-3).

    ``by_alias`` so the response says ``schema``, not the attribute name the
    model uses to dodge Pydantic's ``BaseModel.schema`` shadowing. The value is
    the *resolved* binding, so a config posted without one is echoed back with
    the schema it was bound to (DECISION-23).
    """
    return register_dashboard(payload, repository).model_dump(by_alias=True)


@router.get("/dashboard")
def list_dashboards(repository: RepositoryDep) -> list[str]:
    """List registered dashboard names (FR-5.3)."""
    return repository.list_dashboards()


@router.get("/dashboard/{name}")
def read_dashboard(name: str, repository: RepositoryDep) -> dict[str, Any]:
    """Generate a dashboard (FR-4). 404 if there is no such dashboard."""
    return generate_dashboard(name, repository)
