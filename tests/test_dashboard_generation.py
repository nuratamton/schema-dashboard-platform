"""T9 -- dashboard generation. FR-4.1-FR-4.9.

Must include: empty dataset (FR-4.8).
Must include: generation does not mutate stored rows (FR-4.9).

Cases are transcribed from REQUIREMENTS.md FR-4, not read off the
implementation. Domain names are fine here; they are banned only in backend/
(RULE-0).
"""

from __future__ import annotations

import copy
from collections.abc import Iterator, Sequence
from typing import Any

import pytest

from backend.core import views
from backend.core.dashboards import generate_dashboard, register_dashboard
from backend.core.errors import ErrorCode, UnknownDashboard, ValidationIssue
from backend.core.models import DashboardRequest, IngestRequest, SchemaRequest
from backend.core.validation import ingest_rows, register_schema
from backend.core.views import ViewConfig, register
from backend.store.base import Row
from backend.store.memory import InMemoryRepository

TRADE_SCHEMA: dict[str, Any] = {
    "name": "trade",
    "fields": [
        {"name": "tradeId", "type": "string", "required": True},
        {"name": "amount", "type": "number", "required": True, "aggregation": "sum"},
        {"name": "status", "type": "string"},
    ],
}

TRADE_ROWS: list[dict[str, Any]] = [
    {"tradeId": "T001", "amount": 10000, "status": "OPEN"},
    {"tradeId": "T002", "amount": 5000, "status": "CLOSED"},
    {"tradeId": "T003", "amount": 10000, "status": "OPEN"},
]

TRADE_DASHBOARD: dict[str, Any] = {
    "name": "trade-dashboard",
    "schema": "trade",
    "views": [
        {"type": "summary", "field": "amount", "aggregation": "sum"},
        {"type": "table", "columns": ["tradeId", "amount", "status"]},
    ],
}

CUSTOMER_SCHEMA: dict[str, Any] = {
    "name": "customer",
    "fields": [
        {"name": "customerId", "type": "string", "required": True},
        {"name": "name", "type": "string", "required": True},
        {"name": "country", "type": "string"},
    ],
}

CUSTOMER_ROWS: list[dict[str, Any]] = [
    {"customerId": "C001", "name": "Acme", "country": "UK"},
    {"customerId": "C002", "name": "Globex", "country": "US"},
]

CUSTOMER_DASHBOARD: dict[str, Any] = {
    "name": "customer-dashboard",
    "schema": "customer",
    "views": [
        {"type": "summary", "field": "customerId", "aggregation": "count"},
        {"type": "table", "columns": ["customerId", "name", "country"]},
    ],
}


def build(
    repository: InMemoryRepository,
    schema: dict[str, Any],
    rows: list[dict[str, Any]] | None = None,
    dashboard: dict[str, Any] | None = None,
) -> InMemoryRepository:
    """Register a schema, optionally ingest rows, optionally register a config."""
    register_schema(SchemaRequest.model_validate(schema), repository)
    if rows:
        ingest_rows(
            IngestRequest.model_validate({"schema": schema["name"], "rows": rows}),
            repository,
        )
    if dashboard:
        register_dashboard(DashboardRequest.model_validate(dashboard), repository)
    return repository


@pytest.fixture()
def repo() -> InMemoryRepository:
    """The brief's example: one schema, three rows, one dashboard."""
    return build(InMemoryRepository(), TRADE_SCHEMA, TRADE_ROWS, TRADE_DASHBOARD)


@pytest.fixture()
def empty_repo() -> InMemoryRepository:
    """Schema and dashboard registered, no rows ingested."""
    return build(InMemoryRepository(), TRADE_SCHEMA, None, TRADE_DASHBOARD)


def summary_of(field: str, aggregation: str | None = None) -> dict[str, Any]:
    view: dict[str, Any] = {"type": "summary", "field": field}
    if aggregation is not None:
        view["aggregation"] = aggregation
    return view


# ======================================================================
# FR-4.1 -- unknown dashboard
# ======================================================================


def test_unknown_dashboard_is_a_404(repo: InMemoryRepository) -> None:
    with pytest.raises(UnknownDashboard) as excinfo:
        generate_dashboard("nope", repo)

    assert excinfo.value.status_code == 404  # FR-4.1, NFR-6
    assert excinfo.value.code is ErrorCode.UNKNOWN_DASHBOARD
    assert "nope" in excinfo.value.message


def test_dashboard_names_are_case_sensitive(repo: InMemoryRepository) -> None:
    with pytest.raises(UnknownDashboard):
        generate_dashboard("Trade-Dashboard", repo)  # FR-4.1


def test_a_schema_name_is_not_a_dashboard_name(repo: InMemoryRepository) -> None:
    """Separate namespaces in the store; generation looks in only one."""
    with pytest.raises(UnknownDashboard):
        generate_dashboard("trade", repo)  # FR-4.1


# ======================================================================
# FR-4.2, FR-4.5, FR-4.6 -- the response
# ======================================================================


def test_the_brief_example_dashboard_generates(repo: InMemoryRepository) -> None:
    """The FR-4 response, whole."""
    assert generate_dashboard("trade-dashboard", repo) == {
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
                "rows": TRADE_ROWS,
            },
        ],
    }


def test_the_response_carries_exactly_the_four_top_level_keys(
    repo: InMemoryRepository,
) -> None:
    output = generate_dashboard("trade-dashboard", repo)

    assert list(output) == ["dashboard", "schema", "rowCount", "views"]


def test_the_response_names_the_bound_schema(repo: InMemoryRepository) -> None:
    """FR-4.2: the registered schema is an input, and the output says which."""
    assert generate_dashboard("trade-dashboard", repo)["schema"] == "trade"


def test_row_count_reports_the_dataset_size(repo: InMemoryRepository) -> None:
    assert generate_dashboard("trade-dashboard", repo)["rowCount"] == 3


def test_row_count_tracks_later_ingests(repo: InMemoryRepository) -> None:
    """Generation reads live state; nothing is cached at registration."""
    ingest_rows(
        IngestRequest.model_validate(
            {"schema": "trade", "rows": [{"tradeId": "T004", "amount": 1000}]}
        ),
        repo,
    )

    output = generate_dashboard("trade-dashboard", repo)

    assert output["rowCount"] == 4  # FR-4.2
    assert output["views"][0]["value"] == 26000


def test_row_count_is_independent_of_the_configured_views(
    repo: InMemoryRepository,
) -> None:
    """rowCount is a fact about the dataset, not about any view's projection."""
    build(
        repo,
        {"name": "s", "fields": [{"name": "a", "type": "string"}]},
        None,
        {"name": "one-column", "schema": "trade", "views": [
            {"type": "table", "columns": ["tradeId"]}
        ]},
    )

    assert generate_dashboard("one-column", repo)["rowCount"] == 3


def test_generation_reads_the_schema_not_only_the_rows(
    empty_repo: InMemoryRepository,
) -> None:
    """FR-4.2. The view omits `aggregation`, so the only place `sum` can come
    from is the schema's field default -- generation must be reading it."""
    register_dashboard(
        DashboardRequest.model_validate(
            {"name": "defaulted", "schema": "trade", "views": [summary_of("amount")]}
        ),
        empty_repo,
    )

    output = generate_dashboard("defaulted", empty_repo)

    assert output["views"][0]["aggregation"] == "sum"  # FR-4.2


# ======================================================================
# FR-4.3 -- declaration order
# ======================================================================


def test_views_resolve_in_configured_order(repo: InMemoryRepository) -> None:
    build(
        repo,
        {"name": "other", "fields": [{"name": "a", "type": "string"}]},
        None,
        {
            "name": "ordered",
            "schema": "trade",
            "views": [
                {"type": "table", "columns": ["status"]},
                summary_of("amount", "max"),
                summary_of("amount", "min"),
                {"type": "table", "columns": ["tradeId"]},
            ],
        },
    )

    output = generate_dashboard("ordered", repo)

    assert [view["type"] for view in output["views"]] == [
        "table",
        "summary",
        "summary",
        "table",
    ]  # FR-4.3
    assert [view.get("aggregation") for view in output["views"]] == [
        None,
        "max",
        "min",
        None,
    ]


def test_repeated_view_types_are_each_resolved(repo: InMemoryRepository) -> None:
    """Two summaries over the same field with different aggregations."""
    build(
        repo,
        {"name": "other", "fields": [{"name": "a", "type": "string"}]},
        None,
        {
            "name": "two-summaries",
            "schema": "trade",
            "views": [summary_of("amount", "min"), summary_of("amount", "max")],
        },
    )

    output = generate_dashboard("two-summaries", repo)

    assert [view["value"] for view in output["views"]] == [5000, 10000]  # FR-4.3


# ======================================================================
# FR-4.7 -- absent optionals project as null
# ======================================================================


def test_an_absent_optional_projects_as_null() -> None:
    """Rows are stored with null optionals absent (T6); the table restores them
    so every row carries every configured column."""
    repository = build(
        InMemoryRepository(),
        TRADE_SCHEMA,
        [
            {"tradeId": "T001", "amount": 1000, "status": "OPEN"},
            {"tradeId": "T002", "amount": 2000},
            {"tradeId": "T003", "amount": 3000, "status": None},
        ],
        TRADE_DASHBOARD,
    )

    output = generate_dashboard("trade-dashboard", repository)

    assert output["views"][1]["rows"] == [
        {"tradeId": "T001", "amount": 1000, "status": "OPEN"},
        {"tradeId": "T002", "amount": 2000, "status": None},
        {"tradeId": "T003", "amount": 3000, "status": None},
    ]  # FR-4.7


def test_every_projected_row_has_every_column(repo: InMemoryRepository) -> None:
    ingest_rows(
        IngestRequest.model_validate(
            {"schema": "trade", "rows": [{"tradeId": "T004", "amount": 4000}]}
        ),
        repo,
    )

    table = generate_dashboard("trade-dashboard", repo)["views"][1]

    assert all(list(row) == table["columns"] for row in table["rows"])  # FR-4.7


# ======================================================================
# FR-4.8 -- the empty dataset, across all five aggregations
# ======================================================================


@pytest.mark.parametrize(
    ("aggregation", "expected"),
    [("sum", 0), ("count", 0), ("avg", None), ("min", None), ("max", None)],
)
def test_empty_dataset_summary_does_not_raise(
    aggregation: str, expected: Any, empty_repo: InMemoryRepository
) -> None:
    register_dashboard(
        DashboardRequest.model_validate(
            {
                "name": f"empty-{aggregation}",
                "schema": "trade",
                "views": [summary_of("amount", aggregation)],
            }
        ),
        empty_repo,
    )

    output = generate_dashboard(f"empty-{aggregation}", empty_repo)

    assert output["views"][0]["value"] == expected  # FR-4.8
    assert output["rowCount"] == 0


@pytest.mark.parametrize("aggregation", ["avg", "min", "max"])
def test_empty_dataset_gives_null_not_zero(
    aggregation: str, empty_repo: InMemoryRepository
) -> None:
    """0 would be a claim about the data; null says there is no answer."""
    register_dashboard(
        DashboardRequest.model_validate(
            {
                "name": f"e-{aggregation}",
                "schema": "trade",
                "views": [summary_of("amount", aggregation)],
            }
        ),
        empty_repo,
    )

    assert generate_dashboard(f"e-{aggregation}", empty_repo)["views"][0][
        "value"
    ] is None  # FR-4.8


def test_empty_dataset_table_is_an_empty_list(empty_repo: InMemoryRepository) -> None:
    output = generate_dashboard("trade-dashboard", empty_repo)

    assert output["views"][1]["rows"] == []  # FR-4.8
    assert output["views"][1]["columns"] == ["tradeId", "amount", "status"]
    assert output["rowCount"] == 0


def test_a_whole_dashboard_generates_before_any_ingest(
    empty_repo: InMemoryRepository,
) -> None:
    """A dashboard is registrable and renderable with no data at all."""
    assert generate_dashboard("trade-dashboard", empty_repo) == {
        "dashboard": "trade-dashboard",
        "schema": "trade",
        "rowCount": 0,
        "views": [
            {"type": "summary", "field": "amount", "aggregation": "sum", "value": 0},
            {
                "type": "table",
                "columns": ["tradeId", "amount", "status"],
                "rows": [],
            },
        ],
    }  # FR-4.8


# ======================================================================
# FR-4.9 -- generation never mutates stored data
# ======================================================================


def test_generation_leaves_the_stored_rows_unchanged(repo: InMemoryRepository) -> None:
    before = copy.deepcopy(repo.get_rows("trade"))

    generate_dashboard("trade-dashboard", repo)

    assert repo.get_rows("trade") == before  # FR-4.9
    assert repo.count_rows("trade") == 3


def test_mutating_the_generated_payload_does_not_reach_the_store(
    repo: InMemoryRepository,
) -> None:
    """The returned payload is the caller's to do what it likes with."""
    output = generate_dashboard("trade-dashboard", repo)

    output["views"][1]["rows"][0]["amount"] = 999999
    output["views"][1]["rows"].append({"tradeId": "INJECTED"})
    output["views"][1]["columns"].append("injected")
    output["views"][0]["value"] = 0

    assert repo.get_rows("trade") == TRADE_ROWS  # FR-4.9
    assert repo.count_rows("trade") == 3


def test_generating_twice_gives_the_same_answer(repo: InMemoryRepository) -> None:
    """Generation is a read: nothing it does changes what it reads next time."""
    first = generate_dashboard("trade-dashboard", repo)
    first["views"][1]["rows"].clear()

    assert generate_dashboard("trade-dashboard", repo)["views"][1]["rows"] == TRADE_ROWS


def test_generation_does_not_mutate_the_stored_config(repo: InMemoryRepository) -> None:
    stored_views = copy.deepcopy(repo.get_dashboard("trade-dashboard").views)

    output = generate_dashboard("trade-dashboard", repo)
    output["views"][1]["columns"].append("injected")

    assert repo.get_dashboard("trade-dashboard").views == stored_views  # FR-4.9


# ======================================================================
# FR-4.4 -- dispatch through the registry, no per-type branching
# ======================================================================


@pytest.fixture()
def restore_registry() -> Iterator[None]:
    snapshot = dict(views._REGISTRY)
    yield
    views._REGISTRY.clear()
    views._REGISTRY.update(snapshot)


def test_a_new_view_type_generates_without_editing_the_generator(
    repo: InMemoryRepository, restore_registry: None
) -> None:
    """FR-4.4, proven: the generator contains no knowledge of view types, so a
    handler registered at runtime resolves through it untouched."""

    def _validate_distinct(
        config: ViewConfig, schema: SchemaRequest
    ) -> list[ValidationIssue]:
        if config.get("field") not in {field.name for field in schema.fields}:
            return [ValidationIssue(field="field", code=ErrorCode.UNKNOWN_FIELD)]
        return []

    @register("distinct", validate=_validate_distinct, config_keys={"field"})
    def _resolve_distinct(
        config: ViewConfig, schema: SchemaRequest, rows: Sequence[Row]
    ) -> dict[str, Any]:
        field = config["field"]
        return {
            "type": "distinct",
            "field": field,
            "values": sorted({row[field] for row in rows if row.get(field) is not None}),
        }

    register_dashboard(
        DashboardRequest.model_validate(
            {
                "name": "with-distinct",
                "schema": "trade",
                "views": [
                    {"type": "distinct", "field": "status"},
                    summary_of("amount", "sum"),
                ],
            }
        ),
        repo,
    )

    output = generate_dashboard("with-distinct", repo)

    assert output["views"][0] == {
        "type": "distinct",
        "field": "status",
        "values": ["CLOSED", "OPEN"],
    }  # FR-4.4
    assert output["views"][1]["value"] == 25000
    assert output["rowCount"] == 3


# ======================================================================
# Two use cases, side by side (FR-4.2, the platform's premise)
# ======================================================================


def test_two_dashboards_of_different_schemas_generate_side_by_side() -> None:
    """One repository, two unrelated use cases, both correct at once."""
    repository = InMemoryRepository()
    build(repository, TRADE_SCHEMA, TRADE_ROWS, TRADE_DASHBOARD)
    build(repository, CUSTOMER_SCHEMA, CUSTOMER_ROWS, CUSTOMER_DASHBOARD)

    trade = generate_dashboard("trade-dashboard", repository)
    customer = generate_dashboard("customer-dashboard", repository)

    assert trade["schema"] == "trade"  # FR-4.2
    assert trade["rowCount"] == 3
    assert trade["views"][0]["value"] == 25000

    assert customer["schema"] == "customer"  # FR-4.2
    assert customer["rowCount"] == 2
    assert customer["views"][0]["value"] == 2
    assert customer["views"][1]["rows"] == CUSTOMER_ROWS


def test_each_dashboard_reads_only_its_own_dataset() -> None:
    """The binding decides which rows a dashboard sees."""
    repository = InMemoryRepository()
    build(repository, TRADE_SCHEMA, TRADE_ROWS, TRADE_DASHBOARD)
    build(repository, CUSTOMER_SCHEMA, CUSTOMER_ROWS, CUSTOMER_DASHBOARD)

    customer = generate_dashboard("customer-dashboard", repository)

    assert customer["rowCount"] == 2  # FR-4.2
    assert all(set(row) == {"customerId", "name", "country"} for row in customer["views"][1]["rows"])


def test_two_dashboards_over_one_schema_see_the_same_data(
    repo: InMemoryRepository,
) -> None:
    build(
        repo,
        {"name": "other", "fields": [{"name": "a", "type": "string"}]},
        None,
        {
            "name": "second-view",
            "schema": "trade",
            "views": [summary_of("amount", "avg")],
        },
    )

    first = generate_dashboard("trade-dashboard", repo)
    second = generate_dashboard("second-view", repo)

    assert first["rowCount"] == second["rowCount"] == 3  # FR-4.2
    assert second["views"][0]["value"] == 25000 / 3
