"""T3 -- type registry. FR-1.4, FR-1.10.

Must include: True fails the `number` check (Python bool/int trap).
Must include: "1000" fails the `number` check (no coercion).

The accept/reject cases below are taken from the type table in REQUIREMENTS.md
FR-1 -- written from the specification, not from reading the implementation.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from backend.core import types
from backend.core.types import is_registered, matches, register, supported_types


# ----------------------------------------------------------------------
# string -- accepts str, rejects everything else including numbers
# ----------------------------------------------------------------------


@pytest.mark.parametrize("value", ["", "abc", "1000", "true", "0"])
def test_string_accepts_str(value: Any) -> None:
    assert matches("string", value) is True  # FR-1.4


@pytest.mark.parametrize("value", [1, 0, -1, 1.5, True, False, None, [], {}])
def test_string_rejects_everything_else(value: Any) -> None:
    """The table is explicit that numbers are rejected, not stringified."""
    assert matches("string", value) is False  # FR-1.4


# ----------------------------------------------------------------------
# number -- accepts int and float, rejects bool and numeric strings
# ----------------------------------------------------------------------


@pytest.mark.parametrize("value", [0, 1, -1, 1000, 0.0, 1.5, -2.5, 1e3])
def test_number_accepts_int_and_float(value: Any) -> None:
    assert matches("number", value) is True  # FR-1.4


def test_true_does_not_satisfy_number() -> None:
    """isinstance(True, int) is True in Python; the checker must exclude bool."""
    assert matches("number", True) is False  # FR-1.10


def test_false_does_not_satisfy_number() -> None:
    """The trap is about the type, not the truthiness -- False must fail too."""
    assert matches("number", False) is False  # FR-1.10


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_floats_do_not_satisfy_number(value: Any) -> None:
    """DECISION-13 reversed. Python's json parser emits NaN/Infinity literals, and
    FastAPI's encoder turns them back into `null` on the way out -- colliding with
    the value FR-4.8 reserves for "no data"."""
    assert matches("number", value) is False  # FR-1.4


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_non_finite_floats_do_not_satisfy_integer(value: Any) -> None:
    assert matches("integer", value) is False  # FR-1.4


def test_very_large_integers_still_satisfy_number() -> None:
    """math.isfinite() raises on an int too large to convert to float, so the
    finiteness check must apply to floats only."""
    assert matches("number", 10**400) is True  # FR-1.4
    assert matches("integer", 10**400) is True  # FR-1.4


def test_numeric_string_does_not_satisfy_number() -> None:
    """Strict means strict: no coercion of "1000" to 1000."""
    assert matches("number", "1000") is False  # FR-1.4


@pytest.mark.parametrize("value", ["1000", "1.5", "", "abc", None, [], {}])
def test_number_rejects_non_numerics(value: Any) -> None:
    assert matches("number", value) is False  # FR-1.4


# ----------------------------------------------------------------------
# integer -- accepts int, rejects bool, float and numeric strings
# ----------------------------------------------------------------------


@pytest.mark.parametrize("value", [0, 1, -1, 1000])
def test_integer_accepts_int(value: Any) -> None:
    assert matches("integer", value) is True  # FR-1.4


@pytest.mark.parametrize("value", [True, False])
def test_integer_rejects_bool(value: Any) -> None:
    assert matches("integer", value) is False  # FR-1.10


@pytest.mark.parametrize("value", [1.5, -2.5, 5.0, 0.0])
def test_integer_rejects_float(value: Any) -> None:
    """5.0 is the interesting case: a whole float is still a float, not an int."""
    assert matches("integer", value) is False  # FR-1.4


@pytest.mark.parametrize("value", ["1000", "1", "", None, [], {}])
def test_integer_rejects_strings_and_others(value: Any) -> None:
    assert matches("integer", value) is False  # FR-1.4


# ----------------------------------------------------------------------
# boolean -- accepts bool, rejects 0, 1 and "true"
# ----------------------------------------------------------------------


@pytest.mark.parametrize("value", [True, False])
def test_boolean_accepts_bool(value: Any) -> None:
    assert matches("boolean", value) is True  # FR-1.4


@pytest.mark.parametrize("value", [0, 1])
def test_boolean_rejects_int_zero_and_one(value: Any) -> None:
    """The trap runs one way: isinstance(0, bool) is False, so this needs no guard."""
    assert matches("boolean", value) is False  # FR-1.10


@pytest.mark.parametrize("value", ["true", "True", "false", "", None, 1.0, [], {}])
def test_boolean_rejects_strings_and_others(value: Any) -> None:
    assert matches("boolean", value) is False  # FR-1.4


# ----------------------------------------------------------------------
# null is not a type (FR-2.6, FR-2.7)
# ----------------------------------------------------------------------


@pytest.mark.parametrize("type_name", ["string", "number", "integer", "boolean"])
def test_none_satisfies_no_type(type_name: str) -> None:
    """Whether a null is acceptable depends on `required`, which is the validation
    engine's decision (FR-2.6, FR-2.7). A type checker only reports that None is
    not a value of the type."""
    assert matches(type_name, None) is False


# ----------------------------------------------------------------------
# The registry itself (FR-1.4, NFR-3)
# ----------------------------------------------------------------------


def test_the_fr_1_table_is_registered() -> None:
    assert supported_types() == ["string", "number", "integer", "boolean"]


@pytest.mark.parametrize("type_name", ["string", "number", "integer", "boolean"])
def test_is_registered_is_true_for_supported_types(type_name: str) -> None:
    assert is_registered(type_name) is True  # FR-1.4


@pytest.mark.parametrize("type_name", ["date", "Number", "NUMBER", "", "float"])
def test_is_registered_is_false_for_unsupported_types(type_name: str) -> None:
    """Backs the FR-1.4 rejection, and confirms type names are case-sensitive."""
    assert is_registered(type_name) is False  # FR-1.4


def test_unknown_type_names_the_supported_ones() -> None:
    """FR-1.4 requires the rejection to say what is supported."""
    with pytest.raises(KeyError) as excinfo:
        matches("date", "2026-01-01")

    message = str(excinfo.value)
    for type_name in supported_types():
        assert type_name in message  # FR-1.4


def test_checking_an_unknown_type_raises_rather_than_returning_false() -> None:
    """A schema cannot reference an unregistered type (FR-1.4 blocks it at
    registration), so reaching here is a bug in our code -- it must not be
    disguised as a validation failure."""
    with pytest.raises(KeyError):
        matches("nope", "anything")


# ----------------------------------------------------------------------
# Extensibility (NFR-3): adding a type is one registration, no edits elsewhere
# ----------------------------------------------------------------------


@pytest.fixture()
def restore_registry() -> Iterator[None]:
    """Snapshot and restore the registry so extension tests do not leak.

    Reaches into the private _REGISTRY deliberately: the alternative is an
    `unregister` function in the production API that only tests would ever call.
    """
    snapshot = dict(types._REGISTRY)
    yield
    types._REGISTRY.clear()
    types._REGISTRY.update(snapshot)


def test_a_new_type_is_a_single_registration(restore_registry: None) -> None:
    """NFR-3, proven rather than asserted: no existing module is touched."""

    @register("date")
    def _is_date(value: Any) -> bool:
        return isinstance(value, str) and len(value) == 10 and value[4] == value[7] == "-"

    assert is_registered("date") is True
    assert matches("date", "2026-01-01") is True
    assert matches("date", "not-a-date") is False
    assert "date" in supported_types()

    # The types already registered are unaffected.
    assert matches("number", 1000) is True
    assert matches("number", True) is False  # FR-1.10


def test_registering_a_duplicate_type_name_is_refused(restore_registry: None) -> None:
    """A silent overwrite would make the winner depend on import order."""
    with pytest.raises(ValueError, match="already registered"):
        register("string")(lambda value: True)


def test_the_registry_is_unchanged_after_the_extension_tests() -> None:
    """Ordering-independent guard that restore_registry actually restores."""
    assert supported_types() == ["string", "number", "integer", "boolean"]
