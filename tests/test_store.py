"""T1 -- repository interface and in-memory implementation. NFR-4.

Names here are deliberately neutral ("alpha", "beta"). The store has no domain
vocabulary, so its tests should not lend it one; a test that reads naturally with
meaningless names is evidence the layer really is generic (RULE-0).
"""

from __future__ import annotations

import pytest

from backend.store.base import Repository
from backend.store.memory import InMemoryRepository


@pytest.fixture()
def repo() -> InMemoryRepository:
    """A fresh, empty repository per test. No shared state between tests."""
    return InMemoryRepository()


# ----------------------------------------------------------------------
# The contract itself (NFR-4)
# ----------------------------------------------------------------------


def test_repository_is_abstract() -> None:
    """The interface cannot be used directly -- it is a contract, not a default."""
    with pytest.raises(TypeError):
        Repository()  # type: ignore[abstract]


def test_in_memory_implements_the_whole_contract() -> None:
    """Guards NFR-4: adding a method to the ABC without implementing it fails here."""
    assert Repository.__abstractmethods__, "the ABC declares no abstract methods"
    assert not InMemoryRepository.__abstractmethods__
    assert isinstance(InMemoryRepository(), Repository)


def test_instances_do_not_share_state() -> None:
    """Class-level dicts are the classic bug; two repositories must be independent."""
    first, second = InMemoryRepository(), InMemoryRepository()
    first.save_schema("alpha", {"fields": []})
    first.save_dashboard("alpha-view", {"views": []})
    first.append_rows("alpha", [{"a": 1}])

    assert second.list_schemas() == []
    assert second.list_dashboards() == []
    assert second.get_rows("alpha") == []


# ----------------------------------------------------------------------
# Schemas (FR-1.9)
# ----------------------------------------------------------------------


def test_saved_schema_is_retrievable(repo: InMemoryRepository) -> None:
    definition = {"name": "alpha", "fields": [{"name": "a", "type": "string"}]}
    repo.save_schema("alpha", definition)

    assert repo.get_schema("alpha") == definition
    assert repo.has_schema("alpha") is True


def test_unknown_schema_reads_as_absent_without_raising(repo: InMemoryRepository) -> None:
    """The store reports absence; deciding it is a 404 belongs to the caller."""
    assert repo.get_schema("nope") is None
    assert repo.has_schema("nope") is False


def test_list_schemas_is_empty_before_anything_is_registered(repo: InMemoryRepository) -> None:
    assert repo.list_schemas() == []


def test_list_schemas_preserves_registration_order(repo: InMemoryRepository) -> None:
    for name in ("gamma", "alpha", "beta"):
        repo.save_schema(name, {"name": name})

    assert repo.list_schemas() == ["gamma", "alpha", "beta"]


def test_saving_the_same_schema_name_overwrites(repo: InMemoryRepository) -> None:
    """Last write wins at this layer.

    FR-1.8 requires a 409, but that is an HTTP decision made by the caller after
    consulting has_schema(). The store stays free of error semantics, so this
    test documents the port's behaviour rather than the endpoint's.
    """
    repo.save_schema("alpha", {"version": "first"})
    repo.save_schema("alpha", {"version": "second"})

    assert repo.get_schema("alpha") == {"version": "second"}
    assert repo.list_schemas() == ["alpha"]


# ----------------------------------------------------------------------
# Dashboard configs (FR-3.11)
# ----------------------------------------------------------------------


def test_saved_dashboard_is_retrievable(repo: InMemoryRepository) -> None:
    config = {"name": "alpha-view", "schema": "alpha", "views": [{"type": "table"}]}
    repo.save_dashboard("alpha-view", config)

    assert repo.get_dashboard("alpha-view") == config
    assert repo.has_dashboard("alpha-view") is True


def test_unknown_dashboard_reads_as_absent_without_raising(repo: InMemoryRepository) -> None:
    assert repo.get_dashboard("nope") is None
    assert repo.has_dashboard("nope") is False


def test_list_dashboards_preserves_registration_order(repo: InMemoryRepository) -> None:
    assert repo.list_dashboards() == []
    for name in ("second", "first"):
        repo.save_dashboard(name, {"name": name})

    assert repo.list_dashboards() == ["second", "first"]


def test_saving_the_same_dashboard_name_overwrites(repo: InMemoryRepository) -> None:
    repo.save_dashboard("alpha-view", {"version": "first"})
    repo.save_dashboard("alpha-view", {"version": "second"})

    assert repo.get_dashboard("alpha-view") == {"version": "second"}


def test_schemas_and_dashboards_are_separate_namespaces(repo: InMemoryRepository) -> None:
    """A schema and a dashboard may share a name without colliding."""
    repo.save_schema("alpha", {"kind": "schema"})
    repo.save_dashboard("alpha", {"kind": "dashboard"})

    assert repo.get_schema("alpha") == {"kind": "schema"}
    assert repo.get_dashboard("alpha") == {"kind": "dashboard"}


# ----------------------------------------------------------------------
# Row datasets (FR-2.10)
# ----------------------------------------------------------------------


def test_appended_rows_come_back_in_order(repo: InMemoryRepository) -> None:
    rows = [{"a": 1}, {"a": 2}, {"a": 3}]
    repo.append_rows("alpha", rows)

    assert repo.get_rows("alpha") == rows


def test_successive_appends_accumulate_in_order(repo: InMemoryRepository) -> None:
    repo.append_rows("alpha", [{"a": 1}])
    repo.append_rows("alpha", [{"a": 2}, {"a": 3}])

    assert repo.get_rows("alpha") == [{"a": 1}, {"a": 2}, {"a": 3}]


def test_rows_for_an_unknown_schema_are_empty(repo: InMemoryRepository) -> None:
    """Supports the empty-dataset aggregations of FR-4.8, which must not raise."""
    assert repo.get_rows("nope") == []
    assert repo.count_rows("nope") == 0


def test_rows_for_a_schema_with_no_ingest_are_empty(repo: InMemoryRepository) -> None:
    repo.save_schema("alpha", {"name": "alpha"})

    assert repo.get_rows("alpha") == []
    assert repo.count_rows("alpha") == 0


def test_appending_an_empty_batch_is_a_no_op(repo: InMemoryRepository) -> None:
    repo.append_rows("alpha", [])

    assert repo.get_rows("alpha") == []
    assert repo.count_rows("alpha") == 0


def test_datasets_are_isolated_per_schema(repo: InMemoryRepository) -> None:
    repo.append_rows("alpha", [{"a": 1}])
    repo.append_rows("beta", [{"b": 2}, {"b": 3}])

    assert repo.get_rows("alpha") == [{"a": 1}]
    assert repo.get_rows("beta") == [{"b": 2}, {"b": 3}]


def test_count_rows_tracks_appends(repo: InMemoryRepository) -> None:
    """Backs rowCount in the FR-4 response."""
    repo.append_rows("alpha", [{"a": 1}, {"a": 2}])
    repo.append_rows("alpha", [{"a": 3}])

    assert repo.count_rows("alpha") == 3


def test_the_store_does_not_inspect_row_contents(repo: InMemoryRepository) -> None:
    """Any JSON object goes in unchanged -- shape is core's concern, not the store's."""
    rows = [{}, {"any": None}, {"other": False, "third": 0}]
    repo.append_rows("alpha", rows)

    assert repo.get_rows("alpha") == rows


# ----------------------------------------------------------------------
# Mutation isolation (FR-4.9)
# ----------------------------------------------------------------------


def test_mutating_a_row_after_appending_does_not_change_the_store(
    repo: InMemoryRepository,
) -> None:
    row = {"a": 1}
    repo.append_rows("alpha", [row])
    row["a"] = 999

    assert repo.get_rows("alpha") == [{"a": 1}]


def test_mutating_the_submitted_batch_does_not_change_the_store(
    repo: InMemoryRepository,
) -> None:
    batch = [{"a": 1}]
    repo.append_rows("alpha", batch)
    batch.append({"a": 2})

    assert repo.get_rows("alpha") == [{"a": 1}]


def test_mutating_returned_rows_does_not_change_the_store(repo: InMemoryRepository) -> None:
    """Dashboard generation reads this dataset and must not be able to corrupt it."""
    repo.append_rows("alpha", [{"a": 1}])

    returned = repo.get_rows("alpha")
    returned[0]["a"] = 999
    returned.append({"a": 2})

    assert repo.get_rows("alpha") == [{"a": 1}]
    assert repo.count_rows("alpha") == 1


def test_each_read_returns_independent_copies(repo: InMemoryRepository) -> None:
    repo.append_rows("alpha", [{"a": 1}])

    first, second = repo.get_rows("alpha"), repo.get_rows("alpha")

    assert first == second
    assert first[0] is not second[0]


def test_mutating_the_returned_name_lists_does_not_change_the_store(
    repo: InMemoryRepository,
) -> None:
    repo.save_schema("alpha", {})
    repo.save_dashboard("alpha-view", {})

    repo.list_schemas().append("injected")
    repo.list_dashboards().append("injected")

    assert repo.list_schemas() == ["alpha"]
    assert repo.list_dashboards() == ["alpha-view"]
