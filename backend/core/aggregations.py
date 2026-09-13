"""Aggregation registry.

Requirements: NFR-2, FR-1.7, FR-3.8, FR-4.8.

Supported: sum, avg, min, max, count.

Each aggregation declares:
  - which field types it is legal for (sum/avg/min/max -> numeric; count -> any)
  - its result on an empty dataset (sum -> 0, count -> 0, avg/min/max -> None)

Adding an aggregation is one call to :func:`register`; nothing already written
changes (NFR-2). Same shape as the type registry, deliberately -- two registries
that behave differently are two things to learn.

Legality (FR-1.7, FR-3.8)
-------------------------
``sum``/``avg``/``min``/``max`` require the ``numeric`` trait that
``core/types.py`` puts on a :class:`~backend.core.types.FieldType`. They do not
name ``number`` and ``integer``. The difference matters at the seam between the
two registries: naming the types would mean registering a ``decimal`` type forced
an edit *here*, which is exactly the coupling NFR-3 rules out. ``count`` requires
no trait and is legal for every type, present and future.

Empty datasets (FR-4.8)
-----------------------
An empty input must not raise. Rather than teach four functions to guard, each
aggregation declares its empty result and :func:`apply` short-circuits before
calling it -- so ``min`` over nothing returns ``None`` instead of reaching the
builtin's ``ValueError``. A compute function is guaranteed a non-empty sequence.

Input contract
--------------
:func:`apply` aggregates exactly the values it is handed. It does not reach into
rows, skip nulls, or know which field it is summing -- the caller extracts the
values it wants aggregated. Deciding whether an absent optional value is skipped
or counted belongs to the view handler that reads the dataset (T7), because it is
a question about rows, not about arithmetic.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from backend.core import types

__all__ = [
    "Aggregation",
    "AggregationFunction",
    "apply",
    "get",
    "is_legal_for",
    "is_registered",
    "register",
    "supported_aggregations",
]


AggregationFunction = Callable[[Sequence[Any]], Any]
"""Reduces a non-empty sequence of field values to one value."""


@dataclass(frozen=True, slots=True)
class Aggregation:
    """A registered aggregation: its name, its reducer, and its two declarations."""

    name: str
    compute: AggregationFunction

    empty_result: Any = None
    """What this aggregation returns for an empty dataset (FR-4.8)."""

    requires_numeric: bool = False
    """Whether this aggregation needs a field type carrying the ``numeric`` trait."""


_REGISTRY: dict[str, Aggregation] = {}


def register(
    name: str,
    *,
    empty_result: Any = None,
    requires_numeric: bool = False,
) -> Callable[[AggregationFunction], AggregationFunction]:
    """Register ``name`` as an aggregation. The whole cost of adding one (NFR-2).

    The decorated function may assume a non-empty sequence; ``empty_result``
    covers the empty case (FR-4.8).

    Raises:
        ValueError: if ``name`` is already registered -- a silent overwrite would
            let import order decide which definition wins.
    """

    def decorator(compute: AggregationFunction) -> AggregationFunction:
        if name in _REGISTRY:
            raise ValueError(f"Aggregation {name!r} is already registered")
        _REGISTRY[name] = Aggregation(
            name=name,
            compute=compute,
            empty_result=empty_result,
            requires_numeric=requires_numeric,
        )
        return compute

    return decorator


# ----------------------------------------------------------------------
# The registered aggregations -- the FR-1 legality table
# ----------------------------------------------------------------------


@register("sum", empty_result=0, requires_numeric=True)
def _sum(values: Sequence[Any]) -> Any:
    """Total of the values. Empty dataset totals 0, which is arithmetically true."""
    return sum(values)


@register("avg", empty_result=None, requires_numeric=True)
def _avg(values: Sequence[Any]) -> Any:
    """Arithmetic mean. Empty dataset has no mean, so ``None`` rather than 0."""
    return sum(values) / len(values)


@register("min", empty_result=None, requires_numeric=True)
def _min(values: Sequence[Any]) -> Any:
    """Smallest value. Empty dataset has no smallest value."""
    return min(values)


@register("max", empty_result=None, requires_numeric=True)
def _max(values: Sequence[Any]) -> Any:
    """Largest value. Empty dataset has no largest value."""
    return max(values)


@register("count", empty_result=0, requires_numeric=False)
def _count(values: Sequence[Any]) -> Any:
    """How many values. Legal for every type -- counting needs no arithmetic."""
    return len(values)


# ----------------------------------------------------------------------
# Lookup
# ----------------------------------------------------------------------


def is_registered(name: str) -> bool:
    """Return whether ``name`` is a known aggregation. Backs FR-1.7 and FR-3.4."""
    return name in _REGISTRY


def supported_aggregations() -> list[str]:
    """Return every registered aggregation name, in registration order."""
    return list(_REGISTRY)


def get(name: str) -> Aggregation:
    """Return the registered :class:`Aggregation`.

    Raises:
        KeyError: if ``name`` is not registered. Same reasoning as
            :func:`backend.core.types.get` -- an unknown aggregation is rejected
            when the schema (FR-1.7) or the dashboard config (FR-3.8) is
            registered, so reaching here means our own code is wrong.
    """
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(
            f"Unknown aggregation {name!r}; supported aggregations are "
            f"{', '.join(supported_aggregations())}"
        ) from None


def is_legal_for(name: str, type_name: str) -> bool:
    """Return whether aggregation ``name`` may be applied to a field of ``type_name``.

    The FR-1.7 legality check, used both when a schema declares a default
    aggregation on a field (FR-1.7) and when a dashboard config resolves one
    (FR-3.8).

    Raises:
        KeyError: if either name is unregistered. Callers check
            :func:`is_registered` and :func:`backend.core.types.is_registered`
            first, because "unknown aggregation" and "illegal aggregation" are
            different messages to whoever wrote the schema.
    """
    aggregation = get(name)
    field_type = types.get(type_name)
    return field_type.numeric if aggregation.requires_numeric else True


def apply(name: str, values: Sequence[Any]) -> Any:
    """Aggregate ``values``, returning the declared empty result for an empty input.

    Never raises on an empty dataset (FR-4.8).
    """
    aggregation = get(name)
    if not values:
        return aggregation.empty_result
    return aggregation.compute(values)
