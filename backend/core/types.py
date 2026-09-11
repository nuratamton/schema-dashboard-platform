"""Field type registry.

Requirements: FR-1.4, FR-1.10, NFR-3.

Maps a type name to a strict checker. Supported: string, number, integer,
boolean. No coercion anywhere -- "1000" is not a number.

TRAP (FR-1.10): isinstance(True, int) is True in Python. Numeric checkers must
exclude bool explicitly.

Adding a type (e.g. "date") must be a single registration, not an edit to a
conditional chain.

TODO(T3): implement the registry.
"""
