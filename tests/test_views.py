"""T7 -- view handler registry. NFR-1, FR-3.6-FR-3.10, FR-4.5-FR-4.7.

Cases are transcribed from REQUIREMENTS.md FR-3 and FR-4, not read off the
implementation. Domain names are fine here; they are banned only in backend/
(RULE-0).
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Any

import pytest

from backend.core import views
from backend.core.errors import ErrorCode, ValidationIssue
from backend.core.models import SchemaRequest
from backend.core.views import (
    ViewConfig,
    get,
    is_registered,
    register,
    resolve_aggregation,
    supported_views,
)
from backend.store.base import Row

TRADE_SCHEMA: dict[str, Any] = {
    "name": "trade",
    "fields": [
        {"name": "tradeId", "type": "string", "required": True},
        {"name": "amount", "type": "number", "required": True, "aggregation": "sum"},
        {"name": "status", "type": "string"},
    ],
}

ROWS: list[Row] = [
    {"tradeId": "T001", "amount": 10000, "status": "OPEN"},
    {"tradeId": "T002", "amount": 5000, "status": "CLOSED"},
    {"tradeId": "T003", "amount": 10000, "status": "OPEN"},
]


def schema(**overrides: Any) -> SchemaRequest:
    payload = dict(TRADE_SCHEMA)
    payload.update(overrides)
    return SchemaRequest.model_validate(payload)


def schema_of(*fields: dict[str, Any]) -> SchemaRequest:
    return SchemaRequest.model_validate({"name": "s", "fields": list(fields)})


def validate(config: ViewConfig, on: SchemaRequest | None = None) -> list[ValidationIssue]:
    return get(config["type"]).validate(config, on or schema())


def resolve(
    config: ViewConfig,
    rows: Sequence[Row] | None = None,
    on: SchemaRequest | None = None,
) -> dict[str, Any]:
    return get(config["type"]).resolve(config, on or schema(), ROWS if rows is None else rows)


def codes(issues: list[ValidationIssue]) -> list[ErrorCode]:
    return [issue.code for issue in issues]


# ======================================================================
# summary -- validation (FR-3.6 - FR-3.8)
# ======================================================================


def test_summary_with_an_explicit_aggregation_is_valid() -> None:
    assert validate({"type": "summary", "field": "amount", "aggregation": "sum"}) == []


def test_summary_field_must_exist_in_the_schema() -> None:
    issues = validate({"type": "summary", "field": "notional", "aggregation": "sum"})

    assert codes(issues) == [ErrorCode.UNKNOWN_FIELD]  # FR-3.6
    assert issues[0].field == "notional"


def test_summary_without_a_field_key_is_rejected() -> None:
    issues = validate({"type": "summary", "aggregation": "sum"})

    assert codes(issues) == [ErrorCode.MISSING_REQUIRED_FIELD]  # FR-3.6
    assert issues[0].field == "field"


def test_summary_field_names_are_case_sensitive() -> None:
    assert codes(validate({"type": "summary", "field": "Amount"})) == [
        ErrorCode.UNKNOWN_FIELD
    ]  # FR-3.6


def test_an_unknown_field_does_not_also_report_an_aggregation_problem() -> None:
    """Legality is a question about the field's type, and there is no field."""
    issues = validate({"type": "summary", "field": "notional", "aggregation": "nope"})

    assert codes(issues) == [ErrorCode.UNKNOWN_FIELD]  # FR-3.6


# -- the FR-3.7 precedence chain, all three outcomes --------------------


def test_aggregation_comes_from_the_view_when_given() -> None:
    """First link: the view config wins."""
    issues = validate({"type": "summary", "field": "amount", "aggregation": "avg"})

    assert issues == []  # FR-3.7
    assert resolve({"type": "summary", "field": "amount", "aggregation": "avg"})[
        "aggregation"
    ] == "avg"


def test_the_view_aggregation_overrides_the_schema_default() -> None:
    """`amount` declares `sum`; the view asks for `max` and gets `max`."""
    output = resolve({"type": "summary", "field": "amount", "aggregation": "max"})

    assert output["aggregation"] == "max"  # FR-3.7
    assert output["value"] == 10000


def test_aggregation_falls_back_to_the_schema_field_default() -> None:
    """Second link: the view omits it, so `amount`'s declared `sum` applies."""
    config = {"type": "summary", "field": "amount"}

    assert validate(config) == []  # FR-3.7
    assert resolve(config)["aggregation"] == "sum"  # FR-3.7


def test_aggregation_required_when_neither_source_supplies_one() -> None:
    """Third link: `status` declares no default and the view gives none."""
    issues = validate({"type": "summary", "field": "status"})

    assert codes(issues) == [ErrorCode.AGGREGATION_REQUIRED]  # FR-3.7
    assert issues[0].field == "status"


def test_no_implicit_sum_when_the_aggregation_is_missing() -> None:
    """A silently wrong dashboard is worse than a loud failure (DECISION-4)."""
    assert codes(validate({"type": "summary", "field": "status"})) != []  # FR-3.7


def test_validate_and_resolve_agree_on_the_resolved_aggregation() -> None:
    """The single shared chain: what was checked is what gets applied."""
    field = {f.name: f for f in schema().fields}["amount"]
    config = {"type": "summary", "field": "amount"}

    assert resolve_aggregation(config, field) == "sum"  # FR-3.7
    assert resolve(config)["aggregation"] == resolve_aggregation(config, field)


# -- FR-3.8 legality ----------------------------------------------------


def test_an_aggregation_illegal_for_the_field_type_is_rejected() -> None:
    """The FR-3.8 example: sum on a string field."""
    issues = validate({"type": "summary", "field": "status", "aggregation": "sum"})

    assert codes(issues) == [ErrorCode.INVALID_AGGREGATION]  # FR-3.8
    assert issues[0].field == "status"
    assert issues[0].actual == "string"


def test_an_illegal_schema_default_is_caught_through_the_chain() -> None:
    """A default inherited from the schema is checked as hard as an explicit one."""
    one_field = schema_of({"name": "flag", "type": "boolean", "aggregation": "count"})

    assert validate({"type": "summary", "field": "flag"}, on=one_field) == []  # FR-3.8


def test_count_is_legal_on_a_string_field() -> None:
    assert validate({"type": "summary", "field": "status", "aggregation": "count"}) == []


def test_an_unregistered_aggregation_is_rejected() -> None:
    issues = validate({"type": "summary", "field": "amount", "aggregation": "median"})

    assert codes(issues) == [ErrorCode.UNKNOWN_AGGREGATION]  # FR-3.7
    assert issues[0].actual == "median"
    assert issues[0].expected is not None and "sum" in issues[0].expected


def test_unknown_and_illegal_aggregations_get_different_codes() -> None:
    unknown = validate({"type": "summary", "field": "amount", "aggregation": "median"})
    illegal = validate({"type": "summary", "field": "status", "aggregation": "sum"})

    assert codes(unknown) != codes(illegal)  # FR-3.7, FR-3.8


# ======================================================================
# summary -- resolution (FR-4.5)
# ======================================================================


def test_summary_aggregates_across_all_rows() -> None:
    output = resolve({"type": "summary", "field": "amount", "aggregation": "sum"})

    assert output == {
        "type": "summary",
        "field": "amount",
        "aggregation": "sum",
        "value": 25000,
    }  # FR-4.5


@pytest.mark.parametrize(
    ("aggregation", "expected"),
    [("sum", 25000), ("avg", 25000 / 3), ("min", 5000), ("max", 10000), ("count", 3)],
)
def test_every_aggregation_resolves(aggregation: str, expected: Any) -> None:
    config = {"type": "summary", "field": "amount", "aggregation": aggregation}

    assert resolve(config)["value"] == expected  # FR-4.5


def test_summary_on_an_empty_dataset_does_not_raise() -> None:
    config = {"type": "summary", "field": "amount", "aggregation": "sum"}

    assert resolve(config, rows=[])["value"] == 0  # FR-4.8


@pytest.mark.parametrize(
    ("aggregation", "expected"),
    [("sum", 0), ("count", 0), ("avg", None), ("min", None), ("max", None)],
)
def test_empty_dataset_results_reach_through_the_view(
    aggregation: str, expected: Any
) -> None:
    config = {"type": "summary", "field": "amount", "aggregation": aggregation}

    assert resolve(config, rows=[])["value"] == expected  # FR-4.8


def test_summary_counts_values_not_rows() -> None:
    """DECISION-20: count means COUNT(column), not COUNT(*). Two of three rows
    carry `status`, and rowCount in the FR-4 response reports the third."""
    rows: list[Row] = [
        {"tradeId": "T001", "amount": 1, "status": "OPEN"},
        {"tradeId": "T002", "amount": 2},
        {"tradeId": "T003", "amount": 3, "status": "OPEN"},
    ]

    output = resolve({"type": "summary", "field": "status", "aggregation": "count"}, rows)

    assert output["value"] == 2  # FR-4.5
    assert len(rows) == 3


def test_summary_skips_absent_values_when_aggregating() -> None:
    """sum cannot include a value that is not there; count agrees with it."""
    rows: list[Row] = [
        {"tradeId": "T001", "amount": 1000},
        {"tradeId": "T002"},
        {"tradeId": "T003", "amount": 3000},
    ]

    assert resolve({"type": "summary", "field": "amount"}, rows)["value"] == 4000
    assert (
        resolve({"type": "summary", "field": "amount", "aggregation": "avg"}, rows)[
            "value"
        ]
        == 2000
    )  # FR-4.5


def test_summary_over_a_field_absent_from_every_row_is_the_empty_result() -> None:
    rows: list[Row] = [{"tradeId": "T001", "amount": 1}]
    config = {"type": "summary", "field": "status", "aggregation": "count"}

    assert resolve(config, rows)["value"] == 0  # FR-4.8


def test_summary_does_not_mutate_the_rows_it_reads() -> None:
    rows = [dict(row) for row in ROWS]

    resolve({"type": "summary", "field": "amount", "aggregation": "sum"}, rows)

    assert rows == ROWS  # FR-4.9


# ======================================================================
# table -- validation (FR-3.9, FR-3.10)
# ======================================================================


def test_table_with_known_columns_is_valid() -> None:
    config = {"type": "table", "columns": ["tradeId", "amount", "status"]}

    assert validate(config) == []  # FR-3.9


def test_table_column_must_exist_in_the_schema() -> None:
    issues = validate({"type": "table", "columns": ["tradeId", "currency"]})

    assert codes(issues) == [ErrorCode.UNKNOWN_FIELD]  # FR-3.9
    assert issues[0].field == "currency"


def test_every_unknown_column_is_reported() -> None:
    """One round trip to fix, not one per column."""
    issues = validate({"type": "table", "columns": ["currency", "amount", "desk"]})

    assert codes(issues) == [ErrorCode.UNKNOWN_FIELD, ErrorCode.UNKNOWN_FIELD]  # FR-3.9
    assert [issue.field for issue in issues] == ["currency", "desk"]


def test_table_columns_must_be_non_empty() -> None:
    issues = validate({"type": "table", "columns": []})

    assert codes(issues) == [ErrorCode.MISSING_REQUIRED_FIELD]  # FR-3.10
    assert issues[0].field == "columns"


def test_table_without_a_columns_key_is_rejected() -> None:
    assert codes(validate({"type": "table"})) == [
        ErrorCode.MISSING_REQUIRED_FIELD
    ]  # FR-3.10


def test_table_columns_must_be_a_list() -> None:
    assert codes(validate({"type": "table", "columns": "tradeId"})) == [
        ErrorCode.MISSING_REQUIRED_FIELD
    ]  # FR-3.10


# ======================================================================
# table -- resolution (FR-4.6, FR-4.7)
# ======================================================================


def test_table_projects_exactly_the_configured_columns() -> None:
    output = resolve({"type": "table", "columns": ["tradeId", "amount"]})

    assert output["columns"] == ["tradeId", "amount"]
    assert output["rows"] == [
        {"tradeId": "T001", "amount": 10000},
        {"tradeId": "T002", "amount": 5000},
        {"tradeId": "T003", "amount": 10000},
    ]  # FR-4.6


def test_table_emits_no_extra_keys() -> None:
    """`status` is in the schema and in the rows, but not in the config."""
    output = resolve({"type": "table", "columns": ["tradeId"]})

    assert all(set(row) == {"tradeId"} for row in output["rows"])  # FR-4.6


def test_table_preserves_the_configured_column_order() -> None:
    output = resolve({"type": "table", "columns": ["status", "tradeId", "amount"]})

    assert output["columns"] == ["status", "tradeId", "amount"]
    assert list(output["rows"][0]) == ["status", "tradeId", "amount"]  # FR-4.6


def test_table_preserves_row_order() -> None:
    output = resolve({"type": "table", "columns": ["tradeId"]})

    assert [row["tradeId"] for row in output["rows"]] == ["T001", "T002", "T003"]


def test_an_absent_optional_value_projects_as_null() -> None:
    """FR-4.7: rows stay rectangular. Rows are stored with null optionals absent
    (T6), so this is where absence becomes null again."""
    rows: list[Row] = [
        {"tradeId": "T001", "amount": 1000, "status": "OPEN"},
        {"tradeId": "T002", "amount": 2000},
    ]

    output = resolve({"type": "table", "columns": ["tradeId", "status"]}, rows)

    assert output["rows"] == [
        {"tradeId": "T001", "status": "OPEN"},
        {"tradeId": "T002", "status": None},
    ]  # FR-4.7


def test_an_absent_value_is_null_not_omitted() -> None:
    """Every row must carry every configured column as a key."""
    rows: list[Row] = [{"tradeId": "T002", "amount": 2000}]

    output = resolve({"type": "table", "columns": ["tradeId", "status"]}, rows)

    assert "status" in output["rows"][0]  # FR-4.7
    assert output["rows"][0]["status"] is None


def test_table_on_an_empty_dataset_is_an_empty_list() -> None:
    output = resolve({"type": "table", "columns": ["tradeId"]}, rows=[])

    assert output["rows"] == []  # FR-4.8
    assert output["columns"] == ["tradeId"]


def test_table_does_not_mutate_the_rows_it_reads() -> None:
    rows = [dict(row) for row in ROWS]

    resolve({"type": "table", "columns": ["tradeId"]}, rows)

    assert rows == ROWS  # FR-4.9


def test_projected_rows_are_independent_of_the_stored_rows() -> None:
    rows = [dict(row) for row in ROWS]

    output = resolve({"type": "table", "columns": ["tradeId"]}, rows)
    output["rows"][0]["tradeId"] = "MUTATED"

    assert rows[0]["tradeId"] == "T001"  # FR-4.9


# ======================================================================
# The registry (FR-3.4, NFR-1)
# ======================================================================


def test_both_view_types_are_registered() -> None:
    assert supported_views() == ["summary", "table"]


@pytest.mark.parametrize("view_type", ["summary", "table"])
def test_is_registered_is_true_for_supported_views(view_type: str) -> None:
    assert is_registered(view_type) is True  # FR-3.4


@pytest.mark.parametrize("view_type", ["chart", "Summary", "SUMMARY", "", "grid"])
def test_is_registered_is_false_for_unsupported_views(view_type: str) -> None:
    assert is_registered(view_type) is False  # FR-3.4


def test_unknown_view_type_names_the_supported_ones() -> None:
    """FR-3.4 requires the rejection to list supported view types."""
    with pytest.raises(KeyError) as excinfo:
        get("chart")

    message = str(excinfo.value)
    for view_type in supported_views():
        assert view_type in message  # FR-3.4


def test_a_handler_exposes_both_operations() -> None:
    for view_type in supported_views():
        handler = get(view_type)
        assert handler.name == view_type
        assert callable(handler.validate)
        assert callable(handler.resolve)


# -- NFR-1: a third view type is a pure addition ------------------------


@pytest.fixture()
def restore_registry() -> Iterator[None]:
    """Snapshot and restore the registry so extension tests do not leak.

    Reaches into the private _REGISTRY deliberately: the alternative is an
    `unregister` function in the production API that only tests would ever call.
    """
    snapshot = dict(views._REGISTRY)
    yield
    views._REGISTRY.clear()
    views._REGISTRY.update(snapshot)


def test_a_third_view_type_is_a_pure_addition(restore_registry: None) -> None:
    """NFR-1, proven rather than asserted: one handler, one registration, and no
    edit to any existing module. Under 20 lines, as the requirement asks."""

    def _validate_distinct(
        config: ViewConfig, schema_: SchemaRequest
    ) -> list[ValidationIssue]:
        field_name = config.get("field")
        if field_name not in {field.name for field in schema_.fields}:
            return [ValidationIssue(field=str(field_name), code=ErrorCode.UNKNOWN_FIELD)]
        return []

    @register("distinct", validate=_validate_distinct, config_keys={"field"})
    def _resolve_distinct(
        config: ViewConfig, schema_: SchemaRequest, rows: Sequence[Row]
    ) -> dict[str, Any]:
        field_name = config["field"]
        seen = {row[field_name] for row in rows if row.get(field_name) is not None}
        return {"type": "distinct", "field": field_name, "values": sorted(seen)}

    assert is_registered("distinct") is True  # NFR-1
    assert "distinct" in supported_views()

    config = {"type": "distinct", "field": "status"}
    assert validate(config) == []  # NFR-1
    assert resolve(config) == {
        "type": "distinct",
        "field": "status",
        "values": ["CLOSED", "OPEN"],
    }  # NFR-1

    assert codes(validate({"type": "distinct", "field": "nope"})) == [
        ErrorCode.UNKNOWN_FIELD
    ]

    # The handlers already registered are unaffected.
    assert resolve({"type": "summary", "field": "amount"})["value"] == 25000


def test_registering_a_duplicate_view_type_is_refused(restore_registry: None) -> None:
    """A silent overwrite would make the winner depend on import order."""
    with pytest.raises(ValueError, match="already registered"):
        register("summary", validate=lambda config, schema_: [], config_keys=set())(
            lambda config, schema_, rows: {}
        )


def test_the_registry_is_unchanged_after_the_extension_tests() -> None:
    """Ordering-independent guard that restore_registry actually restores."""
    assert supported_views() == ["summary", "table"]
