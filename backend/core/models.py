"""Pydantic request and response models.

Requirements: FR-1, FR-2, FR-3, FR-4.

Scope boundary: Pydantic validates the *envelope* only -- that a schema request
has a name and fields, that an ingest request has a schema name and a list of
rows. It must NOT be used to validate row contents; Pydantic would coerce
"1000" into 1000 and silently defeat FR-2.4. Rows arrive as dict[str, Any] and
are validated by core/validation.py.

TODO(T5): define the models.
"""
