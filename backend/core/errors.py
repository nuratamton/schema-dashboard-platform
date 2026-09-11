"""Error codes, validation issues, and domain exceptions.

Requirements: NFR-5, NFR-6.

One error contract across every endpoint:

    {"error": CODE, "message": str, "details": [ValidationIssue, ...]}

TODO(T2): define the error code enum, the ValidationIssue structure
          (row, field, code, expected, actual), and the exception types that
          the api/ layer maps to HTTP status codes.
"""
