"""T8 -- config validation at registration time. FR-3.1-FR-3.11.

Must include: a config naming a nonexistent field is rejected by POST /dashboard,
not later by GET (FR-3.5).
Must include: the aggregation precedence chain (FR-3.7).

Cases are transcribed from REQUIREMENTS.md FR-3, not read off the
implementation. Domain names are fine here; they are banned only in backend/
(RULE-0).
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError as PydanticValidationError

from backend.core.dashboards import (
    register_dashboard,
    resolve_schema,
    validate_dashboard_config,
)
from backend.core.errors import (
    AmbiguousSchema,
    DuplicateName,
    ErrorCode,
    NoSchemaRegistered,
    UnknownSchema,
    ValidationFailed,
)
from backend.core.models import DashboardRequest, SchemaRequest
from backend.core.validation import register_schema
from backend.store.memory import InMemoryRepository

TRADE_SCHEMA: dict[str, Any] = {
    "name": "trade",
    "fields": [
        {"name": "tradeId", "type": "string", "required": True},
        {"name": "amount", "type": "number", "required": True, "aggregation": "sum"},
        {"name": "status", "type": "string"},
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

#: The FR-3 example config, including the `schema` key this project adds (D-3).
TRADE_DASHBOARD: dict[str, Any] = {
    "name": "trade-dashboard",
    "schema": "trade",
    "views": [
        {"type": "summary", "field": "amount", "aggregation": "sum"},
        {"type": "table", "columns": ["tradeId", "amount", "status"]},
    ],
}


@pytest.fixture()
def repo() -> InMemoryRepository:
    """One registered schema, so an omitted binding is inferable."""
    repository = InMemoryRepository()
    register_schema(SchemaRequest.model_validate(TRADE_SCHEMA), repository)
    return repository


@pytest.fixture()
def two_schemas() -> InMemoryRepository:
    repository = InMemoryRepository()
    register_schema(SchemaRequest.model_validate(TRADE_SCHEMA), repository)
    register_schema(SchemaRequest.model_validate(CUSTOMER_SCHEMA), repository)
    return repository


def dashboard(**overrides: Any) -> DashboardRequest:
    payload = dict(TRADE_DASHBOARD)
    payload.update(overrides)
    return DashboardRequest.model_validate(payload)


def config_of(*view_configs: dict[str, Any], **overrides: Any) -> DashboardRequest:
    """A config with the given views, bound to `trade` unless overridden."""
    return dashboard(views=list(view_configs), **overrides)


def codes(error: ValidationFailed) -> list[ErrorCode]:
    return [issue.code for issue in error.details]


def fields(error: ValidationFailed) -> list[str | None]:
    return [issue.field for issue in error.details]


# ======================================================================
# FR-3.5 -- the requirement this task exists for
# ======================================================================


def test_a_config_naming_a_nonexistent_field_is_rejected_at_registration(
    repo: InMemoryRepository,
) -> None:
    """THE test. A broken config is refused when it is written, not when
    someone opens the dashboard (FR-3.5)."""
    payload = config_of({"type": "summary", "field": "notional", "aggregation": "sum"})

    with pytest.raises(ValidationFailed) as excinfo:
        register_dashboard(payload, repo)

    assert codes(excinfo.value) == [ErrorCode.UNKNOWN_FIELD]  # FR-3.6
    assert excinfo.value.status_code == 422  # NFR-6


def test_a_rejected_config_is_not_stored(repo: InMemoryRepository) -> None:
    """Nothing reaches GET, because nothing was written (FR-3.5)."""
    payload = config_of({"type": "summary", "field": "notional", "aggregation": "sum"})

    with pytest.raises(ValidationFailed):
        register_dashboard(payload, repo)

    assert repo.has_dashboard("trade-dashboard") is False  # FR-3.5
    assert repo.list_dashboards() == []
    assert repo.get_dashboard("trade-dashboard") is None


def test_a_config_is_validated_against_an_empty_dataset(repo: InMemoryRepository) -> None:
    """Registration-time means before any rows exist -- the schema is enough."""
    assert repo.count_rows("trade") == 0

    register_dashboard(dashboard(), repo)  # FR-3.5

    assert repo.has_dashboard("trade-dashboard") is True


def test_every_stored_config_is_renderable(repo: InMemoryRepository) -> None:
    """The property FR-3.5 buys: if it is in the store, it passed every check."""
    register_dashboard(dashboard(), repo)

    stored = repo.get_dashboard("trade-dashboard")
    schema = repo.get_schema(stored.schema_name)

    assert validate_dashboard_config(stored, schema) == []  # FR-3.5


# ======================================================================
# Schema resolution (FR-3.2, as amended by DECISION-22)
# ======================================================================


def test_an_explicit_known_schema_is_used(repo: InMemoryRepository) -> None:
    stored = register_dashboard(dashboard(), repo)

    assert stored.schema_name == "trade"  # FR-3.2


def test_an_explicit_unknown_schema_is_a_404(repo: InMemoryRepository) -> None:
    with pytest.raises(UnknownSchema) as excinfo:
        register_dashboard(dashboard(schema="nope"), repo)

    assert excinfo.value.status_code == 404  # FR-3.2, NFR-6
    assert excinfo.value.code is ErrorCode.UNKNOWN_SCHEMA


def test_an_omitted_schema_is_inferred_when_exactly_one_is_registered(
    repo: InMemoryRepository,
) -> None:
    payload = DashboardRequest.model_validate(
        {"name": "d", "views": [{"type": "summary", "field": "amount"}]}
    )

    assert resolve_schema(payload, repo).name == "trade"  # FR-3.2


def test_the_briefs_own_example_config_works_verbatim(repo: InMemoryRepository) -> None:
    """The brief's config carries no schema binding at all. With one schema
    registered it is unambiguous, so it registers as written (DECISION-22)."""
    payload = DashboardRequest.model_validate(
        {
            "name": "trade-dashboard",
            "views": [
                {"type": "summary", "field": "amount", "aggregation": "sum"},
                {"type": "table", "columns": ["tradeId", "amount", "status"]},
            ],
        }
    )

    stored = register_dashboard(payload, repo)

    assert stored.schema_name == "trade"  # FR-3.2
    assert repo.has_dashboard("trade-dashboard") is True


def test_an_omitted_schema_is_ambiguous_when_several_are_registered(
    two_schemas: InMemoryRepository,
) -> None:
    payload = DashboardRequest.model_validate(
        {"name": "d", "views": [{"type": "summary", "field": "amount"}]}
    )

    with pytest.raises(AmbiguousSchema) as excinfo:
        register_dashboard(payload, two_schemas)

    assert excinfo.value.status_code == 422  # FR-3.2, NFR-6
    assert excinfo.value.code is ErrorCode.AMBIGUOUS_SCHEMA


def test_an_ambiguous_binding_names_the_candidates(
    two_schemas: InMemoryRepository,
) -> None:
    """FR-3.2: the caller has to be able to pick one."""
    payload = DashboardRequest.model_validate({"name": "d", "views": []})

    with pytest.raises(AmbiguousSchema) as excinfo:
        register_dashboard(payload, two_schemas)

    assert excinfo.value.candidates == ["trade", "customer"]
    assert "trade" in excinfo.value.message  # FR-3.2
    assert "customer" in excinfo.value.message


def test_an_explicit_binding_is_never_ambiguous(
    two_schemas: InMemoryRepository,
) -> None:
    """Two schemas registered, one named: the whole point of the schema key."""
    stored = register_dashboard(dashboard(), two_schemas)

    assert stored.schema_name == "trade"  # FR-3.2


def test_an_omitted_schema_with_none_registered_is_its_own_failure() -> None:
    """Not ambiguity -- there is nothing to be ambiguous between (DECISION-33).

    Reachable the first time anyone posts a dashboard before posting a schema,
    which the UI's panel ordering makes easy to do out of order.
    """
    payload = DashboardRequest.model_validate({"name": "d", "views": []})

    with pytest.raises(NoSchemaRegistered) as excinfo:
        register_dashboard(payload, InMemoryRepository())

    assert excinfo.value.status_code == 422  # FR-3.2, NFR-6
    assert excinfo.value.code is ErrorCode.NO_SCHEMA_REGISTERED


def test_no_schema_registered_is_not_reported_as_ambiguous() -> None:
    """The distinction is the point: the two failures have different fixes."""
    payload = DashboardRequest.model_validate({"name": "d", "views": []})

    with pytest.raises(NoSchemaRegistered) as excinfo:
        register_dashboard(payload, InMemoryRepository())

    assert not isinstance(excinfo.value, AmbiguousSchema)  # FR-3.2
    assert excinfo.value.code is not ErrorCode.AMBIGUOUS_SCHEMA


def test_no_schema_registered_says_what_to_do_next() -> None:
    """Naming candidates is meaningless here; telling the caller to register a
    schema is the actionable message."""
    payload = DashboardRequest.model_validate({"name": "d", "views": []})

    with pytest.raises(NoSchemaRegistered) as excinfo:
        register_dashboard(payload, InMemoryRepository())

    assert "no schemas are registered" in excinfo.value.message  # FR-3.2
    assert "register a schema first" in excinfo.value.message
    assert excinfo.value.to_response()["details"] == []


def test_registering_one_schema_resolves_the_no_schema_failure() -> None:
    """The boundary: zero is NO_SCHEMA_REGISTERED, one infers cleanly."""
    repository = InMemoryRepository()
    payload = DashboardRequest.model_validate(
        {"name": "d", "views": [{"type": "table", "columns": ["tradeId"]}]}
    )

    with pytest.raises(NoSchemaRegistered):
        register_dashboard(payload, repository)

    register_schema(SchemaRequest.model_validate(TRADE_SCHEMA), repository)

    assert register_dashboard(payload, repository).schema_name == "trade"  # FR-3.2


def test_an_explicit_schema_with_none_registered_is_still_a_404() -> None:
    """Naming a schema that does not exist is unchanged by DECISION-33 -- the
    caller asked for a specific resource and it is absent."""
    payload = DashboardRequest.model_validate(
        {"name": "d", "schema": "trade", "views": []}
    )

    with pytest.raises(UnknownSchema) as excinfo:
        register_dashboard(payload, InMemoryRepository())

    assert excinfo.value.status_code == 404  # FR-3.2, NFR-6


def test_the_resolved_binding_is_stored_not_the_requested_one(
    repo: InMemoryRepository,
) -> None:
    """An inferred binding is decided once and frozen (DECISION-23)."""
    payload = DashboardRequest.model_validate(
        {"name": "d", "views": [{"type": "summary", "field": "amount"}]}
    )
    assert payload.schema_name is None

    register_dashboard(payload, repo)

    assert repo.get_dashboard("d").schema_name == "trade"  # FR-3.2


def test_an_inferred_binding_survives_a_later_schema_registration(
    repo: InMemoryRepository,
) -> None:
    """Registering a second schema must not change or break an existing
    dashboard that was bound by inference (DECISION-23)."""
    payload = DashboardRequest.model_validate(
        {"name": "d", "views": [{"type": "summary", "field": "amount"}]}
    )
    register_dashboard(payload, repo)

    register_schema(SchemaRequest.model_validate(CUSTOMER_SCHEMA), repo)

    assert repo.get_dashboard("d").schema_name == "trade"  # FR-3.2


def test_views_are_validated_against_the_bound_schema_only(
    two_schemas: InMemoryRepository,
) -> None:
    """`amount` exists in trade and not in customer; the binding decides."""
    payload = config_of(
        {"type": "summary", "field": "amount", "aggregation": "sum"},
        schema="customer",
    )

    with pytest.raises(ValidationFailed) as excinfo:
        register_dashboard(payload, two_schemas)

    assert codes(excinfo.value) == [ErrorCode.UNKNOWN_FIELD]  # FR-3.6


def test_the_schema_is_resolved_before_the_views_are_checked(
    repo: InMemoryRepository,
) -> None:
    """An unknown schema is a 404 even when the views are also broken -- there
    is nothing to validate them against."""
    payload = config_of({"type": "nope"}, schema="missing")

    with pytest.raises(UnknownSchema):
        register_dashboard(payload, repo)


# ======================================================================
# Unique dashboard name (FR-3.1)
# ======================================================================


def test_duplicate_dashboard_name_is_rejected(repo: InMemoryRepository) -> None:
    register_dashboard(dashboard(), repo)

    with pytest.raises(DuplicateName) as excinfo:
        register_dashboard(dashboard(), repo)

    assert excinfo.value.status_code == 409  # FR-3.1, NFR-6
    assert excinfo.value.code is ErrorCode.DUPLICATE_NAME
    assert "trade-dashboard" in excinfo.value.message


def test_duplicate_dashboard_name_does_not_overwrite_the_original(
    repo: InMemoryRepository,
) -> None:
    register_dashboard(dashboard(), repo)

    with pytest.raises(DuplicateName):
        register_dashboard(
            config_of({"type": "table", "columns": ["status"]}), repo
        )

    stored = repo.get_dashboard("trade-dashboard")
    assert len(stored.views) == 2  # FR-3.1


def test_duplicate_name_is_refused_before_the_body_is_validated(
    repo: InMemoryRepository,
) -> None:
    """Re-registration is refused whatever the body says (DECISION-16)."""
    register_dashboard(dashboard(), repo)

    with pytest.raises(DuplicateName):
        register_dashboard(config_of({"type": "summary", "field": "nope"}), repo)


def test_a_dashboard_and_a_schema_may_share_a_name(repo: InMemoryRepository) -> None:
    register_dashboard(dashboard(name="trade"), repo)

    assert repo.has_schema("trade") is True  # FR-3.1
    assert repo.has_dashboard("trade") is True


def test_several_dashboards_coexist(repo: InMemoryRepository) -> None:
    register_dashboard(dashboard(), repo)
    register_dashboard(
        config_of({"type": "table", "columns": ["status"]}, name="status-table"), repo
    )

    assert repo.list_dashboards() == ["trade-dashboard", "status-table"]  # FR-3.11


# ======================================================================
# Views array and view types (FR-3.3, FR-3.4)
# ======================================================================


def test_an_empty_views_array_is_rejected(repo: InMemoryRepository) -> None:
    with pytest.raises(ValidationFailed) as excinfo:
        register_dashboard(config_of(), repo)

    assert codes(excinfo.value) == [ErrorCode.MISSING_REQUIRED_FIELD]  # FR-3.3
    assert fields(excinfo.value) == ["views"]


def test_an_omitted_views_key_is_rejected(repo: InMemoryRepository) -> None:
    """Omitted and empty are one event: no views were given."""
    payload = DashboardRequest.model_validate({"name": "d", "schema": "trade"})

    with pytest.raises(ValidationFailed) as excinfo:
        register_dashboard(payload, repo)

    assert codes(excinfo.value) == [ErrorCode.MISSING_REQUIRED_FIELD]  # FR-3.3


def test_an_unknown_view_type_is_rejected(repo: InMemoryRepository) -> None:
    with pytest.raises(ValidationFailed) as excinfo:
        register_dashboard(config_of({"type": "chart", "field": "amount"}), repo)

    issue = excinfo.value.details[0]
    assert issue.code is ErrorCode.UNKNOWN_TYPE  # FR-3.4
    assert issue.actual == "chart"


def test_an_unknown_view_type_lists_the_supported_types(
    repo: InMemoryRepository,
) -> None:
    """FR-3.4 requires the rejection to list supported view types."""
    with pytest.raises(ValidationFailed) as excinfo:
        register_dashboard(config_of({"type": "chart"}), repo)

    expected = excinfo.value.details[0].expected
    assert expected is not None
    assert "summary" in expected and "table" in expected  # FR-3.4


def test_a_view_without_a_type_key_is_rejected(repo: InMemoryRepository) -> None:
    with pytest.raises(ValidationFailed) as excinfo:
        register_dashboard(config_of({"field": "amount"}), repo)

    assert codes(excinfo.value) == [ErrorCode.MISSING_REQUIRED_FIELD]  # FR-3.4
    assert fields(excinfo.value) == ["views[0].type"]


def test_view_types_are_case_sensitive(repo: InMemoryRepository) -> None:
    with pytest.raises(ValidationFailed) as excinfo:
        register_dashboard(config_of({"type": "Summary", "field": "amount"}), repo)

    assert codes(excinfo.value) == [ErrorCode.UNKNOWN_TYPE]  # FR-3.4


def test_an_unknown_view_type_does_not_also_report_its_contents(
    repo: InMemoryRepository,
) -> None:
    """No handler owns the config, so nothing can judge the rest of it."""
    with pytest.raises(ValidationFailed) as excinfo:
        register_dashboard(config_of({"type": "chart", "field": "notional"}), repo)

    assert codes(excinfo.value) == [ErrorCode.UNKNOWN_TYPE]  # FR-3.4


# ======================================================================
# Delegation to the view handlers (FR-3.6 - FR-3.10)
# ======================================================================


def test_summary_field_must_exist(repo: InMemoryRepository) -> None:
    with pytest.raises(ValidationFailed) as excinfo:
        register_dashboard(
            config_of({"type": "summary", "field": "notional", "aggregation": "sum"}),
            repo,
        )

    assert codes(excinfo.value) == [ErrorCode.UNKNOWN_FIELD]  # FR-3.6


def test_aggregation_falls_back_to_the_schema_default(repo: InMemoryRepository) -> None:
    """FR-3.7 second link: `amount` declares `sum`, so the view need not."""
    register_dashboard(config_of({"type": "summary", "field": "amount"}), repo)

    assert repo.has_dashboard("trade-dashboard") is True  # FR-3.7


def test_aggregation_required_when_neither_source_supplies_one(
    repo: InMemoryRepository,
) -> None:
    """FR-3.7 third link: `status` declares no default."""
    with pytest.raises(ValidationFailed) as excinfo:
        register_dashboard(config_of({"type": "summary", "field": "status"}), repo)

    assert codes(excinfo.value) == [ErrorCode.AGGREGATION_REQUIRED]  # FR-3.7


def test_an_aggregation_illegal_for_the_field_type_is_rejected(
    repo: InMemoryRepository,
) -> None:
    with pytest.raises(ValidationFailed) as excinfo:
        register_dashboard(
            config_of({"type": "summary", "field": "status", "aggregation": "sum"}),
            repo,
        )

    assert codes(excinfo.value) == [ErrorCode.INVALID_AGGREGATION]  # FR-3.8


def test_table_column_must_exist(repo: InMemoryRepository) -> None:
    with pytest.raises(ValidationFailed) as excinfo:
        register_dashboard(
            config_of({"type": "table", "columns": ["tradeId", "currency"]}), repo
        )

    assert codes(excinfo.value) == [ErrorCode.UNKNOWN_FIELD]  # FR-3.9


def test_table_columns_must_be_non_empty(repo: InMemoryRepository) -> None:
    with pytest.raises(ValidationFailed) as excinfo:
        register_dashboard(config_of({"type": "table", "columns": []}), repo)

    assert codes(excinfo.value) == [ErrorCode.MISSING_REQUIRED_FIELD]  # FR-3.10


def test_a_repeated_column_is_rejected(repo: InMemoryRepository) -> None:
    """FR-4.6 wants rows projected to exactly the configured columns, which a
    repeat makes impossible -- an object cannot carry the same key twice."""
    with pytest.raises(ValidationFailed) as excinfo:
        register_dashboard(
            config_of({"type": "table", "columns": ["amount", "tradeId", "amount"]}),
            repo,
        )

    assert codes(excinfo.value) == [ErrorCode.DUPLICATE_NAME]  # FR-4.6
    assert fields(excinfo.value) == ["views[0].amount"]


def test_distinct_columns_are_accepted(repo: InMemoryRepository) -> None:
    register_dashboard(
        config_of({"type": "table", "columns": ["tradeId", "amount", "status"]}), repo
    )

    assert repo.has_dashboard("trade-dashboard") is True  # FR-3.9


# ======================================================================
# Every issue is collected, and located (FR-3.3 - FR-3.10)
# ======================================================================


def test_a_config_with_several_distinct_problems_reports_all_of_them(
    repo: InMemoryRepository,
) -> None:
    """Four mistakes, one round trip to fix."""
    payload = config_of(
        {"type": "summary", "field": "notional", "aggregation": "sum"},
        {"type": "summary", "field": "status"},
        {"type": "chart", "columns": ["amount"]},
        {"type": "table", "columns": ["tradeId", "currency"]},
    )

    with pytest.raises(ValidationFailed) as excinfo:
        register_dashboard(payload, repo)

    assert codes(excinfo.value) == [
        ErrorCode.UNKNOWN_FIELD,
        ErrorCode.AGGREGATION_REQUIRED,
        ErrorCode.UNKNOWN_TYPE,
        ErrorCode.UNKNOWN_FIELD,
    ]


def test_issues_name_the_view_they_came_from(repo: InMemoryRepository) -> None:
    """With several views referencing several fields, an unqualified field name
    is not enough to act on."""
    payload = config_of(
        {"type": "summary", "field": "amount", "aggregation": "sum"},
        {"type": "table", "columns": ["tradeId", "currency"]},
        {"type": "summary", "field": "notional"},
    )

    with pytest.raises(ValidationFailed) as excinfo:
        register_dashboard(payload, repo)

    assert fields(excinfo.value) == ["views[1].currency", "views[2].notional"]


def test_several_problems_in_one_view_are_all_reported(
    repo: InMemoryRepository,
) -> None:
    payload = config_of({"type": "table", "columns": ["currency", "amount", "desk"]})

    with pytest.raises(ValidationFailed) as excinfo:
        register_dashboard(payload, repo)

    assert fields(excinfo.value) == ["views[0].currency", "views[0].desk"]  # FR-3.9


def test_a_valid_view_between_two_broken_ones_reports_nothing(
    repo: InMemoryRepository,
) -> None:
    payload = config_of(
        {"type": "summary", "field": "nope"},
        {"type": "summary", "field": "amount", "aggregation": "sum"},
        {"type": "summary", "field": "alsoNope"},
    )

    with pytest.raises(ValidationFailed) as excinfo:
        register_dashboard(payload, repo)

    assert fields(excinfo.value) == ["views[0].nope", "views[2].alsoNope"]


def test_the_failure_message_counts_problems(repo: InMemoryRepository) -> None:
    payload = config_of(
        {"type": "summary", "field": "nope"},
        {"type": "summary", "field": "alsoNope"},
    )

    with pytest.raises(ValidationFailed) as excinfo:
        register_dashboard(payload, repo)

    assert excinfo.value.message == (
        "2 problems found in dashboard 'trade-dashboard'; "
        "the dashboard was not registered"
    )


def test_a_single_problem_is_reported_in_the_singular(
    repo: InMemoryRepository,
) -> None:
    with pytest.raises(ValidationFailed) as excinfo:
        register_dashboard(config_of({"type": "summary", "field": "nope"}), repo)

    assert "1 problem found" in excinfo.value.message


def test_a_valid_config_produces_no_issues(repo: InMemoryRepository) -> None:
    schema = SchemaRequest.model_validate(TRADE_SCHEMA)

    assert validate_dashboard_config(dashboard(), schema) == []


# ======================================================================
# Storage (FR-3.11)
# ======================================================================


def test_a_valid_config_is_stored(repo: InMemoryRepository) -> None:
    register_dashboard(dashboard(), repo)

    assert repo.has_dashboard("trade-dashboard") is True  # FR-3.11
    assert repo.list_dashboards() == ["trade-dashboard"]


def test_the_stored_config_preserves_view_order(repo: InMemoryRepository) -> None:
    """FR-4.3 will resolve views in declaration order, so order must survive."""
    register_dashboard(dashboard(), repo)

    stored = repo.get_dashboard("trade-dashboard")
    assert [view["type"] for view in stored.views] == ["summary", "table"]


def test_the_repository_is_a_parameter_not_a_singleton() -> None:
    """Two repositories, same dashboard name, no interference (NFR-4)."""
    first, second = InMemoryRepository(), InMemoryRepository()
    for repository in (first, second):
        register_schema(SchemaRequest.model_validate(TRADE_SCHEMA), repository)
        register_dashboard(dashboard(), repository)

    assert first.list_dashboards() == ["trade-dashboard"]
    assert second.list_dashboards() == ["trade-dashboard"]


# ======================================================================
# Unknown keys in a view config (FR-3.4, DECISION-34)
# ======================================================================


def test_an_unknown_key_in_a_view_config_is_rejected(repo: InMemoryRepository) -> None:
    """A typo'd `aggregations` would otherwise fall through to the schema
    default and produce a silently wrong dashboard."""
    payload = config_of(
        {"type": "summary", "field": "amount", "aggregations": "count"}
    )

    with pytest.raises(ValidationFailed) as excinfo:
        register_dashboard(payload, repo)

    assert codes(excinfo.value) == [ErrorCode.UNKNOWN_FIELD]  # FR-3.4
    assert fields(excinfo.value) == ["views[0].aggregations"]


def test_a_misspelled_columns_key_is_rejected(repo: InMemoryRepository) -> None:
    payload = config_of({"type": "table", "colums": ["tradeId"]})

    with pytest.raises(ValidationFailed) as excinfo:
        register_dashboard(payload, repo)

    assert ErrorCode.UNKNOWN_FIELD in codes(excinfo.value)  # FR-3.4
    assert "views[0].colums" in fields(excinfo.value)


def test_a_summary_key_on_a_table_view_is_rejected(repo: InMemoryRepository) -> None:
    """Each handler owns its own key set; `field` means nothing to `table`."""
    payload = config_of({"type": "table", "columns": ["tradeId"], "field": "amount"})

    with pytest.raises(ValidationFailed) as excinfo:
        register_dashboard(payload, repo)

    assert fields(excinfo.value) == ["views[0].field"]  # FR-3.4


def test_every_unknown_key_in_a_view_is_reported(repo: InMemoryRepository) -> None:
    payload = config_of(
        {"type": "table", "columns": ["tradeId"], "limit": 5, "sort": "asc"}
    )

    with pytest.raises(ValidationFailed) as excinfo:
        register_dashboard(payload, repo)

    assert fields(excinfo.value) == ["views[0].limit", "views[0].sort"]  # FR-3.4


def test_the_declared_keys_are_still_accepted(repo: InMemoryRepository) -> None:
    register_dashboard(
        config_of(
            {"type": "summary", "field": "amount", "aggregation": "sum"},
            {"type": "table", "columns": ["tradeId"]},
        ),
        repo,
    )

    assert repo.has_dashboard("trade-dashboard") is True  # FR-3.4


# ======================================================================
# Names that cannot round-trip (FR-3.1, DECISION-35)
# ======================================================================


@pytest.mark.parametrize("name", ["a/b", "/leading", "trailing/", "   ", "\t", ""])
def test_an_unusable_dashboard_name_is_rejected(
    name: str, repo: InMemoryRepository
) -> None:
    """A name containing `/` registers but can never be fetched back; a
    whitespace-only name is not a name."""
    with pytest.raises((ValidationFailed, PydanticValidationError)) as excinfo:
        register_dashboard(dashboard(name=name), repo)

    if isinstance(excinfo.value, ValidationFailed):
        assert ErrorCode.INVALID_NAME in codes(excinfo.value)  # FR-3.1
    assert repo.list_dashboards() == []


@pytest.mark.parametrize("name", ["trade dashboard", "trade-dashboard", "t.d_1", "TD"])
def test_ordinary_dashboard_names_are_accepted(
    name: str, repo: InMemoryRepository
) -> None:
    """Minimal rule: spaces encode and route correctly, so they stay legal."""
    register_dashboard(dashboard(name=name), repo)

    assert repo.list_dashboards() == [name]  # FR-3.1
