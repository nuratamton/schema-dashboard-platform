"""T4 -- aggregation registry. NFR-2, FR-4.8.

Must include: empty-dataset result for all five aggregations.

The legality matrix and the empty-dataset results below are transcribed from the
tables in REQUIREMENTS.md FR-1 and FR-4.8 -- written from the specification, not
read off the implementation.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Any

import pytest

from backend.core import aggregations, types
from backend.core.aggregations import (
    apply,
    is_legal_for,
    is_registered,
    register,
    supported_aggregations,
)

#: The FR-1 legality table: aggregation -> the types it is legal for.
NUMERIC_AGGREGATIONS = ["sum", "avg", "min", "max"]
ALL_TYPES = ["string", "number", "integer", "boolean"]
NUMERIC_TYPES = ["number", "integer"]
NON_NUMERIC_TYPES = ["string", "boolean"]


# ----------------------------------------------------------------------
# Empty-dataset results (FR-4.8) -- all five, and none of them may raise
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("aggregation", "expected"),
    [("sum", 0), ("count", 0), ("avg", None), ("min", None), ("max", None)],
)
def test_empty_dataset_result(aggregation: str, expected: Any) -> None:
    """sum -> 0, count -> 0, avg/min/max -> None. Must not raise."""
    assert apply(aggregation, []) == expected  # FR-4.8


@pytest.mark.parametrize("aggregation", ["sum", "avg", "min", "max", "count"])
def test_no_aggregation_raises_on_an_empty_dataset(aggregation: str) -> None:
    """min([]) and max([]) raise ValueError in Python; the registry must not."""
    apply(aggregation, [])  # FR-4.8 -- the assertion is that this line returns


@pytest.mark.parametrize("aggregation", ["avg", "min", "max"])
def test_empty_result_is_none_not_zero(aggregation: str) -> None:
    """0 would be a claim about the data; None says there is no answer."""
    assert apply(aggregation, []) is None  # FR-4.8


@pytest.mark.parametrize("aggregation", ["sum", "count"])
def test_empty_result_is_zero_not_none(aggregation: str) -> None:
    assert apply(aggregation, []) == 0  # FR-4.8
    assert apply(aggregation, []) is not None  # FR-4.8


# ----------------------------------------------------------------------
# Computation on non-empty data
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("aggregation", "values", "expected"),
    [
        ("sum", [1000, 2000, 3000], 6000),
        ("sum", [1.5, 2.5], 4.0),
        ("sum", [42], 42),
        ("sum", [-1, 1], 0),
        ("avg", [1000, 2000, 3000], 2000),
        ("avg", [1, 2], 1.5),
        ("avg", [42], 42),
        ("min", [3, 1, 2], 1),
        ("min", [-1.5, 0], -1.5),
        ("max", [3, 1, 2], 3),
        ("max", [-1.5, 0], 0),
        ("count", [1, 2, 3], 3),
        ("count", ["a", "b"], 2),
        ("count", [True, False], 2),
        ("count", [None], 1),
    ],
)
def test_aggregate_values(aggregation: str, values: Sequence[Any], expected: Any) -> None:
    assert apply(aggregation, values) == expected


def test_count_is_legal_over_non_numeric_values() -> None:
    """count needs no arithmetic, so it works on whatever the field holds."""
    assert apply("count", ["OPEN", "CLOSED", "OPEN"]) == 3


def test_apply_does_not_mutate_the_input() -> None:
    """Feeds FR-4.9: generation must not disturb the dataset it reads."""
    values = [3, 1, 2]
    for aggregation in ["sum", "avg", "min", "max", "count"]:
        apply(aggregation, values)

    assert values == [3, 1, 2]


# ----------------------------------------------------------------------
# Legality (FR-1.7, FR-3.8) -- expressed as a trait, not a list of type names
# ----------------------------------------------------------------------


@pytest.mark.parametrize("aggregation", NUMERIC_AGGREGATIONS)
@pytest.mark.parametrize("type_name", NUMERIC_TYPES)
def test_arithmetic_aggregations_are_legal_for_numeric_types(
    aggregation: str, type_name: str
) -> None:
    assert is_legal_for(aggregation, type_name) is True  # FR-1.7


@pytest.mark.parametrize("aggregation", NUMERIC_AGGREGATIONS)
@pytest.mark.parametrize("type_name", NON_NUMERIC_TYPES)
def test_arithmetic_aggregations_are_illegal_for_non_numeric_types(
    aggregation: str, type_name: str
) -> None:
    """The FR-1.7 example: "aggregation": "sum" on a string field is rejected."""
    assert is_legal_for(aggregation, type_name) is False  # FR-1.7


@pytest.mark.parametrize("type_name", ALL_TYPES)
def test_count_is_legal_for_every_type(type_name: str) -> None:
    assert is_legal_for("count", type_name) is True  # FR-1.7


def test_boolean_is_not_numeric_for_aggregation_purposes() -> None:
    """The FR-1.10 trap, one layer up: bool is an int in Python, but summing a
    boolean field is a category error, not a convenience."""
    assert is_legal_for("sum", "boolean") is False  # FR-1.7


@pytest.mark.parametrize(
    ("type_name", "numeric"),
    [("number", True), ("integer", True), ("string", False), ("boolean", False)],
)
def test_the_numeric_trait_matches_the_fr_1_table(type_name: str, numeric: bool) -> None:
    """Legality is read off this trait, so the trait is what has to be right."""
    assert types.get(type_name).numeric is numeric  # FR-1.7


def test_legality_of_an_unknown_aggregation_raises() -> None:
    """"Unknown aggregation" and "illegal aggregation" are different messages to
    whoever wrote the schema; the caller distinguishes them before asking."""
    with pytest.raises(KeyError, match="median"):
        is_legal_for("median", "number")


def test_legality_against_an_unknown_type_raises() -> None:
    with pytest.raises(KeyError, match="date"):
        is_legal_for("sum", "date")


# ----------------------------------------------------------------------
# The registry itself
# ----------------------------------------------------------------------


def test_the_five_aggregations_are_registered() -> None:
    assert supported_aggregations() == ["sum", "avg", "min", "max", "count"]


@pytest.mark.parametrize("aggregation", ["sum", "avg", "min", "max", "count"])
def test_is_registered_is_true_for_supported_aggregations(aggregation: str) -> None:
    assert is_registered(aggregation) is True


@pytest.mark.parametrize("aggregation", ["median", "Sum", "SUM", "", "total"])
def test_is_registered_is_false_for_unsupported_aggregations(aggregation: str) -> None:
    """Confirms aggregation names are case-sensitive, as type names are."""
    assert is_registered(aggregation) is False


def test_unknown_aggregation_names_the_supported_ones() -> None:
    with pytest.raises(KeyError) as excinfo:
        apply("median", [1, 2, 3])

    message = str(excinfo.value)
    for aggregation in supported_aggregations():
        assert aggregation in message


# ----------------------------------------------------------------------
# Extensibility (NFR-2): adding an aggregation is one registration
# ----------------------------------------------------------------------


@pytest.fixture()
def restore_registry() -> Iterator[None]:
    """Snapshot and restore the registry so extension tests do not leak.

    Reaches into the private _REGISTRY deliberately: the alternative is an
    `unregister` function in the production API that only tests would ever call.
    """
    snapshot = dict(aggregations._REGISTRY)
    yield
    aggregations._REGISTRY.clear()
    aggregations._REGISTRY.update(snapshot)


def test_a_new_aggregation_is_a_single_registration(restore_registry: None) -> None:
    """NFR-2, proven rather than asserted: no existing module is touched."""

    @register("median", empty_result=None, requires_numeric=True)
    def _median(values: Sequence[Any]) -> Any:
        ordered = sorted(values)
        midpoint = len(ordered) // 2
        if len(ordered) % 2:
            return ordered[midpoint]
        return (ordered[midpoint - 1] + ordered[midpoint]) / 2

    assert is_registered("median") is True  # NFR-2
    assert apply("median", [1, 3, 2]) == 2  # NFR-2
    assert apply("median", [1, 2, 3, 4]) == 2.5
    assert apply("median", []) is None  # FR-4.8
    assert is_legal_for("median", "number") is True  # FR-1.7
    assert is_legal_for("median", "string") is False  # FR-1.7

    # The aggregations already registered are unaffected.
    assert apply("sum", [1000, 2000]) == 3000


def test_a_new_type_is_legal_for_arithmetic_without_editing_this_module(
    restore_registry: None,
) -> None:
    """The reason legality is a trait rather than a list of type names (NFR-3).

    Registering a numeric type makes every arithmetic aggregation legal for it
    immediately -- aggregations.py names no type and so needs no edit.
    """
    types_snapshot = dict(types._REGISTRY)
    try:

        @types.register("decimal", numeric=True)
        def _is_decimal(value: Any) -> bool:
            return isinstance(value, (int, float)) and not isinstance(value, bool)

        for aggregation in NUMERIC_AGGREGATIONS:
            assert is_legal_for(aggregation, "decimal") is True  # NFR-2 / NFR-3
        assert is_legal_for("count", "decimal") is True  # FR-1.7
    finally:
        types._REGISTRY.clear()
        types._REGISTRY.update(types_snapshot)


def test_registering_a_duplicate_aggregation_name_is_refused(restore_registry: None) -> None:
    """A silent overwrite would make the winner depend on import order."""
    with pytest.raises(ValueError, match="already registered"):
        register("sum")(lambda values: 0)


def test_the_registry_is_unchanged_after_the_extension_tests() -> None:
    """Ordering-independent guard that restore_registry actually restores."""
    assert supported_aggregations() == ["sum", "avg", "min", "max", "count"]
    assert types.supported_types() == ["string", "number", "integer", "boolean"]
