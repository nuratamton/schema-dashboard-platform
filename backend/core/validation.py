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

TODO(T5): schema registration checks.
TODO(T6): row validation engine.
"""
