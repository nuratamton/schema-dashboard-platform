"""Aggregation registry.

Requirements: NFR-2, FR-1.7, FR-3.8, FR-4.8.

Supported: sum, avg, min, max, count.

Each aggregation declares:
  - which field types it is legal for (sum/avg/min/max -> numeric; count -> any)
  - its result on an empty dataset (sum -> 0, count -> 0, avg/min/max -> None)

Adding an aggregation must be a single registration.

TODO(T4): implement the registry.
"""
