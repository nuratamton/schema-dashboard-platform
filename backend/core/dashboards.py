"""Dashboard config validation and dashboard generation.

Requirements: FR-3.1-FR-3.11 (validation), FR-4.1-FR-4.9 (generation).

Validation (T8) runs at REGISTRATION time, not render time. This is the
highest-signal requirement in the assignment: the brief says configs are merely
"stored in memory", which invites a blind write. Delegate per-view checks to the
view handlers.

Aggregation precedence (FR-3.7):
    view config value -> schema field default -> error

Generation (T9) loads schema + rows + config and dispatches each view through
the view registry. There must be no if/elif on view type in this module.

Why registration-time validation is the whole point
---------------------------------------------------
A config referencing a field that does not exist is broken the moment it is
written. Discovering that at ``GET`` time pushes the failure onto whoever is
looking at the dashboard rather than whoever misconfigured it, and does so
repeatedly, forever. Refusing the write means a stored config is, by
construction, one that can be rendered (DECISION-5).

Three outcomes, three status codes
----------------------------------
The checks below run in a fixed order because their results cannot be merged
into one response: a 409, a 404 and a 422 are different answers, and only the
last is a list. Each stage is therefore conclusive.

    1. duplicate name          -> 409  (FR-3.1)
    2. schema binding          -> 404 unknown, or 422 ambiguous  (FR-3.2)
    3. everything else         -> 422 with every issue collected (FR-3.3-FR-3.10)

Only stage 3 accumulates. Stages 1 and 2 are about which schema the config even
refers to; until that is settled there is nothing to validate the views against.

What generation is left holding
-------------------------------
Because every stored config has already been checked against its schema,
:func:`generate_dashboard` has no error path of its own beyond "no such
dashboard" (FR-4.1). It looks nothing up conditionally and validates nothing; it
loads three things and dispatches. That is the dividend FR-3.5 pays.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from backend.core import views
from backend.core.errors import (
    AmbiguousSchema,
    DuplicateName,
    ErrorCode,
    NoSchemaRegistered,
    UnknownDashboard,
    UnknownSchema,
    ValidationFailed,
    ValidationIssue,
)
from backend.core.models import DashboardRequest, SchemaRequest
from backend.core.validation import validate_name
from backend.store.base import Repository

__all__ = [
    "generate_dashboard",
    "register_dashboard",
    "resolve_schema",
    "validate_dashboard_config",
]


def resolve_schema(
    payload: DashboardRequest, repository: Repository
) -> SchemaRequest:
    """Decide which schema a config is bound to. FR-3.2, amended by DECISION-22.

    Named explicitly, the name must be registered. Omitted, the binding is
    inferred when exactly one schema is registered -- which is what lets the
    brief's own example config, carrying no ``schema`` key at all, work verbatim.
    With more than one candidate, inference would be guesswork, so it is refused
    and the candidates are named.

    The two ways inference can fail are reported separately (DECISION-33): too
    many candidates is a choice the caller has to make, none at all is a step
    they have not taken yet.

    Raises:
        UnknownSchema: a name was given and nothing is registered under it
            (FR-3.2 -> 404).
        NoSchemaRegistered: no name was given and no schema exists
            (FR-3.2 -> 422).
        AmbiguousSchema: no name was given and more than one schema exists
            (FR-3.2 -> 422).
    """
    if payload.schema_name is not None:
        schema: SchemaRequest | None = repository.get_schema(payload.schema_name)
        if schema is None:
            raise UnknownSchema(payload.schema_name)
        return schema

    candidates = repository.list_schemas()
    if not candidates:
        raise NoSchemaRegistered()
    if len(candidates) > 1:
        raise AmbiguousSchema(candidates)
    return repository.get_schema(candidates[0])


def _locate(issue: ValidationIssue, index: int) -> ValidationIssue:
    """Prefix an issue's ``field`` with the view it came from.

    A dashboard config has no row index to locate a failure, so the position
    goes in ``field`` as a path -- ``views[1].<field name>``. With several views
    referencing several fields, "UNKNOWN_FIELD on <name>" is not enough to act
    on; naming the view it came from is.
    """
    suffix = f".{issue.field}" if issue.field else ""
    return replace(issue, field=f"views[{index}]{suffix}")


def validate_dashboard_config(
    payload: DashboardRequest, schema: SchemaRequest
) -> list[ValidationIssue]:
    """Check a config against its bound schema. FR-3.3, FR-3.4, FR-3.6-FR-3.10.

    Returns every problem found. A config with four separate mistakes should take
    one round trip to fix.

    This function contains no knowledge of any view type. It checks that a type
    is registered and hands the config to that type's handler, which is what
    makes a third view type a pure addition (NFR-1, FR-4.4).
    """
    issues: list[ValidationIssue] = validate_name(payload.name)

    # FR-3.3. Omitted and empty are one event: no views were given.
    if not payload.views:
        issues.append(
            ValidationIssue(field="views", code=ErrorCode.MISSING_REQUIRED_FIELD)
        )
        return issues

    for index, view in enumerate(payload.views):
        view_type = view.get("type")

        if not isinstance(view_type, str) or not view_type:
            issues.append(
                _locate(
                    ValidationIssue(field="type", code=ErrorCode.MISSING_REQUIRED_FIELD),
                    index,
                )
            )
            continue

        # FR-3.4 -- the rejection names the supported view types.
        if not views.is_registered(view_type):
            issues.append(
                _locate(
                    ValidationIssue(
                        field="type",
                        code=ErrorCode.UNKNOWN_TYPE,
                        expected=", ".join(views.supported_views()),
                        actual=view_type,
                    ),
                    index,
                )
            )
            continue

        handler = views.get(view_type)

        # FR-3.4 -- keys this view type does not understand. A typo'd
        # `aggregations` would otherwise fall through to the schema default and
        # produce a silently wrong dashboard, which is exactly what DECISION-4
        # exists to prevent. The key set lives on the handler, so a new view type
        # brings its own (DECISION-34).
        allowed = handler.config_keys | {"type"}
        issues.extend(
            _locate(ValidationIssue(field=key, code=ErrorCode.UNKNOWN_FIELD), index)
            for key in view
            if key not in allowed
        )

        # FR-3.6 - FR-3.10, delegated. The handler owns its own config's rules.
        issues.extend(
            _locate(issue, index) for issue in handler.validate(view, schema)
        )

    return issues


def register_dashboard(
    payload: DashboardRequest, repository: Repository
) -> DashboardRequest:
    """Validate and store a dashboard config. FR-3.1 - FR-3.11.

    Returns the config as stored, whose ``schema_name`` is always set even when
    the request omitted it.

    Raises:
        DuplicateName: the name is taken (FR-3.1 -> 409).
        UnknownSchema: the named schema is not registered (FR-3.2 -> 404).
        AmbiguousSchema, NoSchemaRegistered: the binding could not be inferred
            (FR-3.2 -> 422).
        ValidationFailed: the config is not consistent with its schema
            (FR-3.3 - FR-3.10 -> 422).
    """
    # Check-then-act, for the same reason as register_schema: the store
    # overwrites silently by design (DECISION-7). Ahead of everything else
    # because re-registration is refused whatever the body says (DECISION-16).
    if repository.has_dashboard(payload.name):
        raise DuplicateName("dashboard", payload.name)

    schema = resolve_schema(payload, repository)

    issues = validate_dashboard_config(payload, schema)
    if issues:
        problem = "problem" if len(issues) == 1 else "problems"
        raise ValidationFailed(
            f"{len(issues)} {problem} found in dashboard {payload.name!r}; "
            f"the dashboard was not registered",
            issues,
        )

    # Store the *resolved* binding, not the request's. An inferred binding is
    # decided once, here, and frozen: a dashboard registered while one schema
    # existed must not change meaning -- or start failing -- when a second is
    # registered later (DECISION-23).
    bound = payload.model_copy(update={"schema_name": schema.name})
    repository.save_dashboard(bound.name, bound)
    return bound


# ----------------------------------------------------------------------
# Generation (FR-4.1 - FR-4.9)
# ----------------------------------------------------------------------


def generate_dashboard(name: str, repository: Repository) -> dict[str, Any]:
    """Render a registered dashboard. FR-4.1 - FR-4.9.

    Reads all three inputs FR-4.2 names -- the stored config, the schema it is
    bound to, and that schema's dataset -- and resolves each view through its
    registered handler in declaration order (FR-4.3, FR-4.4).

    There is no branch on view type here, and adding a view type requires no
    edit to this function: the registry decides what a ``type`` means. The same
    is true of the response, which is assembled from whatever the handlers
    return.

    Raises:
        UnknownDashboard: no such dashboard (FR-4.1 -> 404). The only error this
            function can produce -- every stored config was validated against its
            schema when it was written (FR-3.5), so nothing below can fail.
    """
    config: DashboardRequest | None = repository.get_dashboard(name)
    if config is None:
        raise UnknownDashboard(name)

    # Never None: the binding was resolved and frozen at registration
    # (DECISION-23), schemas cannot be re-registered (DECISION-2), and the
    # repository has no way to delete one.
    schema: SchemaRequest = repository.get_schema(config.schema_name)

    # FR-4.9 comes free here: the store hands out copies (DECISION-8), so
    # nothing below can reach the stored dataset even by accident.
    rows = repository.get_rows(config.schema_name)

    return {
        "dashboard": config.name,
        "schema": config.schema_name,
        # Asked of the store rather than taken as len(rows): rowCount is a fact
        # about the dataset, not about the list this call happens to be holding
        # (DECISION-9).
        "rowCount": repository.count_rows(config.schema_name),
        "views": [
            views.get(view["type"]).resolve(view, schema, rows)
            for view in config.views
        ],
    }
