"""T11 -- THE acceptance test. RULE-0, REQUIREMENTS.md section 6.

Runs the trade use case and an entirely different customer use case end to end
in one app instance, concurrently, asserting both dashboards are correct.

Also greps backend/ for domain terms and asserts zero hits.

If this passes, the assignment is solved.

The assertion that decides it is not that `customer` works -- a hard-coded
single-use-case implementation would pass every other file in this suite. It is
that both work *at the same time*, in the same process, against the same code,
with the second one having required no change to `backend/` at all.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

BACKEND = Path(__file__).resolve().parent.parent / "backend"


def source_files() -> list[Path]:
    """Every hand-written module under backend/. Compiled artefacts excluded."""
    return sorted(
        path
        for path in BACKEND.rglob("*.py")
        if "__pycache__" not in path.parts
    )


def relative(path: Path) -> str:
    return str(path.relative_to(BACKEND.parent))


# ======================================================================
# Section 6 -- two unrelated use cases, one platform, at once
# ======================================================================


@pytest.fixture()
def both(
    client: TestClient,
    trade_schema: dict[str, Any],
    trade_rows: list[dict[str, Any]],
    trade_dashboard: dict[str, Any],
    customer_schema: dict[str, Any],
    customer_rows: list[dict[str, Any]],
    customer_dashboard: dict[str, Any],
) -> TestClient:
    """Both use cases registered in one app instance, through the API only."""
    for schema, rows, dashboard in (
        (trade_schema, trade_rows, trade_dashboard),
        (customer_schema, customer_rows, customer_dashboard),
    ):
        assert client.post("/schema", json=schema).status_code == 201
        assert (
            client.post(
                "/ingest", json={"schema": schema["name"], "rows": rows}
            ).status_code
            == 201
        )
        assert client.post("/dashboard", json=dashboard).status_code == 201
    return client


def test_the_second_use_case_works_end_to_end(
    client: TestClient,
    customer_schema: dict[str, Any],
    customer_rows: list[dict[str, Any]],
    customer_dashboard: dict[str, Any],
) -> None:
    """REQUIREMENTS.md section 6, step by step, with zero lines of backend/
    changed since the trade use case worked."""
    assert client.post("/schema", json=customer_schema).status_code == 201  # FR-1
    assert (
        client.post(
            "/ingest", json={"schema": "customer", "rows": customer_rows}
        ).status_code
        == 201
    )  # FR-2
    assert client.post("/dashboard", json=customer_dashboard).status_code == 201  # FR-3

    response = client.get("/dashboard/customer-dashboard")  # FR-4

    assert response.status_code == 200
    assert response.json() == {
        "dashboard": "customer-dashboard",
        "schema": "customer",
        "rowCount": 3,
        "views": [
            {
                "type": "summary",
                "field": "customerId",
                "aggregation": "count",
                "value": 3,
            },
            {
                "type": "table",
                "columns": ["customerId", "name", "country"],
                "rows": [
                    {"customerId": "C001", "name": "Acme", "country": "UK"},
                    {"customerId": "C002", "name": "Globex", "country": "US"},
                    # FR-4.7: the third row omits `country`, projected as null.
                    {"customerId": "C003", "name": "Initech", "country": None},
                ],
            },
        ],
    }


def test_both_dashboards_are_correct_at_the_same_time(both: TestClient) -> None:
    """The assertion the assignment turns on.

    A single-use-case implementation passes every other test in this suite. It
    cannot pass this one: two schemas, two datasets, two configs, two answers,
    all live in one process simultaneously.
    """
    trade = both.get("/dashboard/trade-dashboard").json()
    customer = both.get("/dashboard/customer-dashboard").json()

    assert trade["schema"] == "trade"
    assert trade["rowCount"] == 3
    assert trade["views"][0]["value"] == 25000  # FR-4.5
    assert trade["views"][1]["columns"] == ["tradeId", "amount", "status"]

    assert customer["schema"] == "customer"
    assert customer["rowCount"] == 3
    assert customer["views"][0]["value"] == 3  # FR-4.5
    assert customer["views"][1]["columns"] == ["customerId", "name", "country"]

    assert trade["views"][1]["rows"] != customer["views"][1]["rows"]


def test_both_are_introspectable_at_once(both: TestClient) -> None:
    assert both.get("/schema").json() == ["trade", "customer"]  # FR-5.1
    assert both.get("/dashboard").json() == [
        "trade-dashboard",
        "customer-dashboard",
    ]  # FR-5.3


def test_registering_the_second_use_case_does_not_disturb_the_first(
    client: TestClient,
    trade_schema: dict[str, Any],
    trade_rows: list[dict[str, Any]],
    trade_dashboard: dict[str, Any],
    customer_schema: dict[str, Any],
    customer_rows: list[dict[str, Any]],
    customer_dashboard: dict[str, Any],
) -> None:
    """Adding a use case is additive. The first dashboard's output is byte-for-byte
    what it was before the second existed."""
    client.post("/schema", json=trade_schema)
    client.post("/ingest", json={"schema": "trade", "rows": trade_rows})
    client.post("/dashboard", json=trade_dashboard)

    before = client.get("/dashboard/trade-dashboard").json()

    client.post("/schema", json=customer_schema)
    client.post("/ingest", json={"schema": "customer", "rows": customer_rows})
    client.post("/dashboard", json=customer_dashboard)

    assert client.get("/dashboard/trade-dashboard").json() == before  # FR-4.2


def test_each_use_case_validates_by_its_own_rules(both: TestClient) -> None:
    """The same engine enforces two different schemas. A row valid for one is
    rejected for the other, and the platform holds no opinion about either."""
    rejected = both.post(
        "/ingest", json={"schema": "customer", "rows": [{"tradeId": "T9", "amount": 1}]}
    )

    assert rejected.status_code == 422  # FR-2.5
    codes = {issue["code"] for issue in rejected.json()["details"]}
    assert codes == {"MISSING_REQUIRED_FIELD", "UNKNOWN_FIELD"}


def test_ingesting_into_one_use_case_leaves_the_other_untouched(
    both: TestClient,
) -> None:
    both.post(
        "/ingest",
        json={"schema": "customer", "rows": [{"customerId": "C004", "name": "Umbrella"}]},
    )

    assert both.get("/dashboard/customer-dashboard").json()["rowCount"] == 4  # FR-2.10
    assert both.get("/dashboard/trade-dashboard").json()["rowCount"] == 3


def test_a_third_use_case_needs_no_code_either(client: TestClient) -> None:
    """Nothing about the two fixtures is special. A schema invented here, in the
    test, with field names the codebase has never seen, works the same way."""
    client.post(
        "/schema",
        json={
            "name": "sensor",
            "fields": [
                {"name": "deviceId", "type": "string", "required": True},
                {"name": "reading", "type": "number", "required": True, "aggregation": "avg"},
                {"name": "faulty", "type": "boolean"},
            ],
        },
    )
    client.post(
        "/ingest",
        json={
            "schema": "sensor",
            "rows": [
                {"deviceId": "D1", "reading": 10, "faulty": False},
                {"deviceId": "D2", "reading": 20},
            ],
        },
    )
    client.post(
        "/dashboard",
        json={
            "name": "sensor-dashboard",
            "schema": "sensor",
            "views": [
                {"type": "summary", "field": "reading"},
                {"type": "summary", "field": "faulty", "aggregation": "count"},
                {"type": "table", "columns": ["deviceId", "faulty"]},
            ],
        },
    )

    body = client.get("/dashboard/sensor-dashboard").json()

    assert body["views"][0] == {
        "type": "summary",
        "field": "reading",
        "aggregation": "avg",  # FR-3.7: taken from the schema's field default
        "value": 15,
    }
    assert body["views"][1]["value"] == 1  # FR-4.5: COUNT(column), one row has it
    assert body["views"][2]["rows"] == [
        {"deviceId": "D1", "faulty": False},
        {"deviceId": "D2", "faulty": None},  # FR-4.7
    ]


# ======================================================================
# RULE-0 -- the guard to point a panel at
# ======================================================================

#: Use-case vocabulary from both test use cases. None of it may appear anywhere
#: in backend/, in any casing, in code or in prose. Matched as substrings, so
#: "traded" fails too -- exactly what `grep -ri trade backend/` would catch.
DOMAIN_TERMS = (
    "trade",
    "tradeId",
    "customer",
    "customerId",
    "amount",
    "country",
)

#: `status` is a field name in the brief's example schema *and* ordinary HTTP
#: vocabulary, so it is checked as a whole word with two narrow exemptions. Note
#: `status_code` never matches: `_` is a word character.
AMBIGUOUS_TERM = re.compile(r"\bstatus\b", re.IGNORECASE)

EXEMPTIONS = (
    # FR-5.4 mandates this exact body for GET /health.
    re.compile(r'\{"status":\s*"ok"\}'),
    # English prose about HTTP status codes in docstrings.
    re.compile(r"status\s+code", re.IGNORECASE),
)


def test_there_are_source_files_to_check() -> None:
    """Guards the guard: a glob that matches nothing passes everything."""
    files = source_files()

    assert len(files) >= 15, f"only found {len(files)} modules under backend/"
    assert all(path.suffix == ".py" for path in files)


def test_no_domain_term_appears_anywhere_in_the_backend() -> None:
    """RULE-0. The platform has never heard of a trade or a customer.

    This is the test to point a panel at when they ask how you know the platform
    is generic: the use-case vocabulary exists in runtime data, in tests and in
    documentation, and nowhere in the code that serves it.
    """
    hits: list[str] = []
    for path in source_files():
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            lowered = line.lower()
            for term in DOMAIN_TERMS:
                if term.lower() in lowered:
                    hits.append(f"{relative(path)}:{number}: {term!r} in {line.strip()!r}")

    assert not hits, "RULE-0 violated -- domain vocabulary in backend/:\n" + "\n".join(hits)


def test_status_appears_only_as_http_vocabulary() -> None:
    """`status` is the one word both vocabularies claim.

    Every occurrence in backend/ must be about HTTP. A domain use -- a field
    name, a branch on a schema's contents -- fails here.
    """
    hits: list[str] = []
    for path in source_files():
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            remainder = line
            for exemption in EXEMPTIONS:
                remainder = exemption.sub("", remainder)
            if AMBIGUOUS_TERM.search(remainder):
                hits.append(f"{relative(path)}:{number}: {line.strip()!r}")

    assert not hits, (
        "RULE-0 violated -- 'status' used as domain vocabulary in backend/:\n"
        + "\n".join(hits)
    )


def test_the_guard_would_catch_a_violation() -> None:
    """A guard that cannot fail proves nothing. This checks the matcher itself."""
    offending = 'if field.name == "tradeId":'

    assert any(term.lower() in offending.lower() for term in DOMAIN_TERMS)
    assert AMBIGUOUS_TERM.search('config["status"]') is not None


# ======================================================================
# NFR-7 -- layer discipline, checked rather than asserted
# ======================================================================


def imported_modules(path: Path) -> set[str]:
    """Every module name imported by a source file."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


@pytest.mark.parametrize(
    ("package", "forbidden"),
    [
        ("core", ("backend.api", "fastapi")),
        ("store", ("backend.api", "backend.core", "fastapi")),
    ],
)
def test_layer_discipline(package: str, forbidden: tuple[str, ...]) -> None:
    """NFR-7: api -> core -> store, never the reverse.

    core/ holds the logic and knows nothing about transport; store/ holds state
    and knows nothing about either. Enforced by reading the imports, so the rule
    cannot quietly stop being true.
    """
    violations: list[str] = []
    for path in source_files():
        if path.parent.name != package:
            continue
        for module in imported_modules(path):
            if any(module == name or module.startswith(f"{name}.") for name in forbidden):
                violations.append(f"{relative(path)} imports {module}")

    assert not violations, "NFR-7 violated:\n" + "\n".join(violations)


# ======================================================================
# NFR-9 -- type hints throughout
# ======================================================================


def test_every_function_is_fully_annotated() -> None:
    """NFR-9: the codebase should read as production Python.

    Every parameter and every return annotated, `self` excepted. Checked by
    parsing rather than by eye, because "throughout" is the kind of claim that
    decays one hurried function at a time.
    """
    unannotated: list[str] = []
    for path in source_files():
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            arguments = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
            missing = [
                argument.arg
                for argument in arguments
                if argument.annotation is None and argument.arg not in ("self", "cls")
            ]
            if node.returns is None:
                missing.append("-> return")
            if missing:
                unannotated.append(
                    f"{relative(path)}:{node.lineno}: {node.name}() missing {missing}"
                )

    assert not unannotated, "NFR-9 violated:\n" + "\n".join(unannotated)
