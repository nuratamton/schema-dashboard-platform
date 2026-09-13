"""T5 -- schema registration. FR-1.1-FR-1.8.

Must include: `required` defaults to False when omitted (FR-1.5).
Must include: duplicate schema name -> 409 (FR-1.8).

Cases are transcribed from REQUIREMENTS.md FR-1, not read off the
implementation. The payloads use the brief's own `trade` example so that what is
being asserted is recognisable -- domain names are fine here, they are banned
only in backend/ (RULE-0).
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from backend.core.errors import (
    DuplicateName,
    ErrorCode,
    ValidationFailed,
)
from backend.core.models import FieldDefinition, SchemaRequest
from backend.core.validation import register_schema, validate_schema_definition
from backend.store.memory import InMemoryRepository


@pytest.fixture()
def repo() -> InMemoryRepository:
    """A fresh repository per test -- register_schema takes it as a parameter."""
    return InMemoryRepository()


def schema(**overrides: Any) -> SchemaRequest:
    """The brief's FR-1 example payload, with overrides."""
    payload: dict[str, Any] = {
        "name": "trade",
        "fields": [
            {"name": "tradeId", "type": "string", "required": True},
            {"name": "amount", "type": "number", "required": True, "aggregation": "sum"},
            {"name": "status", "type": "string"},
        ],
    }
    payload.update(overrides)
    return SchemaRequest.model_validate(payload)


def codes(error: ValidationFailed) -> list[ErrorCode]:
    return [issue.code for issue in error.details]


# ----------------------------------------------------------------------
# The envelope (FR-1.2, FR-1.5, FR-1.6)
# ----------------------------------------------------------------------


def test_the_brief_example_schema_is_accepted(repo: InMemoryRepository) -> None:
    register_schema(schema(), repo)

    assert repo.has_schema("trade") is True  # FR-1.9
    assert repo.list_schemas() == ["trade"]


def test_required_defaults_to_false_when_omitted() -> None:
    """The `status` field of the brief's example omits `required`."""
    field = FieldDefinition.model_validate({"name": "status", "type": "string"})

    assert field.required is False  # FR-1.5


def test_required_is_honoured_when_given() -> None:
    field = FieldDefinition.model_validate(
        {"name": "tradeId", "type": "string", "required": True}
    )

    assert field.required is True  # FR-1.5


def test_aggregation_defaults_to_none_when_omitted() -> None:
    """FR-1.6 makes it optional; FR-3.7 treats its absence as "no default"."""
    field = FieldDefinition.model_validate({"name": "status", "type": "string"})

    assert field.aggregation is None  # FR-1.6


def test_empty_fields_array_is_rejected_by_the_envelope() -> None:
    with pytest.raises(ValidationError):
        SchemaRequest.model_validate({"name": "trade", "fields": []})  # FR-1.2


def test_missing_fields_key_is_rejected_by_the_envelope() -> None:
    with pytest.raises(ValidationError):
        SchemaRequest.model_validate({"name": "trade"})  # FR-1.2


@pytest.mark.parametrize("required", [1, 0, "true", "false", None])
def test_non_boolean_required_is_rejected(required: Any) -> None:
    """Same posture the type registry takes to row values: 1 is not a boolean."""
    with pytest.raises(ValidationError):
        FieldDefinition.model_validate(
            {"name": "amount", "type": "number", "required": required}
        )  # FR-1.5


def test_a_misspelled_key_is_rejected_rather_than_dropped() -> None:
    """"agg" silently ignored would leave the field with no aggregation and
    surface as a confusing FR-3.7 failure much later."""
    with pytest.raises(ValidationError):
        FieldDefinition.model_validate(
            {"name": "amount", "type": "number", "agg": "sum"}
        )


# ----------------------------------------------------------------------
# Unique field names (FR-1.3)
# ----------------------------------------------------------------------


def test_duplicate_field_name_is_rejected(repo: InMemoryRepository) -> None:
    payload = schema(
        fields=[
            {"name": "tradeId", "type": "string"},
            {"name": "tradeId", "type": "number"},
        ]
    )

    with pytest.raises(ValidationFailed) as excinfo:
        register_schema(payload, repo)

    assert codes(excinfo.value) == [ErrorCode.DUPLICATE_NAME]  # FR-1.3
    assert excinfo.value.details[0].field == "tradeId"
    assert excinfo.value.status_code == 422  # NFR-6


def test_a_field_name_repeated_three_times_reports_both_repeats(
    repo: InMemoryRepository,
) -> None:
    payload = schema(
        fields=[
            {"name": "tradeId", "type": "string"},
            {"name": "tradeId", "type": "string"},
            {"name": "tradeId", "type": "string"},
        ]
    )

    with pytest.raises(ValidationFailed) as excinfo:
        register_schema(payload, repo)

    assert codes(excinfo.value) == [
        ErrorCode.DUPLICATE_NAME,
        ErrorCode.DUPLICATE_NAME,
    ]  # FR-1.3


def test_distinct_field_names_are_accepted(repo: InMemoryRepository) -> None:
    register_schema(schema(), repo)  # FR-1.3

    assert repo.has_schema("trade") is True


# ----------------------------------------------------------------------
# Known types (FR-1.4)
# ----------------------------------------------------------------------


def test_unknown_type_is_rejected(repo: InMemoryRepository) -> None:
    payload = schema(fields=[{"name": "settledOn", "type": "date"}])

    with pytest.raises(ValidationFailed) as excinfo:
        register_schema(payload, repo)

    issue = excinfo.value.details[0]
    assert issue.code is ErrorCode.UNKNOWN_TYPE  # FR-1.4
    assert issue.field == "settledOn"
    assert issue.actual == "date"


def test_unknown_type_names_the_supported_types(repo: InMemoryRepository) -> None:
    """FR-1.4 requires the rejection to name what is supported."""
    payload = schema(fields=[{"name": "settledOn", "type": "date"}])

    with pytest.raises(ValidationFailed) as excinfo:
        register_schema(payload, repo)

    expected = excinfo.value.details[0].expected
    assert expected is not None
    for type_name in ("string", "number", "integer", "boolean"):
        assert type_name in expected  # FR-1.4


@pytest.mark.parametrize("type_name", ["string", "number", "integer", "boolean"])
def test_every_registered_type_is_accepted(
    type_name: str, repo: InMemoryRepository
) -> None:
    register_schema(schema(fields=[{"name": "value", "type": type_name}]), repo)  # FR-1.4

    assert repo.has_schema("trade") is True


def test_type_names_are_case_sensitive(repo: InMemoryRepository) -> None:
    payload = schema(fields=[{"name": "amount", "type": "Number"}])

    with pytest.raises(ValidationFailed) as excinfo:
        register_schema(payload, repo)

    assert codes(excinfo.value) == [ErrorCode.UNKNOWN_TYPE]  # FR-1.4


# ----------------------------------------------------------------------
# Aggregation legality (FR-1.6, FR-1.7)
# ----------------------------------------------------------------------


def test_unknown_aggregation_is_rejected(repo: InMemoryRepository) -> None:
    payload = schema(
        fields=[{"name": "amount", "type": "number", "aggregation": "median"}]
    )

    with pytest.raises(ValidationFailed) as excinfo:
        register_schema(payload, repo)

    issue = excinfo.value.details[0]
    assert issue.code is ErrorCode.UNKNOWN_AGGREGATION  # FR-1.7
    assert issue.actual == "median"
    assert issue.expected is not None and "sum" in issue.expected


def test_aggregation_illegal_for_the_field_type_is_rejected(
    repo: InMemoryRepository,
) -> None:
    """The FR-1.7 example verbatim: "aggregation": "sum" on a string field."""
    payload = schema(fields=[{"name": "status", "type": "string", "aggregation": "sum"}])

    with pytest.raises(ValidationFailed) as excinfo:
        register_schema(payload, repo)

    issue = excinfo.value.details[0]
    assert issue.code is ErrorCode.INVALID_AGGREGATION  # FR-1.7
    assert issue.field == "status"
    assert issue.actual == "string"


def test_unknown_and_illegal_aggregations_get_different_codes(
    repo: InMemoryRepository,
) -> None:
    """"No such aggregation" and "not on this field" are different fixes."""
    unknown = schema(
        fields=[{"name": "amount", "type": "number", "aggregation": "median"}]
    )
    illegal = schema(
        fields=[{"name": "status", "type": "string", "aggregation": "sum"}]
    )

    with pytest.raises(ValidationFailed) as first:
        register_schema(unknown, repo)
    with pytest.raises(ValidationFailed) as second:
        register_schema(illegal, repo)

    assert codes(first.value) != codes(second.value)  # FR-1.7


@pytest.mark.parametrize("aggregation", ["sum", "avg", "min", "max", "count"])
@pytest.mark.parametrize("type_name", ["number", "integer"])
def test_every_aggregation_is_legal_on_numeric_fields(
    aggregation: str, type_name: str, repo: InMemoryRepository
) -> None:
    payload = schema(
        fields=[{"name": "value", "type": type_name, "aggregation": aggregation}]
    )
    register_schema(payload, repo)  # FR-1.7

    assert repo.has_schema("trade") is True


@pytest.mark.parametrize("type_name", ["string", "boolean"])
def test_count_is_legal_on_non_numeric_fields(
    type_name: str, repo: InMemoryRepository
) -> None:
    payload = schema(fields=[{"name": "value", "type": type_name, "aggregation": "count"}])
    register_schema(payload, repo)  # FR-1.7

    assert repo.has_schema("trade") is True


def test_a_field_with_no_aggregation_is_accepted(repo: InMemoryRepository) -> None:
    """FR-1.6 is optional; most fields never declare one."""
    register_schema(schema(fields=[{"name": "status", "type": "string"}]), repo)  # FR-1.6

    assert repo.has_schema("trade") is True


def test_an_unknown_type_with_an_aggregation_does_not_crash(
    repo: InMemoryRepository,
) -> None:
    """is_legal_for raises KeyError on an unregistered type (DECISION-12), so
    legality must not be asked once the type is already known to be bad. Only
    UNKNOWN_TYPE is reported: fix the type and the aggregation may be fine."""
    payload = schema(
        fields=[{"name": "settledOn", "type": "date", "aggregation": "sum"}]
    )

    with pytest.raises(ValidationFailed) as excinfo:
        register_schema(payload, repo)

    assert codes(excinfo.value) == [ErrorCode.UNKNOWN_TYPE]  # FR-1.4


def test_an_unknown_type_with_an_unknown_aggregation_reports_both(
    repo: InMemoryRepository,
) -> None:
    """Neither check depends on the other, so both are reported."""
    payload = schema(
        fields=[{"name": "settledOn", "type": "date", "aggregation": "median"}]
    )

    with pytest.raises(ValidationFailed) as excinfo:
        register_schema(payload, repo)

    assert codes(excinfo.value) == [
        ErrorCode.UNKNOWN_TYPE,
        ErrorCode.UNKNOWN_AGGREGATION,
    ]


# ----------------------------------------------------------------------
# Every issue is collected (FR-1.3, FR-1.4, FR-1.7 together)
# ----------------------------------------------------------------------


def test_a_schema_with_several_distinct_problems_reports_all_of_them(
    repo: InMemoryRepository,
) -> None:
    """Three separate mistakes should take one round trip to fix, not three."""
    payload = schema(
        fields=[
            {"name": "tradeId", "type": "string"},
            {"name": "tradeId", "type": "string"},  # FR-1.3 duplicate
            {"name": "settledOn", "type": "date"},  # FR-1.4 unknown type
            {"name": "status", "type": "string", "aggregation": "sum"},  # FR-1.7 illegal
            {"name": "book", "type": "string", "aggregation": "median"},  # FR-1.7 unknown
        ]
    )

    with pytest.raises(ValidationFailed) as excinfo:
        register_schema(payload, repo)

    assert codes(excinfo.value) == [
        ErrorCode.DUPLICATE_NAME,
        ErrorCode.UNKNOWN_TYPE,
        ErrorCode.INVALID_AGGREGATION,
        ErrorCode.UNKNOWN_AGGREGATION,
    ]
    assert [issue.field for issue in excinfo.value.details] == [
        "tradeId",
        "settledOn",
        "status",
        "book",
    ]


def test_validation_issues_carry_no_row_key() -> None:
    """There are no rows at registration time; the key is omitted, not null."""
    payload = schema(fields=[{"name": "settledOn", "type": "date"}])

    issues = validate_schema_definition(payload)

    assert all(issue.row is None for issue in issues)
    assert all("row" not in issue.to_dict() for issue in issues)  # DECISION-10


def test_a_valid_schema_produces_no_issues() -> None:
    assert validate_schema_definition(schema()) == []


def test_nothing_is_stored_when_validation_fails(repo: InMemoryRepository) -> None:
    payload = schema(fields=[{"name": "settledOn", "type": "date"}])

    with pytest.raises(ValidationFailed):
        register_schema(payload, repo)

    assert repo.has_schema("trade") is False  # FR-1.9
    assert repo.list_schemas() == []


# ----------------------------------------------------------------------
# Unique schema name (FR-1.1, FR-1.8)
# ----------------------------------------------------------------------


def test_duplicate_schema_name_is_rejected(repo: InMemoryRepository) -> None:
    register_schema(schema(), repo)

    with pytest.raises(DuplicateName) as excinfo:
        register_schema(schema(), repo)

    assert excinfo.value.status_code == 409  # FR-1.8, NFR-6
    assert excinfo.value.code is ErrorCode.DUPLICATE_NAME
    assert "trade" in excinfo.value.message


def test_duplicate_schema_name_does_not_overwrite_the_original(
    repo: InMemoryRepository,
) -> None:
    """The store overwrites silently by design (DECISION-7); the guard is here."""
    register_schema(schema(), repo)
    replacement = schema(fields=[{"name": "somethingElse", "type": "boolean"}])

    with pytest.raises(DuplicateName):
        register_schema(replacement, repo)

    stored = repo.get_schema("trade")
    assert [field.name for field in stored.fields] == ["tradeId", "amount", "status"]


def test_duplicate_name_is_refused_before_the_body_is_validated(
    repo: InMemoryRepository,
) -> None:
    """Re-registration is refused whatever the body says (DECISION-16)."""
    register_schema(schema(), repo)
    invalid_replacement = schema(fields=[{"name": "x", "type": "date"}])

    with pytest.raises(DuplicateName):
        register_schema(invalid_replacement, repo)


def test_different_schema_names_coexist(repo: InMemoryRepository) -> None:
    """The premise of the platform: concurrent, unrelated use cases (FR-1.1)."""
    register_schema(schema(), repo)
    register_schema(
        schema(
            name="customer",
            fields=[
                {"name": "customerId", "type": "string", "required": True},
                {"name": "country", "type": "string"},
            ],
        ),
        repo,
    )

    assert repo.list_schemas() == ["trade", "customer"]  # FR-1.1


def test_the_repository_is_a_parameter_not_a_singleton() -> None:
    """Two repositories, same schema name, no interference (NFR-4)."""
    first, second = InMemoryRepository(), InMemoryRepository()

    register_schema(schema(), first)
    register_schema(schema(), second)  # would be a 409 against a shared store

    assert first.list_schemas() == ["trade"]
    assert second.list_schemas() == ["trade"]


# ----------------------------------------------------------------------
# Names that cannot round-trip (FR-1.1, DECISION-35)
# ----------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["a/b", "/x", "x/", "   ", "\t"])
def test_an_unusable_schema_name_is_rejected(bad: str, repo: InMemoryRepository) -> None:
    """`GET /schema/{name}` cannot fetch a name containing `/`, and a
    whitespace-only name is not a name."""
    with pytest.raises(ValidationFailed) as excinfo:
        register_schema(schema(name=bad), repo)

    assert ErrorCode.INVALID_NAME in codes(excinfo.value)  # FR-1.1
    assert repo.list_schemas() == []


@pytest.mark.parametrize("ok", ["trade", "trade book", "trade-book", "t.b_1"])
def test_ordinary_schema_names_are_accepted(ok: str, repo: InMemoryRepository) -> None:
    register_schema(schema(name=ok), repo)

    assert repo.list_schemas() == [ok]  # FR-1.1
