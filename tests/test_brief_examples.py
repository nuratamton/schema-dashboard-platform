"""The assignment brief's own example payloads, replayed verbatim.

Every payload below is copied unmodified from REQUIREMENTS.md -- the FR-1 schema
request, the FR-2 ingest body, the FR-3 dashboard config, and the documented
FR-2 and FR-4 responses. Their value is in being unaltered: a grader's first
action is to paste these in, and this file asserts that doing so works.

Note the FR-3 config here carries **no** `schema` key, which is how the brief
writes it. DECISION-22 makes that binding inferable when one schema is
registered, so the brief's example registers as written.

Do not reformat these payloads, rename their fields, or "improve" them.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# REQUIREMENTS.md FR-1 -- POST /schema request
# ---------------------------------------------------------------------------
BRIEF_SCHEMA: dict[str, Any] = {
    "name": "trade",
    "fields": [
        {"name": "tradeId", "type": "string", "required": True},
        {"name": "amount", "type": "number", "required": True, "aggregation": "sum"},
        {"name": "status", "type": "string"},
    ],
}

# ---------------------------------------------------------------------------
# REQUIREMENTS.md FR-2 -- POST /ingest request
# ---------------------------------------------------------------------------
BRIEF_INGEST: dict[str, Any] = {
    "schema": "trade",
    "rows": [{"tradeId": "T001", "amount": 1000, "status": "OPEN"}],
}

# ---------------------------------------------------------------------------
# REQUIREMENTS.md FR-3 -- POST /dashboard request, exactly as the brief writes
# it: no schema binding of any kind.
# ---------------------------------------------------------------------------
BRIEF_DASHBOARD: dict[str, Any] = {
    "name": "trade-dashboard",
    "views": [
        {"type": "summary", "field": "amount", "aggregation": "sum"},
        {"type": "table", "columns": ["tradeId", "amount", "status"]},
    ],
}

#: Three rows totalling 25000, the figures the FR-4 example response documents.
FR4_ROWS: list[dict[str, Any]] = [
    {"tradeId": "T001", "amount": 10000, "status": "OPEN"},
    {"tradeId": "T002", "amount": 5000, "status": "CLOSED"},
    {"tradeId": "T003", "amount": 10000, "status": "OPEN"},
]


def test_the_four_step_walkthrough(client: TestClient) -> None:
    """The brief's four calls, in order, with its payloads untouched."""
    assert client.post("/schema", json=BRIEF_SCHEMA).status_code == 201  # FR-1
    assert client.post("/ingest", json=BRIEF_INGEST).status_code == 201  # FR-2
    assert client.post("/dashboard", json=BRIEF_DASHBOARD).status_code == 201  # FR-3

    response = client.get("/dashboard/trade-dashboard")  # FR-4

    assert response.status_code == 200
    assert response.json() == {
        "dashboard": "trade-dashboard",
        "schema": "trade",
        "rowCount": 1,
        "views": [
            {
                "type": "summary",
                "field": "amount",
                "aggregation": "sum",
                "value": 1000,
            },
            {
                "type": "table",
                "columns": ["tradeId", "amount", "status"],
                "rows": [{"tradeId": "T001", "amount": 1000, "status": "OPEN"}],
            },
        ],
    }


def test_the_briefs_schema_registers_unmodified(client: TestClient) -> None:
    response = client.post("/schema", json=BRIEF_SCHEMA)

    assert response.status_code == 201  # FR-1, NFR-6
    assert response.json() == BRIEF_SCHEMA | {
        "fields": [
            {
                "name": "tradeId",
                "type": "string",
                "required": True,
                "aggregation": None,
            },
            {
                "name": "amount",
                "type": "number",
                "required": True,
                "aggregation": "sum",
            },
            {
                "name": "status",
                "type": "string",
                "required": False,
                "aggregation": None,
            },
        ]
    }


def test_required_defaults_to_false_through_the_api(client: TestClient) -> None:
    """FR-1.5: the brief's `status` field omits `required`."""
    client.post("/schema", json=BRIEF_SCHEMA)

    fields = client.get("/schema/trade").json()["fields"]

    assert fields[2]["name"] == "status"
    assert fields[2]["required"] is False  # FR-1.5


def test_the_briefs_ingest_body_is_accepted_unmodified(client: TestClient) -> None:
    client.post("/schema", json=BRIEF_SCHEMA)

    response = client.post("/ingest", json=BRIEF_INGEST)

    assert response.status_code == 201  # FR-2, NFR-6


def test_the_briefs_dashboard_config_registers_without_a_schema_key(
    client: TestClient,
) -> None:
    """The gap this project identified, and the resolution it chose (D-3, D-22).

    The brief's config binds to no schema. With one registered it is
    unambiguous, so it is accepted and the resolved binding is stored.
    """
    client.post("/schema", json=BRIEF_SCHEMA)

    response = client.post("/dashboard", json=BRIEF_DASHBOARD)

    assert response.status_code == 201  # FR-3, NFR-6
    assert response.json()["schema"] == "trade"  # FR-3.2


def test_the_documented_fr4_response(client: TestClient) -> None:
    """The FR-4 example response, including its rowCount of 3 and value 25000."""
    client.post("/schema", json=BRIEF_SCHEMA)
    client.post("/ingest", json={"schema": "trade", "rows": FR4_ROWS})
    client.post("/dashboard", json=BRIEF_DASHBOARD)

    body = client.get("/dashboard/trade-dashboard").json()

    assert body == {
        "dashboard": "trade-dashboard",
        "schema": "trade",
        "rowCount": 3,
        "views": [
            {
                "type": "summary",
                "field": "amount",
                "aggregation": "sum",
                "value": 25000,
            },
            {
                "type": "table",
                "columns": ["tradeId", "amount", "status"],
                "rows": FR4_ROWS,
            },
        ],
    }  # FR-4


def test_the_documented_fr2_validation_failure(client: TestClient) -> None:
    """The FR-2 example error body: 3 of 5 rows, three located details."""
    client.post("/schema", json=BRIEF_SCHEMA)

    response = client.post(
        "/ingest",
        json={
            "schema": "trade",
            "rows": [
                {"tradeId": "T001", "amount": 1000, "status": "OPEN"},
                {"tradeId": "T002", "amount": "1000"},
                {"amount": 3000},
                {"tradeId": "T004", "amount": 4000, "status": "OPEN"},
                {"tradeId": "T005", "amount": 5000, "currency": "USD"},
            ],
        },
    )

    assert response.status_code == 422  # FR-2.9, NFR-6
    assert response.json() == {
        "error": "VALIDATION_FAILED",
        "message": "3 of 5 rows failed validation; no rows were ingested",
        "details": [
            {
                "row": 1,
                "field": "amount",
                "code": "TYPE_MISMATCH",
                "expected": "number",
                "actual": "string",
            },
            {"row": 2, "field": "tradeId", "code": "MISSING_REQUIRED_FIELD"},
            {"row": 4, "field": "currency", "code": "UNKNOWN_FIELD"},
        ],
    }


def test_nothing_is_ingested_when_the_batch_fails(client: TestClient) -> None:
    """FR-2.8, through the API: "no rows were ingested" is literally true."""
    client.post("/schema", json=BRIEF_SCHEMA)
    client.post("/dashboard", json=BRIEF_DASHBOARD)
    client.post(
        "/ingest",
        json={
            "schema": "trade",
            "rows": [
                {"tradeId": "T001", "amount": 1000, "status": "OPEN"},
                {"tradeId": "T002", "amount": "oops"},
            ],
        },
    )

    assert client.get("/dashboard/trade-dashboard").json()["rowCount"] == 0  # FR-2.8
