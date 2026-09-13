"""Pydantic request and response models.

Requirements: FR-1, FR-2, FR-3, FR-4.

Scope boundary: Pydantic validates the *envelope* only -- that a schema request
has a name and fields, that an ingest request has a schema name and a list of
rows. It must NOT be used to validate row contents; Pydantic would coerce
"1000" into 1000 and silently defeat FR-2.4. Rows arrive as dict[str, Any] and
are validated by core/validation.py.

A second boundary, just as load-bearing (FR-1.4, FR-1.7, NFR-3): ``type`` and
``aggregation`` are plain ``str`` here, checked against the registries in
``core/types.py`` and ``core/aggregations.py`` afterwards. Modelling them as
``Literal["string", "number", ...]`` or a Python ``Enum`` would read as tighter
typing while quietly hard-coding the registered names into this module --
registering a ``date`` type would then require an edit here, destroying the
property that ``test_a_new_type_is_a_single_registration`` exists to prove. The
registries are the single source of truth for what names are legal; this module
only asserts that a name was supplied and is a string. See DECISION-15.

What Pydantic *is* trusted with here is strictness about shape:

* ``extra="forbid"`` -- a misspelled ``"agg"`` must not be silently dropped,
  leaving a field with no aggregation and a confusing FR-3.7 failure later.
* ``StrictBool`` on ``required`` -- ``1`` and ``"true"`` are not booleans, the
  same posture the type registry takes towards row values (FR-1.10, DECISION-6).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from backend.core import aggregations, types

__all__ = [
    "DashboardRequest",
    "FieldDefinition",
    "IngestRequest",
    "SchemaRequest",
]


def _enum_of(names: Callable[[], list[str]]) -> Callable[[dict[str, Any]], None]:
    """Document a registry's current members in the generated OpenAPI schema.

    Recovers the documentation DECISION-15 gave up. The callable runs at schema
    time, by which point the registries are populated, so ``/docs`` lists the
    supported names while the registry stays the single source of truth -- no
    name is written down here, and registering a type still requires no edit to
    this module. See DECISION-27.
    """

    def inject(schema: dict[str, Any]) -> None:
        # An optional field renders as `anyOf[string, null]`; constrain the
        # string branch, not the union, which would forbid null.
        for branch in schema.get("anyOf", [schema]):
            if branch.get("type") == "string":
                branch["enum"] = names()

    return inject


class FieldDefinition(BaseModel):
    """One field in a schema definition (FR-1.3 - FR-1.7).

    ``type`` and ``aggregation`` carry no constraint beyond being strings; their
    legality is decided against the registries by
    ``core.validation.validate_schema_definition``.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    type: str = Field(min_length=1, json_schema_extra=_enum_of(types.supported_types))

    required: bool = Field(default=False, strict=True)
    """FR-1.5: optional, defaulting to ``False`` when omitted."""

    aggregation: str | None = Field(
        default=None,
        min_length=1,
        json_schema_extra=_enum_of(aggregations.supported_aggregations),
    )
    """FR-1.6: optional. The field's *default* aggregation, which a dashboard
    view may override (FR-3.7, DECISION-4)."""


class SchemaRequest(BaseModel):
    """The ``POST /schema`` payload (FR-1.1, FR-1.2)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)

    fields: list[FieldDefinition] = Field(min_length=1)
    """FR-1.2: non-empty. An empty list is a 422 from the envelope, before any
    of the registry checks run."""


class IngestRequest(BaseModel):
    """The ``POST /ingest`` payload (FR-2.1, FR-2.2).

    This is the model the scope boundary at the top of this module is about.
    ``rows`` is typed ``dict[str, Any]``: the envelope guarantees a non-empty
    list of JSON objects and guarantees *nothing* about what is inside them.
    Row contents are checked by ``core.validation.validate_rows`` against the
    registered schema, because a model here would coerce ``"1000"`` into
    ``1000`` and FR-2.4 would silently never fire (DECISION-6).
    """

    model_config = ConfigDict(extra="forbid")

    schema_name: str = Field(alias="schema", min_length=1)
    """Aliased because a field literally named ``schema`` shadows an attribute on
    Pydantic's ``BaseModel``. The wire format is ``schema``, per FR-2."""

    rows: list[dict[str, Any]] = Field(min_length=1)
    """FR-2.2: a non-empty array of objects. ``Any`` is the point -- values reach
    the validation engine exactly as they arrived."""


class DashboardRequest(BaseModel):
    """The ``POST /dashboard`` payload (FR-3.1 - FR-3.3).

    ``views`` entries are raw dicts for the reason set out in ``core/views.py``:
    ``summary`` and ``table`` share no shape, and a discriminated union over the
    registered view types would put their names here and break NFR-1
    (DECISION-21).
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)

    schema_name: str | None = Field(default=None, alias="schema", min_length=1)
    """FR-3.2 as amended by DECISION-22. Optional: omitted, the binding is
    inferred when exactly one schema is registered, which is what lets the
    brief's own example config work verbatim. Aliased because a field named
    ``schema`` shadows an attribute on Pydantic's ``BaseModel``; the wire format
    is ``schema``.

    Once a config is registered this is always set -- ``register_dashboard``
    stores the *resolved* name, so generation never re-infers (DECISION-23)."""

    views: list[dict[str, Any]] = Field(default_factory=list)
    """FR-3.3: non-empty, but checked by ``validate_dashboard_config`` rather
    than here, so that an empty ``views`` is reported in the same collected 422
    as every other config problem. Defaulting to ``[]`` makes omitted and empty
    one event, the way absent and null are one event for a required row field."""
