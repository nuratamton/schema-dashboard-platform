"""Schema registration checks and the row validation engine.

Requirements: FR-1.1-FR-1.8 (registration), FR-2.3-FR-2.9 (rows).

Registration-time checks:
  - field names unique within the schema
  - every declared type exists in the type registry
  - any declared default aggregation is legal for the field's type

Row validation:
  - every required field present and non-null       -> MISSING_REQUIRED_FIELD
  - every present value matches its declared type   -> TYPE_MISMATCH
  - no fields outside the schema                    -> UNKNOWN_FIELD
  - null in an optional field is accepted

Collects EVERY issue across EVERY row (FR-2.9). Does not stop at the first.
"""

from __future__ import annotations

from collections.abc import Sequence

from backend.core import aggregations, types
from backend.core.errors import (
    DuplicateName,
    ErrorCode,
    UnknownSchema,
    ValidationFailed,
    ValidationIssue,
)
from backend.core.models import IngestRequest, SchemaRequest
from backend.store.base import Repository, Row

__all__ = [
    "ingest_rows",
    "validate_name",
    "register_schema",
    "validate_rows",
    "validate_schema_definition",
]


def validate_name(name: str) -> list[ValidationIssue]:
    """Reject a name that cannot be used. FR-1.1, FR-3.1.

    Two rules, both about round-tripping rather than taste:

    * ``/`` makes the resource unreachable. ``POST`` accepts it, ``GET
      /schema/{name}`` cannot match it, and percent-encoding does not help
      because the path is decoded before routing -- so the name is registered,
      listed, permanently unfetchable, and permanently taken.
    * whitespace-only is not a name. ``min_length=1`` counts spaces.

    Deliberately minimal. No character whitelist: spaces, dots, hyphens and
    unicode all encode and route correctly, and a rule that rejected a name
    somebody reasonably tried would be worse than the problem. See DECISION-35.
    """
    if not name.strip() or "/" in name:
        return [ValidationIssue(field="name", code=ErrorCode.INVALID_NAME)]
    return []


def validate_schema_definition(payload: SchemaRequest) -> list[ValidationIssue]:
    """Check a schema definition against the registries. FR-1.3, FR-1.4, FR-1.7.

    Returns every problem found rather than the first. A schema with three
    separate mistakes should take one round trip to fix, not three.

    Issues carry no ``row`` -- there are no rows at registration time, and
    :class:`~backend.core.errors.ValidationIssue` omits the key entirely rather
    than reporting ``null`` (DECISION-10).

    FR-1.2 (non-empty ``fields``) is absent here on purpose: the envelope model
    enforces it, so this function is never reached with an empty list.
    """
    issues: list[ValidationIssue] = validate_name(payload.name)
    seen_names: set[str] = set()

    for field in payload.fields:
        # FR-1.3 -- unique within the schema. The duplicate is still checked
        # below; one mistake should not suppress the report of another.
        if field.name in seen_names:
            issues.append(
                ValidationIssue(field=field.name, code=ErrorCode.DUPLICATE_NAME)
            )
        seen_names.add(field.name)

        # FR-1.4 -- the type must be registered, and the rejection names what is.
        type_is_known = types.is_registered(field.type)
        if not type_is_known:
            issues.append(
                ValidationIssue(
                    field=field.name,
                    code=ErrorCode.UNKNOWN_TYPE,
                    expected=", ".join(types.supported_types()),
                    actual=field.type,
                )
            )

        if field.aggregation is None:
            continue

        # FR-1.7, first half -- does this aggregation exist at all?
        if not aggregations.is_registered(field.aggregation):
            issues.append(
                ValidationIssue(
                    field=field.name,
                    code=ErrorCode.UNKNOWN_AGGREGATION,
                    expected=", ".join(aggregations.supported_aggregations()),
                    actual=field.aggregation,
                )
            )
            continue

        # An unknown type has already been reported, and legality cannot be
        # judged against a type that does not exist -- is_legal_for raises
        # KeyError rather than guessing (DECISION-12). Reporting UNKNOWN_TYPE
        # alone is also the more useful answer: fix the type and the
        # aggregation may well be fine.
        if not type_is_known:
            continue

        # FR-1.7, second half -- legal for this field's type?
        if not aggregations.is_legal_for(field.aggregation, field.type):
            issues.append(
                ValidationIssue(
                    field=field.name,
                    code=ErrorCode.INVALID_AGGREGATION,
                    actual=field.type,
                )
            )

    return issues


def register_schema(payload: SchemaRequest, repository: Repository) -> SchemaRequest:
    """Validate and store a schema definition. FR-1.1, FR-1.8, FR-1.9.

    The repository is a parameter rather than a module-level singleton so that a
    caller -- the API layer at T10, a test at any point -- decides what state
    this writes into (NFR-4).

    Duplicate detection is a check-then-act: the store overwrites silently by
    design and has no error vocabulary (DECISION-7), so the 409 is decided here.

    Raises:
        DuplicateName: the name is taken (FR-1.8 -> 409).
        ValidationFailed: the definition is not internally consistent
            (FR-1.3, FR-1.4, FR-1.7 -> 422).
    """
    # Ahead of content validation: re-registration is refused whatever the body
    # says, so reporting problems in a schema that cannot be created either way
    # is noise. See DECISION-16.
    if repository.has_schema(payload.name):
        raise DuplicateName("schema", payload.name)

    issues = validate_schema_definition(payload)
    if issues:
        problem = "problem" if len(issues) == 1 else "problems"
        raise ValidationFailed(
            f"{len(issues)} {problem} found in schema {payload.name!r}; "
            f"the schema was not registered",
            issues,
        )

    repository.save_schema(payload.name, payload)
    return payload


# ----------------------------------------------------------------------
# Row validation (FR-2.3 - FR-2.9)
# ----------------------------------------------------------------------


def validate_rows(
    schema: SchemaRequest, rows: Sequence[Row]
) -> list[ValidationIssue]:
    """Check rows against a registered schema. FR-2.3 - FR-2.7, FR-2.9.

    This is the engine the scope boundary exists for. Rows arrive as plain
    dicts and every value is inspected by the type registry, never by Pydantic,
    which would coerce ``"1000"`` into ``1000`` and defeat FR-2.4 in silence
    (DECISION-6).

    Every issue across every row is collected (FR-2.9) -- neither the first bad
    field nor the first bad row ends the pass. ``row`` is the zero-based index
    into ``rows``.

    Null has two meanings, decided by the field rather than the value: absent and
    ``null`` are the same thing in a required field (FR-2.3, FR-2.6) and both the
    same non-event in an optional one (FR-2.7).
    """
    issues: list[ValidationIssue] = []
    declared = {field.name: field for field in schema.fields}

    for index, row in enumerate(rows):
        # Declared fields, in schema order: present, non-null, right type?
        for field in schema.fields:
            value = row.get(field.name)

            # FR-2.3 absent, FR-2.6 explicitly null -- the same failure. A
            # required field is a promise that a value exists, and `null` is
            # precisely the claim that one does not.
            if value is None:
                if field.required:
                    issues.append(
                        ValidationIssue(
                            row=index,
                            field=field.name,
                            code=ErrorCode.MISSING_REQUIRED_FIELD,
                        )
                    )
                # FR-2.7: null in an optional field is accepted and carries no
                # type to check.
                continue

            # FR-2.4 -- strict, no coercion.
            if not types.matches(field.type, value):
                issues.append(
                    ValidationIssue(
                        row=index,
                        field=field.name,
                        code=ErrorCode.TYPE_MISMATCH,
                        expected=field.type,
                        actual=types.type_name_of(value),
                    )
                )

        # FR-2.5 -- anything the schema does not declare.
        for key in row:
            if key not in declared:
                issues.append(
                    ValidationIssue(
                        row=index, field=key, code=ErrorCode.UNKNOWN_FIELD
                    )
                )

    return issues


def _without_nulls(row: Row) -> Row:
    """Drop keys whose value is ``null`` so they are stored as absent (FR-2.7).

    Only reached once a batch has validated, so every remaining ``null`` belongs
    to an optional field. Storing absence rather than ``null`` keeps one
    representation of "no value" in the dataset; FR-4.7 projects it back as
    ``null`` when a table view needs rectangular rows.
    """
    return {key: value for key, value in row.items() if value is not None}


def ingest_rows(payload: IngestRequest, repository: Repository) -> int:
    """Validate a batch and append it. Returns the number of rows ingested.

    FR-2.8 -- all-or-nothing. One bad row rejects the batch and nothing is
    written (DECISION-1). The store is only touched after the whole batch has
    passed, so atomicity needs no transaction: there is exactly one write.

    Raises:
        UnknownSchema: no such schema (FR-2.1 -> 404).
        ValidationFailed: one or more rows failed (FR-2.9 -> 422), reporting
            every failing row and field.
    """
    schema: SchemaRequest | None = repository.get_schema(payload.schema_name)
    if schema is None:
        raise UnknownSchema(payload.schema_name)

    issues = validate_rows(schema, payload.rows)
    if issues:
        # The FR-2 example counts rows, not issues: three bad fields in one row
        # is "1 of 5 rows failed", which is what the caller has to go and fix.
        failing_rows = {issue.row for issue in issues}
        raise ValidationFailed(
            f"{len(failing_rows)} of {len(payload.rows)} rows failed validation; "
            f"no rows were ingested",
            issues,
        )

    repository.append_rows(
        payload.schema_name, [_without_nulls(row) for row in payload.rows]
    )
    return len(payload.rows)
