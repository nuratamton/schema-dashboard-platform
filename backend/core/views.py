"""View handler registry.

Requirements: NFR-1, FR-3.6-FR-3.10, FR-4.5-FR-4.7.

Each handler exposes two operations:

    validate(config, schema) -> list[ValidationIssue]
        Run at dashboard REGISTRATION time. Referential integrity: every
        referenced field exists in the schema, every aggregation is legal for
        its field's type.

    resolve(config, rows) -> dict
        Run at GET time. Produces the view's output payload.

Handlers: summary, table.

NFR-1: adding a third view type must be a pure addition -- one new handler plus
one registration, with zero edits to existing modules.

TODO(T7): implement the registry and both handlers.
"""
