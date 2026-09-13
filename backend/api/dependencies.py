"""Shared route dependencies.

The repository is reached through :func:`get_repository` rather than imported
directly, so that a caller can substitute one. Production wiring picks the single
process-lifetime store below; a test overrides the provider through
``app.dependency_overrides`` and gets an empty store per test.

That indirection is the whole reason NFR-4 asks for a storage interface: swapping
``InMemoryRepository`` for a database implementation is an edit to this file and
nowhere else.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from backend.store.base import Repository
from backend.store.memory import InMemoryRepository

__all__ = ["RepositoryDep", "get_repository"]


_repository: Repository = InMemoryRepository()
"""The process-lifetime store. In-memory by requirement -- no persistence."""


def get_repository() -> Repository:
    """Provide the repository. Overridden wholesale in tests."""
    return _repository


RepositoryDep = Annotated[Repository, Depends(get_repository)]
"""Spelled once so the routes read as declarations rather than as wiring."""
