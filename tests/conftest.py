"""Shared pytest fixtures.

Keep domain fixtures HERE, never in backend/ (RULE-0). `trade` and `customer`
are test data; the platform has never heard of either.

The `client` fixture overrides the repository provider rather than reaching into
the app's state, which is the whole reason the provider exists: every test gets
an empty store and no test can be affected by what another one registered.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.api.dependencies import get_repository
from backend.main import app
from backend.store.memory import InMemoryRepository


@pytest.fixture()
def repository() -> InMemoryRepository:
    """A fresh, empty store. Injected into the app by the `client` fixture."""
    return InMemoryRepository()


@pytest.fixture()
def client(repository: InMemoryRepository) -> Iterator[TestClient]:
    """A TestClient whose app reads and writes `repository`."""
    app.dependency_overrides[get_repository] = lambda: repository
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


# ----------------------------------------------------------------------
# Use case one -- the brief's example
# ----------------------------------------------------------------------


@pytest.fixture()
def trade_schema() -> dict[str, Any]:
    return {
        "name": "trade",
        "fields": [
            {"name": "tradeId", "type": "string", "required": True},
            {
                "name": "amount",
                "type": "number",
                "required": True,
                "aggregation": "sum",
            },
            {"name": "status", "type": "string"},
        ],
    }


@pytest.fixture()
def trade_rows() -> list[dict[str, Any]]:
    return [
        {"tradeId": "T001", "amount": 10000, "status": "OPEN"},
        {"tradeId": "T002", "amount": 5000, "status": "CLOSED"},
        {"tradeId": "T003", "amount": 10000, "status": "OPEN"},
    ]


@pytest.fixture()
def trade_dashboard() -> dict[str, Any]:
    return {
        "name": "trade-dashboard",
        "schema": "trade",
        "views": [
            {"type": "summary", "field": "amount", "aggregation": "sum"},
            {"type": "table", "columns": ["tradeId", "amount", "status"]},
        ],
    }


# ----------------------------------------------------------------------
# Use case two -- entirely unrelated, for tests/test_genericity.py
# ----------------------------------------------------------------------


@pytest.fixture()
def customer_schema() -> dict[str, Any]:
    return {
        "name": "customer",
        "fields": [
            {"name": "customerId", "type": "string", "required": True},
            {"name": "name", "type": "string", "required": True},
            {"name": "country", "type": "string"},
        ],
    }


@pytest.fixture()
def customer_rows() -> list[dict[str, Any]]:
    return [
        {"customerId": "C001", "name": "Acme", "country": "UK"},
        {"customerId": "C002", "name": "Globex", "country": "US"},
        {"customerId": "C003", "name": "Initech"},
    ]


@pytest.fixture()
def customer_dashboard() -> dict[str, Any]:
    return {
        "name": "customer-dashboard",
        "schema": "customer",
        "views": [
            {"type": "summary", "field": "customerId", "aggregation": "count"},
            {"type": "table", "columns": ["customerId", "name", "country"]},
        ],
    }
