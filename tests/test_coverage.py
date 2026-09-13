"""Traceability guard. COVERAGE.md Part B2.

Asserts that every requirement ID in REQUIREMENTS.md is referenced by at least
one test. The cost is one comment per test -- `# FR-2.4` beside the assertion --
and in exchange "have I covered everything" becomes `pytest` rather than a
feeling at midnight.

It is deliberately a *reference* check, not a proof of adequacy: a comment says
which requirement a test is about, it cannot say the test is any good. What it
does catch, reliably, is the requirement nobody wrote a test for at all -- which
is the failure that actually happens.

BR-* is excluded. The bonus UI requirements (REQUIREMENTS.md section 4) are
verified by clicking through `frontend/index.html`, which arrives at T12; a
static file with no build step has nothing pytest can meaningfully assert about
it. COVERAGE.md Part A rows 31-34 track them as manual checks.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "REQUIREMENTS.md"
TESTS = ROOT / "tests"
GUARD = Path(__file__).resolve()

#: Matches FR-1, FR-1.10, NFR-4. BR-* is deliberately absent -- see the module
#: docstring.
REQUIREMENT_ID = re.compile(r"\b(?:FR|NFR)-\d+(?:\.\d+)?\b")


def ids_in(text: str) -> set[str]:
    return set(REQUIREMENT_ID.findall(text))


def specified() -> set[str]:
    return ids_in(SPEC.read_text())


def referenced(include_guard: bool = True) -> set[str]:
    return ids_in(
        "\n".join(
            path.read_text()
            for path in sorted(TESTS.rglob("*.py"))
            if include_guard or path.resolve() != GUARD
        )
    )


def test_the_spec_yields_requirement_ids() -> None:
    """Guards the guard: a regex that matches nothing passes everything."""
    ids = specified()

    assert len(ids) > 40, f"only extracted {len(ids)} ids from REQUIREMENTS.md"
    assert {"FR-1.10", "FR-2.8", "FR-3.5", "FR-4.9", "NFR-1"} <= ids


def test_every_requirement_is_referenced_by_a_test() -> None:
    """NFR-8: tests covering every validation branch and edge case named above."""
    missing = sorted(specified() - referenced())

    assert not missing, (
        f"{len(missing)} requirements have no test referencing them: {missing}"
    )


def test_no_test_references_a_requirement_that_does_not_exist() -> None:
    """The other direction: a mistyped id -- a trailing digit, a renumbered
    section -- would otherwise read as coverage while pointing at nothing."""
    invented = sorted(referenced() - specified())

    assert not invented, f"tests reference non-existent requirements: {invented}"


def test_no_requirement_is_covered_only_by_this_guard() -> None:
    """The guard must not vouch for itself.

    Requirement ids appear in this file too -- in the sanity check above and in
    this docstring's neighbours -- and those must not be what makes a requirement
    look covered. Every id has to be referenced by a test that actually exercises
    the behaviour, with one honest exception: NFR-8 asks for tests covering every
    branch and edge case, and this file is that test.
    """
    only_here = sorted(specified() - referenced(include_guard=False))

    assert only_here == ["NFR-8"], (
        "these requirements are referenced only by the coverage guard, "
        f"not by any test of the behaviour: {[i for i in only_here if i != 'NFR-8']}"
    )
