"""View handler registry.

Requirements: NFR-1, FR-3.6-FR-3.10, FR-4.5-FR-4.7.

Each handler exposes two operations:

    validate(config, schema) -> list[ValidationIssue]
        Run at dashboard REGISTRATION time. Referential integrity: every
        referenced field exists in the schema, every aggregation is legal for
        its field's type.

    resolve(config, schema, rows) -> dict
        Run at GET time. Produces the view's output payload.

Handlers: summary, table.

NFR-1: adding a third view type must be a pure addition -- one new handler plus
one registration, with zero edits to existing modules.

Why resolve takes the schema
----------------------------
Not only the rows. ``summary`` needs it to re-derive an aggregation the config
left to the schema's default (FR-3.7), and FR-4.2 names the registered schema as
an input to generation outright. A design where generation read only the dataset
would pass every functional test here while quietly failing that requirement.

View configs are raw dicts
--------------------------
``summary`` carries ``field``, ``table`` carries ``columns``; there is no common
shape to model. A Pydantic union over the known view types would put their names
in ``models.py`` and break NFR-1 the same way ``Literal`` would have broken NFR-3
(DECISION-15). The handler owns its own config's shape, which is what makes a new
view type a pure addition.

Issue codes used here
---------------------
Two, applied consistently:

* ``MISSING_REQUIRED_FIELD`` -- the config did not supply a usable value for a
  key this view needs. Absent, the wrong shape, and empty are the same event:
  no field name was given, no columns were given (FR-3.10).
* ``UNKNOWN_FIELD`` -- a name *was* given and the schema does not declare it
  (FR-3.6, FR-3.9).

Plus the three aggregation codes for ``summary`` (FR-3.7, FR-3.8).
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from typing import Any

from backend.core import aggregations
from backend.core.errors import ErrorCode, ValidationIssue
from backend.core.models import FieldDefinition, SchemaRequest
from backend.store.base import Row

__all__ = [
    "ViewConfig",
    "ViewHandler",
    "ViewResolver",
    "ViewValidator",
    "get",
    "is_registered",
    "register",
    "resolve_aggregation",
    "supported_views",
]


ViewConfig = dict[str, Any]
"""One entry of a dashboard config's ``views`` array, exactly as it arrived."""

ViewValidator = Callable[[ViewConfig, SchemaRequest], list[ValidationIssue]]
ViewResolver = Callable[[ViewConfig, SchemaRequest, Sequence[Row]], dict[str, Any]]


@dataclass(frozen=True, slots=True)
class ViewHandler:
    """A registered view type and its two operations."""

    name: str
    validate: ViewValidator
    resolve: ViewResolver

    config_keys: frozenset[str]
    """Every key this view type understands, ``type`` excluded -- it is common to
    all of them. Declared per handler so a new view type brings its own and NFR-1
    survives; checked centrally by ``core/dashboards.py`` so no handler has to
    remember to. Closes the join between the strict envelope models (DECISION-15)
    and raw-dict view configs (DECISION-21). See DECISION-34."""


_REGISTRY: dict[str, ViewHandler] = {}


def register(
    name: str, *, validate: ViewValidator, config_keys: Collection[str]
) -> Callable[[ViewResolver], ViewResolver]:
    """Register ``name`` as a view type. The whole cost of adding one (NFR-1).

    A view type is two functions rather than one, so the decorator takes
    ``validate`` alongside and decorates ``resolve``. Both halves are named at
    the single registration site, which is the property that matters; the
    asymmetry is the price of keeping one registry shape across this module,
    ``types.py`` and ``aggregations.py``.

    Raises:
        ValueError: if ``name`` is already registered -- a silent overwrite would
            let import order decide which definition wins.
    """

    def decorator(resolve: ViewResolver) -> ViewResolver:
        if name in _REGISTRY:
            raise ValueError(f"View type {name!r} is already registered")
        _REGISTRY[name] = ViewHandler(
            name=name,
            validate=validate,
            resolve=resolve,
            config_keys=frozenset(config_keys),
        )
        return resolve

    return decorator


def _declared_fields(schema: SchemaRequest) -> dict[str, FieldDefinition]:
    """Field definitions by name. Unique by FR-1.3, enforced at registration."""
    return {field.name: field for field in schema.fields}


def resolve_aggregation(config: ViewConfig, field: FieldDefinition) -> Any | None:
    """Apply the FR-3.7 precedence chain: view value -> schema default -> ``None``.

    The single place the chain lives. ``validate`` uses it to decide whether a
    config is registrable and ``resolve`` uses it to decide what to compute, so
    the aggregation a dashboard reports is by construction the one its
    registration was checked against -- the two cannot drift.

    ``None`` means neither source supplied one, which is an error rather than an
    implicit ``sum`` (DECISION-4). The return is deliberately untyped: a config
    may carry any JSON value under ``aggregation``, and reporting that it is not
    a known aggregation is the caller's job, not this function's.
    """
    from_view = config.get("aggregation")
    if from_view is not None:
        return from_view
    return field.aggregation


# ----------------------------------------------------------------------
# summary (FR-3.6 - FR-3.8, FR-4.5)
# ----------------------------------------------------------------------


def _validate_summary(
    config: ViewConfig, schema: SchemaRequest
) -> list[ValidationIssue]:
    """FR-3.6 field exists, FR-3.7 aggregation resolves, FR-3.8 legal for the type."""
    field_name = config.get("field")
    if not isinstance(field_name, str) or not field_name:
        return [ValidationIssue(field="field", code=ErrorCode.MISSING_REQUIRED_FIELD)]

    field = _declared_fields(schema).get(field_name)
    if field is None:
        # FR-3.6. Stop here: legality is a question about the field's type, and
        # there is no field. Same reasoning as the unknown-type guard in
        # validate_schema_definition (DECISION-12).
        return [ValidationIssue(field=field_name, code=ErrorCode.UNKNOWN_FIELD)]

    aggregation = resolve_aggregation(config, field)

    # FR-3.7 -- neither the view nor the schema supplied one.
    if aggregation is None:
        return [
            ValidationIssue(field=field_name, code=ErrorCode.AGGREGATION_REQUIRED)
        ]

    if not isinstance(aggregation, str) or not aggregations.is_registered(aggregation):
        return [
            ValidationIssue(
                field=field_name,
                code=ErrorCode.UNKNOWN_AGGREGATION,
                expected=", ".join(aggregations.supported_aggregations()),
                actual=str(aggregation),
            )
        ]

    # FR-3.8 -- exists, but legal for this field's type?
    if not aggregations.is_legal_for(aggregation, field.type):
        return [
            ValidationIssue(
                field=field_name,
                code=ErrorCode.INVALID_AGGREGATION,
                actual=field.type,
            )
        ]

    return []


@register("summary", validate=_validate_summary, config_keys={"field", "aggregation"})
def _resolve_summary(
    config: ViewConfig, schema: SchemaRequest, rows: Sequence[Row]
) -> dict[str, Any]:
    """FR-4.5 -- aggregate the field across the bound schema's rows.

    Aggregates the field's *non-null* values, so ``count`` means ``COUNT(column)``
    -- rows that have a value -- rather than ``COUNT(*)``. FR-4's response carries
    ``rowCount`` separately, so both numbers remain available and ``count`` stays
    consistent with ``sum`` and ``avg``, which cannot include absent values
    either. See DECISION-20.

    Reads the config through the same precedence chain ``validate`` used, and
    reports the aggregation it actually applied.
    """
    field_name: str = config["field"]
    field = _declared_fields(schema)[field_name]
    aggregation: str = resolve_aggregation(config, field)

    values = [
        row[field_name]
        for row in rows
        if row.get(field_name) is not None
    ]

    return {
        "type": "summary",
        "field": field_name,
        "aggregation": aggregation,
        "value": aggregations.apply(aggregation, values),
    }


# ----------------------------------------------------------------------
# table (FR-3.9, FR-3.10, FR-4.6, FR-4.7)
# ----------------------------------------------------------------------


def _validate_table(config: ViewConfig, schema: SchemaRequest) -> list[ValidationIssue]:
    """FR-3.10 columns non-empty, FR-3.9 every column exists, each named once.

    The uniqueness check enforces FR-4.6 rather than adding a rule of its own:
    "rows projected to exactly the configured columns" is unsatisfiable when a
    column repeats, because a row is an object and an object cannot carry the
    same key twice. The output would report more columns than its rows contain.
    FR-3.5 says a config that cannot produce valid output is refused when it is
    written, not when someone looks at the dashboard. See DECISION-24.
    """
    columns = config.get("columns")
    if not isinstance(columns, list) or not columns:
        # FR-3.10. Absent, not a list, and empty are one event: no columns given.
        return [ValidationIssue(field="columns", code=ErrorCode.MISSING_REQUIRED_FIELD)]

    declared = _declared_fields(schema)
    issues: list[ValidationIssue] = []
    seen: set[str] = set()

    for column in columns:
        # FR-3.9
        if not isinstance(column, str) or column not in declared:
            issues.append(
                ValidationIssue(field=str(column), code=ErrorCode.UNKNOWN_FIELD)
            )
            continue
        # FR-4.6, mirroring the field-uniqueness loop of FR-1.3.
        if column in seen:
            issues.append(
                ValidationIssue(field=column, code=ErrorCode.DUPLICATE_NAME)
            )
        seen.add(column)

    return issues


@register("table", validate=_validate_table, config_keys={"columns"})
def _resolve_table(
    config: ViewConfig, schema: SchemaRequest, rows: Sequence[Row]
) -> dict[str, Any]:
    """FR-4.6 -- project to exactly the configured columns, in configured order.

    FR-4.7: an absent optional value is emitted as ``null`` rather than omitted,
    so every row has the same keys and a client can render the table without
    checking which cells exist. Rows are stored with null optionals absent
    (T6), so this is where that representation is turned back into ``null``.
    """
    columns: list[str] = config["columns"]
    return {
        "type": "table",
        "columns": list(columns),
        "rows": [{column: row.get(column) for column in columns} for row in rows],
    }


# ----------------------------------------------------------------------
# Lookup
# ----------------------------------------------------------------------


def is_registered(name: str) -> bool:
    """Return whether ``name`` is a known view type. Backs FR-3.4."""
    return name in _REGISTRY


def supported_views() -> list[str]:
    """Return every registered view type, in registration order.

    FR-3.4 requires the rejection of an unknown view type to list what is
    supported.
    """
    return list(_REGISTRY)


def get(name: str) -> ViewHandler:
    """Return the registered :class:`ViewHandler`.

    Raises:
        KeyError: if ``name`` is not registered. Same reasoning as the other two
            registries (DECISION-12): FR-3.4 rejects an unknown view type when
            the dashboard is registered, so reaching here means our code is
            wrong, not that the caller sent something bad.
    """
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(
            f"Unknown view type {name!r}; supported view types are "
            f"{', '.join(supported_views())}"
        ) from None
