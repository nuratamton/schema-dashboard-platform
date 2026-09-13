"""T10 -- the FastAPI layer. FR-1 to FR-5, NFR-6, NFR-7.

Covers every status code NFR-6 names, and asserts that a malformed envelope
comes back in the same error contract as everything else -- which is the reason
the RequestValidationError handler exists.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.core import types
from backend.store.memory import InMemoryRepository

ERROR_KEYS = {"error", "message", "details"}


@pytest.fixture()
def ready(
    client: TestClient,
    trade_schema: dict[str, Any],
    trade_rows: list[dict[str, Any]],
    trade_dashboard: dict[str, Any],
) -> TestClient:
    """A client with the schema, rows and dashboard already registered."""
    client.post("/schema", json=trade_schema)
    client.post("/ingest", json={"schema": "trade", "rows": trade_rows})
    client.post("/dashboard", json=trade_dashboard)
    return client


# ======================================================================
# 200 -- reads (NFR-6)
# ======================================================================


def test_health_is_200(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200  # NFR-6
    assert response.json() == {"status": "ok"}  # FR-5.4


def test_list_schemas_is_200(ready: TestClient) -> None:
    response = ready.get("/schema")

    assert response.status_code == 200  # NFR-6
    assert response.json() == ["trade"]  # FR-5.1


def test_list_schemas_is_empty_before_anything_is_registered(
    client: TestClient,
) -> None:
    assert client.get("/schema").json() == []  # FR-5.1


def test_read_schema_is_200(ready: TestClient) -> None:
    response = ready.get("/schema/trade")

    assert response.status_code == 200  # NFR-6
    assert response.json()["name"] == "trade"  # FR-5.2
    assert [field["name"] for field in response.json()["fields"]] == [
        "tradeId",
        "amount",
        "status",
    ]


def test_list_dashboards_is_200(ready: TestClient) -> None:
    response = ready.get("/dashboard")

    assert response.status_code == 200  # NFR-6
    assert response.json() == ["trade-dashboard"]  # FR-5.3


def test_generate_dashboard_is_200(ready: TestClient) -> None:
    response = ready.get("/dashboard/trade-dashboard")

    assert response.status_code == 200  # NFR-6
    assert response.json()["rowCount"] == 3  # FR-4


# ======================================================================
# 201 -- creates (NFR-6)
# ======================================================================


def test_create_schema_is_201(client: TestClient, trade_schema: dict[str, Any]) -> None:
    response = client.post("/schema", json=trade_schema)

    assert response.status_code == 201  # FR-1, NFR-6
    assert response.json()["name"] == "trade"


def test_ingest_is_201(
    client: TestClient, trade_schema: dict[str, Any], trade_rows: list[dict[str, Any]]
) -> None:
    client.post("/schema", json=trade_schema)

    response = client.post("/ingest", json={"schema": "trade", "rows": trade_rows})

    assert response.status_code == 201  # FR-2, NFR-6
    assert response.json() == {"schema": "trade", "ingested": 3, "rowCount": 3}


def test_ingest_reports_the_running_total(
    client: TestClient, trade_schema: dict[str, Any], trade_rows: list[dict[str, Any]]
) -> None:
    client.post("/schema", json=trade_schema)
    client.post("/ingest", json={"schema": "trade", "rows": trade_rows})

    response = client.post(
        "/ingest", json={"schema": "trade", "rows": [{"tradeId": "T9", "amount": 1}]}
    )

    assert response.json() == {"schema": "trade", "ingested": 1, "rowCount": 4}


def test_create_dashboard_is_201(
    client: TestClient, trade_schema: dict[str, Any], trade_dashboard: dict[str, Any]
) -> None:
    client.post("/schema", json=trade_schema)

    response = client.post("/dashboard", json=trade_dashboard)

    assert response.status_code == 201  # FR-3, NFR-6


def test_the_dashboard_response_uses_the_schema_key_not_the_attribute_name(
    client: TestClient, trade_schema: dict[str, Any], trade_dashboard: dict[str, Any]
) -> None:
    """The model dodges Pydantic's BaseModel.schema shadowing internally; the
    wire format must not show that."""
    client.post("/schema", json=trade_schema)

    body = client.post("/dashboard", json=trade_dashboard).json()

    assert body["schema"] == "trade"
    assert "schema_name" not in body


# ======================================================================
# 404 -- unknown resources (NFR-6)
# ======================================================================


def test_unknown_schema_read_is_404(client: TestClient) -> None:
    response = client.get("/schema/nope")

    assert response.status_code == 404  # FR-5.2, NFR-6
    assert response.json()["error"] == "UNKNOWN_SCHEMA"


def test_unknown_dashboard_read_is_404(client: TestClient) -> None:
    response = client.get("/dashboard/nope")

    assert response.status_code == 404  # FR-4.1, NFR-6
    assert response.json()["error"] == "UNKNOWN_DASHBOARD"


def test_ingest_against_an_unknown_schema_is_404(client: TestClient) -> None:
    response = client.post(
        "/ingest", json={"schema": "nope", "rows": [{"a": 1}]}
    )

    assert response.status_code == 404  # FR-2.1, NFR-6
    assert response.json()["error"] == "UNKNOWN_SCHEMA"


def test_dashboard_bound_to_an_unknown_schema_is_404(
    client: TestClient, trade_schema: dict[str, Any]
) -> None:
    client.post("/schema", json=trade_schema)

    response = client.post(
        "/dashboard",
        json={"name": "d", "schema": "nope", "views": [{"type": "table", "columns": ["x"]}]},
    )

    assert response.status_code == 404  # FR-3.2, NFR-6


# ======================================================================
# 409 -- duplicates (NFR-6)
# ======================================================================


def test_duplicate_schema_is_409(client: TestClient, trade_schema: dict[str, Any]) -> None:
    client.post("/schema", json=trade_schema)

    response = client.post("/schema", json=trade_schema)

    assert response.status_code == 409  # FR-1.8, NFR-6
    assert response.json()["error"] == "DUPLICATE_NAME"


def test_duplicate_dashboard_is_409(
    client: TestClient, trade_schema: dict[str, Any], trade_dashboard: dict[str, Any]
) -> None:
    client.post("/schema", json=trade_schema)
    client.post("/dashboard", json=trade_dashboard)

    response = client.post("/dashboard", json=trade_dashboard)

    assert response.status_code == 409  # FR-3.1, NFR-6
    assert response.json()["error"] == "DUPLICATE_NAME"


def test_a_rejected_duplicate_does_not_replace_the_original(
    client: TestClient, trade_schema: dict[str, Any]
) -> None:
    client.post("/schema", json=trade_schema)

    client.post(
        "/schema",
        json={"name": "trade", "fields": [{"name": "other", "type": "boolean"}]},
    )

    assert len(client.get("/schema/trade").json()["fields"]) == 3  # FR-1.8


# ======================================================================
# 422 -- validation failures (NFR-6)
# ======================================================================


def test_schema_definition_validation_is_422(client: TestClient) -> None:
    response = client.post(
        "/schema",
        json={"name": "s", "fields": [{"name": "when", "type": "date"}]},
    )

    assert response.status_code == 422  # FR-1.4, NFR-6
    assert response.json()["details"][0]["code"] == "UNKNOWN_TYPE"


def test_row_validation_is_422(
    client: TestClient, trade_schema: dict[str, Any]
) -> None:
    client.post("/schema", json=trade_schema)

    response = client.post(
        "/ingest",
        json={"schema": "trade", "rows": [{"tradeId": "T1", "amount": "1000"}]},
    )

    assert response.status_code == 422  # FR-2.4, NFR-6
    assert response.json()["details"][0] == {
        "row": 0,
        "field": "amount",
        "code": "TYPE_MISMATCH",
        "expected": "number",
        "actual": "string",
    }


def test_config_validation_is_422(
    client: TestClient, trade_schema: dict[str, Any]
) -> None:
    client.post("/schema", json=trade_schema)

    response = client.post(
        "/dashboard",
        json={
            "name": "d",
            "schema": "trade",
            "views": [{"type": "summary", "field": "notional", "aggregation": "sum"}],
        },
    )

    assert response.status_code == 422  # FR-3.6, NFR-6
    assert response.json()["details"][0]["field"] == "views[0].notional"


def test_ambiguous_schema_binding_is_422(
    client: TestClient, trade_schema: dict[str, Any], customer_schema: dict[str, Any]
) -> None:
    client.post("/schema", json=trade_schema)
    client.post("/schema", json=customer_schema)

    response = client.post(
        "/dashboard",
        json={"name": "d", "views": [{"type": "table", "columns": ["tradeId"]}]},
    )

    assert response.status_code == 422  # FR-3.2, NFR-6
    assert response.json()["error"] == "AMBIGUOUS_SCHEMA"


def test_a_dashboard_before_any_schema_is_422_no_schema_registered(
    client: TestClient, trade_dashboard: dict[str, Any]
) -> None:
    """Posting panel 3 before panel 1 -- an easy thing to do in the UI, and a
    different answer from ambiguity (DECISION-33)."""
    payload = {k: v for k, v in trade_dashboard.items() if k != "schema"}

    response = client.post("/dashboard", json=payload)

    assert response.status_code == 422  # FR-3.2, NFR-6
    body = response.json()
    assert body["error"] == "NO_SCHEMA_REGISTERED"
    assert set(body) == ERROR_KEYS  # NFR-5
    assert body["details"] == []


# ======================================================================
# The envelope override -- the reason the handler exists (NFR-5)
# ======================================================================


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/schema", {"name": "s"}),
        ("/schema", {"name": "s", "fields": []}),
        ("/schema", {"fields": [{"name": "a", "type": "string"}]}),
        ("/schema", {"name": "s", "fields": [{"name": "a", "type": "string", "agg": "sum"}]}),
        ("/schema", {"name": "s", "fields": [{"name": "a", "type": "string", "required": 1}]}),
        ("/ingest", {"schema": "trade"}),
        ("/ingest", {"schema": "trade", "rows": []}),
        ("/ingest", {"schema": "trade", "rows": ["not an object"]}),
        ("/dashboard", {"schema": "trade"}),
    ],
)
def test_a_malformed_envelope_returns_the_same_contract(
    client: TestClient, path: str, payload: dict[str, Any]
) -> None:
    """NFR-5: one error contract across every endpoint, FastAPI's default 422
    body included. Without the override these come back as {"detail": [...]}."""
    response = client.post(path, json=payload)

    assert response.status_code == 422  # NFR-6
    body = response.json()
    assert set(body) == ERROR_KEYS  # NFR-5
    assert body["error"] == "VALIDATION_FAILED"
    assert "detail" not in body


def test_a_missing_envelope_key_is_reported_as_a_missing_field(
    client: TestClient,
) -> None:
    body = client.post("/schema", json={"name": "s"}).json()

    assert body["details"] == [
        {"field": "fields", "code": "MISSING_REQUIRED_FIELD"}
    ]  # NFR-5


def test_an_unexpected_envelope_key_is_reported_as_an_unknown_field(
    client: TestClient,
) -> None:
    body = client.post(
        "/schema",
        json={"name": "s", "fields": [{"name": "a", "type": "string", "agg": "sum"}]},
    ).json()

    assert body["details"][0]["code"] == "UNKNOWN_FIELD"  # NFR-5
    assert body["details"][0]["field"] == "fields[0].agg"


def test_envelope_error_locations_use_the_same_path_form_as_config_errors(
    client: TestClient,
) -> None:
    """`fields[0].name` here, `views[0].<field>` in dashboard errors -- one
    reading of `field` works across the whole contract."""
    body = client.post(
        "/schema", json={"name": "s", "fields": [{"type": "string"}]}
    ).json()

    assert body["details"][0]["field"] == "fields[0].name"


def test_every_envelope_problem_is_reported(client: TestClient) -> None:
    body = client.post("/schema", json={"fields": []}).json()

    assert len(body["details"]) == 2  # NFR-5
    assert {issue["field"] for issue in body["details"]} == {"name", "fields"}


# ======================================================================
# The contract, uniformly (NFR-5)
# ======================================================================


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("get", "/schema/nope", None),
        ("get", "/dashboard/nope", None),
        ("post", "/ingest", {"schema": "nope", "rows": [{"a": 1}]}),
        ("post", "/schema", {"name": "s", "fields": [{"name": "a", "type": "date"}]}),
        ("post", "/schema", {"name": "s"}),
    ],
)
def test_every_error_uses_the_one_contract(
    client: TestClient, method: str, path: str, payload: dict[str, Any] | None
) -> None:
    response = getattr(client, method)(path, **({"json": payload} if payload else {}))

    body = response.json()
    assert set(body) == ERROR_KEYS  # NFR-5
    assert isinstance(body["message"], str) and body["message"]
    assert isinstance(body["details"], list)


@pytest.mark.parametrize(
    ("path", "expected"),
    [("/schema/nope", 404), ("/dashboard/nope", 404)],
)
def test_the_status_code_is_not_serialised_as_the_body(
    client: TestClient, path: str, expected: int
) -> None:
    """JSONResponse takes `content` first. Passing the status code positionally
    would return 200 with the number as the body."""
    response = client.get(path)

    assert response.status_code == expected  # NFR-6
    assert isinstance(response.json(), dict)


# ======================================================================
# Wiring (NFR-4, NFR-7)
# ======================================================================


def test_each_test_gets_a_fresh_repository(client: TestClient) -> None:
    """The dependency override is what makes the rest of this file independent."""
    assert client.get("/schema").json() == []
    assert client.get("/dashboard").json() == []


def test_the_injected_repository_is_the_one_the_app_writes_to(
    client: TestClient, repository: InMemoryRepository, trade_schema: dict[str, Any]
) -> None:
    client.post("/schema", json=trade_schema)

    assert repository.list_schemas() == ["trade"]  # NFR-4


def test_the_openapi_schema_documents_the_live_registries() -> None:
    """DECISION-27: /docs lists the registered names without any module naming
    them, so a type registered at runtime shows up too."""
    from backend.main import app

    def field_schema() -> dict[str, Any]:
        app.openapi_schema = None  # force regeneration
        return app.openapi()["components"]["schemas"]["FieldDefinition"]["properties"]

    assert field_schema()["type"]["enum"] == types.supported_types()

    snapshot = dict(types._REGISTRY)
    try:

        @types.register("date")
        def _is_date(value: Any) -> bool:
            return isinstance(value, str)

        assert "date" in field_schema()["type"]["enum"]  # NFR-3
    finally:
        types._REGISTRY.clear()
        types._REGISTRY.update(snapshot)
        app.openapi_schema = None


def test_an_optional_aggregation_may_still_be_null() -> None:
    """The enum is injected into the string branch, not the union, so omitting
    an aggregation stays legal."""
    from backend.main import app

    app.openapi_schema = None
    aggregation = app.openapi()["components"]["schemas"]["FieldDefinition"][
        "properties"
    ]["aggregation"]

    assert {branch.get("type") for branch in aggregation["anyOf"]} == {"string", "null"}


# ======================================================================
# Nothing escapes the error contract (NFR-5, DECISION-36)
# ======================================================================


def test_an_unexpected_error_still_uses_the_error_contract(
    repository: InMemoryRepository,
) -> None:
    """NFR-5 claims one contract across every endpoint. Without a last-resort
    handler an unhandled exception returns `text/plain` "Internal Server Error",
    which makes that claim false.

    The trigger here is the known edge that exposed it: `avg` over an integer too
    large to convert to a float raises OverflowError (DECISION-36).
    """
    from backend.api.dependencies import get_repository
    from backend.main import app

    app.dependency_overrides[get_repository] = lambda: repository
    try:
        client = TestClient(app, raise_server_exceptions=False)
        client.post(
            "/schema",
            json={"name": "s", "fields": [
                {"name": "a", "type": "number", "required": True, "aggregation": "avg"}
            ]},
        )
        client.post(
            "/ingest",
            content='{"schema":"s","rows":[{"a":%d}]}' % (10**400),
            headers={"Content-Type": "application/json"},
        )
        client.post(
            "/dashboard",
            json={"name": "d", "schema": "s",
                  "views": [{"type": "summary", "field": "a"}]},
        )

        response = client.get("/dashboard/d")

        assert response.status_code == 500  # NFR-6
        assert response.headers["content-type"].startswith("application/json")
        body = response.json()
        assert set(body) == ERROR_KEYS  # NFR-5
        assert body["details"] == []
        assert isinstance(body["message"], str) and body["message"]
    finally:
        app.dependency_overrides.clear()


def test_a_typed_error_is_not_swallowed_by_the_last_resort_handler(
    client: TestClient,
) -> None:
    """The generic handler must sit below the typed one, not replace it."""
    response = client.get("/schema/nope")

    assert response.status_code == 404  # NFR-6
    assert response.json()["error"] == "UNKNOWN_SCHEMA"


# ======================================================================
# `expected` names a type, never prose (NFR-5, DECISION-37)
# ======================================================================


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/schema", {"name": "s"}),
        ("/schema", {"name": "s", "fields": [{"type": "string"}]}),
        ("/schema", {"name": "s", "fields": [{"name": "a", "type": "string", "required": 1}]}),
        ("/schema", {"name": "s", "fields": []}),
        ("/ingest", {"schema": "t", "rows": ["nope"]}),
    ],
)
def test_envelope_errors_never_put_prose_in_expected(
    client: TestClient, path: str, payload: dict[str, Any]
) -> None:
    """errors.py documents expected/actual as naming types, and every
    domain-path error honours that. The envelope path must not differ."""
    for issue in client.post(path, json=payload).json()["details"]:
        assert "expected" not in issue or " " not in issue["expected"]  # NFR-5


def test_domain_errors_still_carry_a_type_in_expected(
    client: TestClient, trade_schema: dict[str, Any]
) -> None:
    """The other half: dropping prose must not drop the useful values."""
    client.post("/schema", json=trade_schema)
    body = client.post(
        "/ingest", json={"schema": "trade", "rows": [{"tradeId": "T1", "amount": "x"}]}
    ).json()

    assert body["details"][0]["expected"] == "number"  # NFR-5
