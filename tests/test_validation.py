"""T6 -- row validation engine. FR-2.3-FR-2.9.

Must include: missing required, type mismatch per type, unknown field,
null in required, null in optional, and a multi-error batch proving every
issue is collected rather than only the first.

Cases are transcribed from REQUIREMENTS.md FR-2, not read off the
implementation. Domain names are fine here; they are banned only in backend/
(RULE-0).
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from backend.core.errors import ErrorCode, UnknownSchema, ValidationFailed
from backend.core.models import IngestRequest, SchemaRequest
from backend.core.validation import ingest_rows, register_schema, validate_rows
from backend.store.memory import InMemoryRepository

TRADE_SCHEMA: dict[str, Any] = {
    "name": "trade",
    "fields": [
        {"name": "tradeId", "type": "string", "required": True},
        {"name": "amount", "type": "number", "required": True, "aggregation": "sum"},
        {"name": "status", "type": "string"},
    ],
}

VALID_ROW: dict[str, Any] = {"tradeId": "T001", "amount": 1000, "status": "OPEN"}


@pytest.fixture()
def repo() -> InMemoryRepository:
    """A fresh repository with the brief's example schema already registered."""
    repository = InMemoryRepository()
    register_schema(SchemaRequest.model_validate(TRADE_SCHEMA), repository)
    return repository


def trade_schema() -> SchemaRequest:
    return SchemaRequest.model_validate(TRADE_SCHEMA)


def schema_of(*fields: dict[str, Any]) -> SchemaRequest:
    """A one-off schema for a single-field case."""
    return SchemaRequest.model_validate({"name": "s", "fields": list(fields)})


def ingest(rows: list[dict[str, Any]], name: str = "trade") -> IngestRequest:
    return IngestRequest.model_validate({"schema": name, "rows": rows})


def codes(issues: Any) -> list[ErrorCode]:
    return [issue.code for issue in issues]


# ----------------------------------------------------------------------
# The happy path
# ----------------------------------------------------------------------


def test_the_brief_example_row_validates() -> None:
    assert validate_rows(trade_schema(), [VALID_ROW]) == []


def test_an_optional_field_may_be_omitted_entirely() -> None:
    """`status` is optional, so its absence is not a problem."""
    assert validate_rows(trade_schema(), [{"tradeId": "T001", "amount": 1000}]) == []


def test_accepted_rows_are_appended_in_order(repo: InMemoryRepository) -> None:
    rows = [
        {"tradeId": "T001", "amount": 1000, "status": "OPEN"},
        {"tradeId": "T002", "amount": 2000, "status": "CLOSED"},
        {"tradeId": "T003", "amount": 3000, "status": "OPEN"},
    ]

    assert ingest_rows(ingest(rows), repo) == 3

    assert repo.get_rows("trade") == rows  # FR-2.10
    assert repo.count_rows("trade") == 3


def test_successive_batches_accumulate(repo: InMemoryRepository) -> None:
    ingest_rows(ingest([VALID_ROW]), repo)
    ingest_rows(ingest([{"tradeId": "T002", "amount": 2000}]), repo)

    assert repo.count_rows("trade") == 2  # FR-2.10


# ----------------------------------------------------------------------
# Required fields (FR-2.3, FR-2.6)
# ----------------------------------------------------------------------


def test_missing_required_field_is_reported() -> None:
    issues = validate_rows(trade_schema(), [{"amount": 1000}])

    assert codes(issues) == [ErrorCode.MISSING_REQUIRED_FIELD]  # FR-2.3
    assert issues[0].field == "tradeId"
    assert issues[0].row == 0


def test_every_missing_required_field_in_a_row_is_reported() -> None:
    issues = validate_rows(trade_schema(), [{"status": "OPEN"}])

    assert codes(issues) == [
        ErrorCode.MISSING_REQUIRED_FIELD,
        ErrorCode.MISSING_REQUIRED_FIELD,
    ]  # FR-2.3
    assert [issue.field for issue in issues] == ["tradeId", "amount"]


def test_null_does_not_satisfy_a_required_field() -> None:
    """FR-2.6: explicitly null is the same failure as absent, not a value."""
    issues = validate_rows(trade_schema(), [{"tradeId": None, "amount": 1000}])

    assert codes(issues) == [ErrorCode.MISSING_REQUIRED_FIELD]  # FR-2.6
    assert issues[0].field == "tradeId"


def test_null_in_a_required_field_is_not_reported_as_a_type_mismatch() -> None:
    """The failure is that no value was supplied, not that one had the wrong type."""
    issues = validate_rows(trade_schema(), [{"tradeId": None, "amount": 1000}])

    assert ErrorCode.TYPE_MISMATCH not in codes(issues)  # FR-2.6


def test_null_in_an_optional_field_is_accepted() -> None:
    """FR-2.7: accepted, and no type check is applied to it."""
    issues = validate_rows(
        trade_schema(), [{"tradeId": "T001", "amount": 1000, "status": None}]
    )

    assert issues == []  # FR-2.7


def test_a_null_optional_field_is_stored_as_absent(repo: InMemoryRepository) -> None:
    """FR-2.7: stored as absent. FR-4.7 projects it back as null when needed."""
    ingest_rows(ingest([{"tradeId": "T001", "amount": 1000, "status": None}]), repo)

    assert repo.get_rows("trade") == [{"tradeId": "T001", "amount": 1000}]  # FR-2.7


def test_a_false_value_is_not_mistaken_for_a_missing_one() -> None:
    """`if not value` would drop False; the check has to be `is None`."""
    schema = schema_of({"name": "settled", "type": "boolean", "required": True})

    assert validate_rows(schema, [{"settled": False}]) == []  # FR-2.3


def test_a_zero_value_is_not_mistaken_for_a_missing_one() -> None:
    schema = schema_of({"name": "value", "type": "number", "required": True})

    assert validate_rows(schema, [{"value": 0}]) == []  # FR-2.3


def test_an_empty_string_is_not_mistaken_for_a_missing_one() -> None:
    schema = schema_of({"name": "note", "type": "string", "required": True})

    assert validate_rows(schema, [{"note": ""}]) == []  # FR-2.3


# ----------------------------------------------------------------------
# Type mismatch, one per registered type (FR-2.4)
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("type_name", "value", "actual"),
    [
        ("string", 1000, "number"),
        ("string", True, "boolean"),
        ("number", "1000", "string"),
        ("number", True, "boolean"),
        ("integer", 1.5, "number"),
        ("integer", "1000", "string"),
        ("integer", True, "boolean"),
        ("boolean", 1, "number"),
        ("boolean", "true", "string"),
    ],
)
def test_type_mismatch_per_type(type_name: str, value: Any, actual: str) -> None:
    schema = schema_of({"name": "value", "type": type_name})

    issues = validate_rows(schema, [{"value": value}])

    assert codes(issues) == [ErrorCode.TYPE_MISMATCH]  # FR-2.4
    assert issues[0].expected == type_name  # FR-2.4
    assert issues[0].actual == actual  # FR-2.4


def test_a_numeric_string_is_not_coerced() -> None:
    """The trap this engine exists for: Pydantic would make "1000" into 1000."""
    schema = schema_of({"name": "amount", "type": "number"})

    issues = validate_rows(schema, [{"amount": "1000"}])

    assert codes(issues) == [ErrorCode.TYPE_MISMATCH]  # FR-2.4
    assert issues[0].expected == "number"
    assert issues[0].actual == "string"


def test_true_does_not_satisfy_a_number_field() -> None:
    """FR-1.10 at row level: isinstance(True, int) is True in Python."""
    schema = schema_of({"name": "amount", "type": "number"})

    issues = validate_rows(schema, [{"amount": True}])

    assert codes(issues) == [ErrorCode.TYPE_MISMATCH]  # FR-2.4
    assert issues[0].actual == "boolean"


def test_a_whole_float_does_not_satisfy_an_integer_field() -> None:
    schema = schema_of({"name": "count", "type": "integer"})

    assert codes(validate_rows(schema, [{"count": 5.0}])) == [
        ErrorCode.TYPE_MISMATCH
    ]  # FR-2.4


def test_an_int_satisfies_a_number_field() -> None:
    """number accepts int and float; only the reverse is narrower."""
    schema = schema_of({"name": "amount", "type": "number"})

    assert validate_rows(schema, [{"amount": 1000}]) == []  # FR-2.4


def test_a_value_outside_the_type_system_reports_no_actual() -> None:
    """A nested array has no name in our vocabulary, so `actual` is omitted
    rather than invented."""
    schema = schema_of({"name": "tags", "type": "string"})

    issues = validate_rows(schema, [{"tags": ["a", "b"]}])

    assert codes(issues) == [ErrorCode.TYPE_MISMATCH]  # FR-2.4
    assert issues[0].actual is None
    assert "actual" not in issues[0].to_dict()


def test_an_int_against_a_string_field_reports_number_not_integer() -> None:
    """The declaration-order tie-break, at the only place it is observable."""
    schema = schema_of({"name": "tradeId", "type": "string"})

    issues = validate_rows(schema, [{"tradeId": 5}])

    assert issues[0].actual == "number"  # FR-2.4


# ----------------------------------------------------------------------
# Unknown fields (FR-2.5)
# ----------------------------------------------------------------------


def test_a_field_not_in_the_schema_is_rejected() -> None:
    row = {"tradeId": "T001", "amount": 1000, "currency": "USD"}

    issues = validate_rows(trade_schema(), [row])

    assert codes(issues) == [ErrorCode.UNKNOWN_FIELD]  # FR-2.5
    assert issues[0].field == "currency"
    assert issues[0].row == 0


def test_every_unknown_field_in_a_row_is_reported() -> None:
    row = {"tradeId": "T001", "amount": 1000, "currency": "USD", "desk": "LDN"}

    issues = validate_rows(trade_schema(), [row])

    assert codes(issues) == [
        ErrorCode.UNKNOWN_FIELD,
        ErrorCode.UNKNOWN_FIELD,
    ]  # FR-2.5
    assert [issue.field for issue in issues] == ["currency", "desk"]


def test_field_names_are_case_sensitive() -> None:
    """`TradeId` is not `tradeId`: one unknown field and one missing required."""
    issues = validate_rows(trade_schema(), [{"TradeId": "T001", "amount": 1000}])

    assert set(codes(issues)) == {
        ErrorCode.MISSING_REQUIRED_FIELD,
        ErrorCode.UNKNOWN_FIELD,
    }  # FR-2.5


def test_an_unknown_field_holding_null_is_still_unknown() -> None:
    """Being null does not excuse a key the schema never declared."""
    row = {"tradeId": "T001", "amount": 1000, "currency": None}

    assert codes(validate_rows(trade_schema(), [row])) == [
        ErrorCode.UNKNOWN_FIELD
    ]  # FR-2.5


# ----------------------------------------------------------------------
# Every issue is collected (FR-2.9)
# ----------------------------------------------------------------------


def test_issues_are_collected_across_every_row_not_just_the_first() -> None:
    rows = [
        {"tradeId": "T001", "amount": "1000"},
        {"amount": 2000},
        {"tradeId": "T003", "amount": 3000, "currency": "USD"},
    ]

    issues = validate_rows(trade_schema(), rows)

    assert [issue.row for issue in issues] == [0, 1, 2]  # FR-2.9
    assert codes(issues) == [
        ErrorCode.TYPE_MISMATCH,
        ErrorCode.MISSING_REQUIRED_FIELD,
        ErrorCode.UNKNOWN_FIELD,
    ]


def test_several_issues_in_one_row_are_all_reported() -> None:
    rows = [{"amount": "oops", "currency": "USD"}]

    issues = validate_rows(trade_schema(), rows)

    assert codes(issues) == [
        ErrorCode.MISSING_REQUIRED_FIELD,
        ErrorCode.TYPE_MISMATCH,
        ErrorCode.UNKNOWN_FIELD,
    ]  # FR-2.9
    assert {issue.row for issue in issues} == {0}


def test_a_valid_row_between_two_bad_ones_produces_no_issues() -> None:
    rows = [{"amount": 1}, VALID_ROW, {"amount": 2}]

    issues = validate_rows(trade_schema(), rows)

    assert [issue.row for issue in issues] == [0, 2]  # FR-2.9


def test_row_indexes_are_zero_based() -> None:
    issues = validate_rows(trade_schema(), [VALID_ROW, {"amount": 1}])

    assert issues[0].row == 1  # FR-2.9


def test_the_fr_2_message_counts_rows_not_issues(repo: InMemoryRepository) -> None:
    """The example says "3 of 5 rows failed"; a row with three bad fields is one
    failed row."""
    rows = [
        VALID_ROW,
        {"amount": "oops", "currency": "USD"},
        VALID_ROW,
        {"tradeId": None, "amount": 1, "desk": "LDN"},
        {"tradeId": "T005", "amount": True},
    ]

    with pytest.raises(ValidationFailed) as excinfo:
        ingest_rows(ingest(rows), repo)

    assert excinfo.value.message == (
        "3 of 5 rows failed validation; no rows were ingested"
    )  # FR-2.9
    assert len(excinfo.value.details) > 3


# ----------------------------------------------------------------------
# All-or-nothing (FR-2.8)
# ----------------------------------------------------------------------


def test_one_bad_row_stores_nothing(repo: InMemoryRepository) -> None:
    """FR-2.8, DECISION-1: the whole batch is rejected."""
    rows = [VALID_ROW, {"tradeId": "T002", "amount": "oops"}]

    with pytest.raises(ValidationFailed) as excinfo:
        ingest_rows(ingest(rows), repo)

    assert excinfo.value.status_code == 422  # NFR-6
    assert repo.get_rows("trade") == []  # FR-2.8
    assert repo.count_rows("trade") == 0


def test_a_failed_batch_leaves_earlier_batches_intact(repo: InMemoryRepository) -> None:
    """Rejecting a batch must not roll back what was already ingested."""
    ingest_rows(ingest([VALID_ROW]), repo)

    with pytest.raises(ValidationFailed):
        ingest_rows(ingest([{"tradeId": "T002", "amount": "oops"}]), repo)

    assert repo.get_rows("trade") == [VALID_ROW]  # FR-2.8


def test_the_last_row_being_bad_still_rejects_the_batch(repo: InMemoryRepository) -> None:
    """Nothing is written until the whole batch has passed."""
    rows = [VALID_ROW, VALID_ROW, {"amount": 1}]

    with pytest.raises(ValidationFailed):
        ingest_rows(ingest(rows), repo)

    assert repo.count_rows("trade") == 0  # FR-2.8


def test_ingestion_does_not_mutate_the_submitted_rows(repo: InMemoryRepository) -> None:
    """Stripping nulls must not edit the caller's payload in place."""
    row = {"tradeId": "T001", "amount": 1000, "status": None}
    payload = ingest([row])

    ingest_rows(payload, repo)

    assert payload.rows[0] == {"tradeId": "T001", "amount": 1000, "status": None}


# ----------------------------------------------------------------------
# The envelope and the schema binding (FR-2.1, FR-2.2)
# ----------------------------------------------------------------------


def test_unknown_schema_is_rejected(repo: InMemoryRepository) -> None:
    with pytest.raises(UnknownSchema) as excinfo:
        ingest_rows(ingest([VALID_ROW], name="nope"), repo)

    assert excinfo.value.status_code == 404  # FR-2.1, NFR-6
    assert excinfo.value.code is ErrorCode.UNKNOWN_SCHEMA


def test_unknown_schema_is_checked_before_the_rows(repo: InMemoryRepository) -> None:
    """There is nothing to validate rows against, so this cannot be a 422."""
    with pytest.raises(UnknownSchema):
        ingest_rows(ingest([{"anything": "at all"}], name="nope"), repo)


def test_empty_rows_array_is_rejected_by_the_envelope() -> None:
    with pytest.raises(ValidationError):
        IngestRequest.model_validate({"schema": "trade", "rows": []})  # FR-2.2


def test_a_row_that_is_not_an_object_is_rejected_by_the_envelope() -> None:
    with pytest.raises(ValidationError):
        IngestRequest.model_validate({"schema": "trade", "rows": ["T001"]})  # FR-2.2


def test_the_envelope_does_not_touch_row_values() -> None:
    """The whole reason rows are dict[str, Any]: values arrive unchanged."""
    payload = IngestRequest.model_validate(
        {"schema": "trade", "rows": [{"amount": "1000", "flag": True, "n": 1.0}]}
    )

    assert payload.rows[0]["amount"] == "1000"  # FR-2.4
    assert isinstance(payload.rows[0]["amount"], str)
    assert payload.rows[0]["flag"] is True
    assert isinstance(payload.rows[0]["n"], float)


def test_rows_are_validated_against_the_named_schema_only() -> None:
    """Two schemas, one repository: the binding decides which rules apply."""
    repository = InMemoryRepository()
    register_schema(SchemaRequest.model_validate(TRADE_SCHEMA), repository)
    register_schema(
        SchemaRequest.model_validate(
            {
                "name": "customer",
                "fields": [{"name": "customerId", "type": "string", "required": True}],
            }
        ),
        repository,
    )

    ingest_rows(ingest([{"customerId": "C001"}], name="customer"), repository)

    with pytest.raises(ValidationFailed):
        ingest_rows(ingest([{"customerId": "C001"}], name="trade"), repository)

    assert repository.count_rows("customer") == 1  # FR-2.1
    assert repository.count_rows("trade") == 0
