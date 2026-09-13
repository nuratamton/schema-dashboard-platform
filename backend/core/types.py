"""Field type registry.

Requirements: FR-1.4, FR-1.10, NFR-3.

Maps a type name to a strict checker. Supported: string, number, integer,
boolean. No coercion anywhere -- ``"1000"`` is not a number, and a whole float
like ``5.0`` is not an integer. Checkers answer one question, ``does this value
satisfy this type``, and nothing else.

A registry, not a conditional chain. Adding a type is one call to
:func:`register`; nothing already written changes (NFR-3).

Traits
------
A registered type carries one trait, ``numeric``. ``core/aggregations.py`` reads
it to decide FR-1.7 legality: ``sum`` requires the trait rather than naming
``number`` and ``integer``, so registering a ``decimal`` type later stays a
one-line addition instead of an edit to that module. One boolean covers the whole
FR-1.7 matrix; see DECISION-14 for why it stops there.

TRAP (FR-1.10)
--------------
``isinstance(True, int)`` is ``True`` in Python, so ``bool`` silently satisfies
every naive numeric check. Both numeric checkers exclude it explicitly. The
inverse is already safe -- ``isinstance(0, bool)`` is ``False`` -- so ``0`` and
``1`` do not satisfy ``boolean`` without any special handling.

Scalar invariant
----------------
Every type registered here is scalar, and that is load-bearing beyond this
module: ``store/memory.py`` copies rows with a shallow ``dict()`` on the way in
and out to guarantee FR-4.9, which is only sufficient because no field value can
hold nested structure (DECISION-8). **Registering a container type -- ``array``,
``object`` -- breaks that reasoning and requires revisiting the store's copy
semantics first.** A scalar type is a free addition; a container type is not.

Null is not a type here. ``None`` satisfies nothing, and whether that is an error
depends on the field's ``required`` flag (FR-2.6, FR-2.7) -- a question for the
validation engine, not for a type checker.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

__all__ = [
    "FieldType",
    "TypeChecker",
    "get",
    "is_registered",
    "matches",
    "register",
    "supported_types",
    "type_name_of",
]


TypeChecker = Callable[[Any], bool]
"""Answers whether one value satisfies one type. Total, pure, and never raises."""


@dataclass(frozen=True, slots=True)
class FieldType:
    """A registered type: its name as it appears in a schema, its checker, its traits."""

    name: str
    check: TypeChecker

    numeric: bool = False
    """Whether arithmetic applies to values of this type.

    The whole trait vocabulary, deliberately. ``core/aggregations.py`` requires
    this flag for ``sum``/``avg``/``min``/``max`` instead of naming the types it
    accepts, which is what keeps a future ``decimal`` registration from forcing an
    edit there (NFR-3, DECISION-14).
    """


_REGISTRY: dict[str, FieldType] = {}


def register(name: str, *, numeric: bool = False) -> Callable[[TypeChecker], TypeChecker]:
    """Register ``name`` as a field type. The whole cost of adding a type (NFR-3).

    Set ``numeric`` for a type that arithmetic applies to; that alone makes
    ``sum``, ``avg``, ``min`` and ``max`` legal for it (FR-1.7).

    Before registering anything non-scalar, read the scalar invariant in this
    module's docstring -- a container type invalidates the store's copy strategy.

    Raises:
        ValueError: if ``name`` is already registered. A silent overwrite would
            let two definitions of a type coexist with the winner decided by
            import order.
    """

    def decorator(check: TypeChecker) -> TypeChecker:
        if name in _REGISTRY:
            raise ValueError(f"Field type {name!r} is already registered")
        _REGISTRY[name] = FieldType(name=name, check=check, numeric=numeric)
        return check

    return decorator


# ----------------------------------------------------------------------
# The registered types -- the FR-1 table, in the order it lists them
# ----------------------------------------------------------------------


@register("string")
def _is_string(value: Any) -> bool:
    """Accepts ``str``. Rejects everything else, including numbers (FR-1.4)."""
    return isinstance(value, str)


@register("number", numeric=True)
def _is_number(value: Any) -> bool:
    """Accepts finite ``int`` and ``float``. Rejects ``bool`` (FR-1.10), numeric
    strings, and the non-finite floats ``NaN`` and ``Infinity``.

    Python's ``json`` parser emits ``NaN``/``Infinity`` literals, and FastAPI's
    encoder turns them back into ``null`` on the way out -- the value FR-4.8
    reserves for "there is no data". A ``sum`` over one ``NaN`` row would report
    ``null`` beside ``rowCount: 1``. See DECISION-13, reversed.

    ``math.isfinite`` is applied to floats only: it raises ``OverflowError`` on an
    int too large to convert to a float, and an int is never non-finite.
    """
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    return isinstance(value, float) and math.isfinite(value)


@register("integer", numeric=True)
def _is_integer(value: Any) -> bool:
    """Accepts ``int``. Rejects ``bool`` (FR-1.10), ``float`` -- ``5.0`` included -- and strings."""
    return isinstance(value, int) and not isinstance(value, bool)


@register("boolean")
def _is_boolean(value: Any) -> bool:
    """Accepts ``bool``. Rejects ``0``, ``1`` and ``"true"``.

    No ``int`` exclusion is needed in this direction: ``isinstance(0, bool)`` is
    ``False``. The trap runs one way only.
    """
    return isinstance(value, bool)


# ----------------------------------------------------------------------
# Lookup
# ----------------------------------------------------------------------


def is_registered(name: str) -> bool:
    """Return whether ``name`` is a known field type. Backs FR-1.4."""
    return name in _REGISTRY


def supported_types() -> list[str]:
    """Return every registered type name, in registration order.

    FR-1.4 requires the rejection of an unknown type to name what *is* supported,
    and registration order means that message mirrors the FR-1 table rather than
    re-sorting it.
    """
    return list(_REGISTRY)


def get(type_name: str) -> FieldType:
    """Return the registered :class:`FieldType`, traits included.

    ``core/aggregations.py`` reaches for this to read ``numeric`` when deciding
    FR-1.7 legality.

    Raises:
        KeyError: if ``type_name`` is not registered. This is a programming
            error rather than a validation failure -- FR-1.4 rejects unknown
            types when the schema is registered, so nothing downstream can ever
            reference a type that does not exist. Returning ``None`` here would
            disguise that bug as bad data. See DECISION-12.
    """
    try:
        return _REGISTRY[type_name]
    except KeyError:
        raise KeyError(
            f"Unknown field type {type_name!r}; supported types are "
            f"{', '.join(supported_types())}"
        ) from None


def matches(type_name: str, value: Any) -> bool:
    """Return whether ``value`` satisfies the type registered as ``type_name``.

    Raises:
        KeyError: if ``type_name`` is not registered. See :func:`get`.
    """
    return get(type_name).check(value)


def type_name_of(value: Any) -> str | None:
    """Name ``value``'s type in the platform's own vocabulary, or ``None``.

    Fills the ``actual`` slot of a ``TYPE_MISMATCH`` issue (FR-2.4). Reporting a
    registered type name rather than a Python one keeps error bodies speaking the
    same language as schemas: a caller who wrote ``"type": "number"`` is told the
    value was a ``string``, not a ``str``.

    ``None`` means no registered type accepts the value -- ``null``, or a nested
    array or object, which the scalar invariant excludes. The caller omits the
    ``actual`` key entirely rather than inventing a name for something outside
    the type system.

    Ambiguity is resolved by declaration order, so ``5`` reports as ``number``
    rather than ``integer``. That tie-break is unobservable where it would
    matter: a value satisfying the expected type never produces a mismatch in the
    first place, so the only way to see it is a mismatch against some *other*
    type -- ``{"id": 5}`` against a ``string`` field, reported as ``number``.
    Either name would be equally true there.
    """
    for field_type in _REGISTRY.values():
        if field_type.check(value):
            return field_type.name
    return None
