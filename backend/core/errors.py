"""Error codes, validation issues, and domain exceptions.

Requirements: NFR-5 (one error contract), NFR-6 (correct status codes), and the
FR-2 validation-failure example.

One error contract across every endpoint::

    {"error": CODE, "message": str, "details": [ValidationIssue, ...]}

``details`` is always present and always a list; it is empty for errors that are
about a resource rather than about its contents.

This module is the single source of the platform's error vocabulary. The store
layer deliberately has none -- it returns ``None`` for a missing entity and
overwrites on a duplicate name -- so every domain error originates at or above
``core`` and is spelled here exactly once.

Two conventions make the API layer generic (NFR-7):

* Every exception carries its own ``status_code`` and ``code`` as class
  attributes, so ``main.py`` registers **one** handler for :class:`PlatformError`
  and reads ``status_code`` off the instance. Adding an error type never touches
  the handler.
* Every exception builds its own response body through :func:`error_response`,
  so the envelope is constructed in one place and cannot drift between endpoints.

Imports nothing from ``api`` or ``store``, and names no use case (RULE-0).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, ClassVar

__all__ = [
    "AmbiguousSchema",
    "DuplicateName",
    "ErrorCode",
    "NoSchemaRegistered",
    "PlatformError",
    "UnknownDashboard",
    "UnknownSchema",
    "ValidationFailed",
    "ValidationIssue",
    "error_response",
]


class ErrorCode(StrEnum):
    """Every error code the platform can emit.

    Codes fall into two roles. *Envelope* codes answer "what kind of failure is
    this?" and appear as the top-level ``error`` key. *Issue* codes answer "what
    specifically is wrong?" and appear as ``code`` inside a ``details[]`` entry.

    The grouping below is by typical role, not a partition: ``DUPLICATE_NAME`` is
    the envelope code for a 409 on a resource name (FR-1.8) *and* the issue code
    for a field name repeated inside one schema (FR-1.3). It is the same
    statement at two scopes.

    The split is why ``VALIDATION_FAILED`` exists even though it is not named in
    TASKS.md: the FR-2 example response uses it as the envelope while the
    per-field codes sit underneath. See DECISION-10.
    """

    # -- Envelope codes: the top-level "error" key -------------------------
    VALIDATION_FAILED = "VALIDATION_FAILED"
    UNKNOWN_SCHEMA = "UNKNOWN_SCHEMA"
    UNKNOWN_DASHBOARD = "UNKNOWN_DASHBOARD"
    DUPLICATE_NAME = "DUPLICATE_NAME"

    AMBIGUOUS_SCHEMA = "AMBIGUOUS_SCHEMA"
    """FR-3.2: a dashboard config omitted ``schema`` and more than one schema is
    registered, so the binding is not unique (DECISION-22)."""

    INVALID_NAME = "INVALID_NAME"
    """FR-1.1, FR-3.1: a name that cannot be used -- it contains ``/``, so
    ``GET /schema/{name}`` could never fetch it back, or it is only whitespace.
    Separate from ``DUPLICATE_NAME`` because a client that retries a duplicate
    with a suffix would loop forever on this one (DECISION-35)."""

    INTERNAL_ERROR = "INTERNAL_ERROR"
    """Something failed that this code did not anticipate. NFR-5 promises one
    error contract across every endpoint, and without a code for the unforeseen
    that promise is only true for failures we thought of (DECISION-36)."""

    NO_SCHEMA_REGISTERED = "NO_SCHEMA_REGISTERED"
    """FR-3.2: a dashboard config omitted ``schema`` and there are no schemas at
    all. Kept apart from ``AMBIGUOUS_SCHEMA`` because nothing is ambiguous here
    and the fix is different -- register a schema, rather than choose between
    them (DECISION-33)."""

    # -- Issue codes: the "code" key inside a details[] entry ---------------
    TYPE_MISMATCH = "TYPE_MISMATCH"
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    UNKNOWN_FIELD = "UNKNOWN_FIELD"

    UNKNOWN_TYPE = "UNKNOWN_TYPE"
    """A type name the relevant registry does not know: a field type in a schema
    (FR-1.4) or a view type in a dashboard config (FR-3.4). ``expected`` carries
    the supported names, which says which registry was consulted. Distinct from
    ``TYPE_MISMATCH``, which is about a *value* failing a type that exists."""

    UNKNOWN_AGGREGATION = "UNKNOWN_AGGREGATION"
    """FR-1.7: the named aggregation is not registered at all."""

    INVALID_AGGREGATION = "INVALID_AGGREGATION"
    """FR-1.7, FR-3.8: the aggregation exists but is not legal for the field's
    type -- ``sum`` on a ``string``. Kept separate from ``UNKNOWN_AGGREGATION``
    because "no such aggregation" and "not on this field" send whoever wrote the
    schema to two different places."""

    AGGREGATION_REQUIRED = "AGGREGATION_REQUIRED"


@dataclass(frozen=True, slots=True, kw_only=True)
class ValidationIssue:
    """One specific thing that is wrong, as it appears in ``details[]``.

    Serves both validation moments. At ingest time (FR-2.9) ``row`` locates the
    offending record; at registration time (FR-1, FR-3.5) there is no row, so
    ``row`` is omitted from the output entirely rather than reported as ``null``.
    ``field`` is likewise optional, for failures that are about the payload as a
    whole rather than one field -- an empty ``fields`` array (FR-1.2) or an empty
    ``views`` array (FR-3.3).

    ``expected`` and ``actual`` name *types*, not values: reporting the offending
    value back would echo caller data into an error body for no diagnostic gain.
    Knowing a ``number`` field received a ``string`` is enough to fix the caller.

    Keyword-only construction is deliberate -- four of the five fields are
    optional, and ``ValidationIssue(1, "x", code)`` would be unreadable at the
    call sites in the validation engine.
    """

    code: ErrorCode
    row: int | None = None
    field: str | None = None
    expected: str | None = None
    actual: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialise in the FR-2 key order, omitting whatever does not apply."""
        payload: dict[str, Any] = {}
        if self.row is not None:
            payload["row"] = self.row
        if self.field is not None:
            payload["field"] = self.field
        payload["code"] = self.code.value
        if self.expected is not None:
            payload["expected"] = self.expected
        if self.actual is not None:
            payload["actual"] = self.actual
        return payload


def error_response(
    code: ErrorCode,
    message: str,
    details: Sequence[ValidationIssue] = (),
) -> dict[str, Any]:
    """Build the NFR-5 envelope.

    The one place the error body is shaped. ``main.py`` calls this directly when
    overriding FastAPI's ``RequestValidationError`` handler, whose default body
    does not match our contract; everywhere else it is reached through
    :meth:`PlatformError.to_response`.
    """
    return {
        "error": code.value,
        "message": message,
        "details": [issue.to_dict() for issue in details],
    }


class PlatformError(Exception):
    """Base for every error the API layer maps to a status code.

    Subclasses set ``status_code`` and ``code`` as class attributes so that
    ``main.py`` can map them generically::

        @app.exception_handler(PlatformError)
        async def handle(request, exc):
            return JSONResponse(exc.status_code, exc.to_response())

    That is the whole point of the class attributes: no if-chain over exception
    types, and a new error type requires no edit to the handler (NFR-1's
    extensibility argument, applied to errors).
    """

    status_code: ClassVar[int]
    code: ClassVar[ErrorCode]

    def __init__(self, message: str, details: Sequence[ValidationIssue] = ()) -> None:
        super().__init__(message)
        self.message = message
        self.details: list[ValidationIssue] = list(details)

    def to_response(self) -> dict[str, Any]:
        """Render this error as the NFR-5 envelope."""
        return error_response(self.code, self.message, self.details)


class ValidationFailed(PlatformError):
    """The payload was well-formed but did not satisfy the rules. NFR-6: 422.

    Covers all three validation moments -- schema registration (FR-1.2-FR-1.7),
    ingestion (FR-2.3-FR-2.9), and dashboard config registration
    (FR-3.3-FR-3.10) -- because they differ only in what they put in ``details``.
    """

    status_code: ClassVar[int] = 422
    code: ClassVar[ErrorCode] = ErrorCode.VALIDATION_FAILED


class UnknownSchema(PlatformError):
    """No schema is registered under the given name. FR-2.1, FR-3.2. NFR-6: 404."""

    status_code: ClassVar[int] = 404
    code: ClassVar[ErrorCode] = ErrorCode.UNKNOWN_SCHEMA

    def __init__(self, name: str) -> None:
        super().__init__(f"No schema is registered under the name {name!r}")
        self.name = name


class UnknownDashboard(PlatformError):
    """No dashboard config is registered under the given name. FR-4.1. NFR-6: 404."""

    status_code: ClassVar[int] = 404
    code: ClassVar[ErrorCode] = ErrorCode.UNKNOWN_DASHBOARD

    def __init__(self, name: str) -> None:
        super().__init__(f"No dashboard is registered under the name {name!r}")
        self.name = name


class DuplicateName(PlatformError):
    """The name is already taken. FR-1.8, FR-3.1. NFR-6: 409.

    One class for both resources: ``resource`` is a caller-supplied label, which
    keeps this free of any branch on what is being registered.
    """

    status_code: ClassVar[int] = 409
    code: ClassVar[ErrorCode] = ErrorCode.DUPLICATE_NAME

    def __init__(self, resource: str, name: str) -> None:
        super().__init__(
            f"A {resource} is already registered under the name {name!r}"
        )
        self.resource = resource
        self.name = name


class AmbiguousSchema(PlatformError):
    """A dashboard config omitted ``schema`` and the choice is not unique. NFR-6: 422.

    FR-3.2 as amended by DECISION-22: the binding is inferred only when exactly
    one schema is registered. Names the candidates so the caller can pick one.

    Raised only when there is more than one candidate. With none, the answer is
    :class:`NoSchemaRegistered` -- see DECISION-33.
    """

    status_code: ClassVar[int] = 422
    code: ClassVar[ErrorCode] = ErrorCode.AMBIGUOUS_SCHEMA

    def __init__(self, candidates: Sequence[str]) -> None:
        self.candidates: list[str] = list(candidates)
        super().__init__(
            f"No 'schema' key was given and {len(self.candidates)} schemas are "
            f"registered, so the binding is ambiguous; name one of: "
            f"{', '.join(self.candidates)}"
        )


class NoSchemaRegistered(PlatformError):
    """A dashboard config omitted ``schema`` and there are none. NFR-6: 422.

    Separate from :class:`AmbiguousSchema` because nothing is ambiguous when
    there is nothing to choose between, and because the two send the caller
    somewhere different: register a schema, rather than name one of several.

    Reachable the first time anyone posts a dashboard before posting a schema,
    which the UI's panel ordering makes an easy thing to do out of order
    (DECISION-33).
    """

    status_code: ClassVar[int] = 422
    code: ClassVar[ErrorCode] = ErrorCode.NO_SCHEMA_REGISTERED

    def __init__(self) -> None:
        super().__init__(
            "No 'schema' key was given and no schemas are registered; "
            "register a schema first, then bind the dashboard to it"
        )
