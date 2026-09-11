"""Ingestion endpoint.

    POST /ingest          FR-2

All-or-nothing: a single invalid row rejects the batch and nothing is stored
(FR-2.8, DECISION-1). The error response reports every failing row (FR-2.9).

TODO(T10): implement the router.
"""
