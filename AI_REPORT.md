# AI Report

## Tools used

**Claude (web)** — Used to create`REQUIREMENTS.md` (numbered
requirements, each with an acceptance criterion) and `TASKS.md` (fourteen ordered tasks, each
naming its files, requirement IDs and tests). This is where the gaps in the brief were found — the
example dashboard config binds to no schema, unresolvable once two schemas are registered (D-22).

**Claude Code (terminal)** — one task per session against that spec, with `CLAUDE.md` as standing
context. Implement, test, log the decision, stop. No session implemented ahead.

The ordering is the point: the specification and the pass condition existed before the first line
of code.

## Example prompts

Structural, before implementation:

> Decompose this brief into numbered, individually testable requirements with acceptance
> criteria. Flag anything the brief leaves ambiguous rather than resolving it silently.

Implementation (T6, verbatim from `TASKS.md`):

> Implement T6 — the row validation engine, FR-2.3 to FR-2.9. Important: rows arrive as plain
> dicts and are validated by this engine, NOT by Pydantic — Pydantic would coerce "1000" to 1000.
> Collect every issue across every row; do not stop at the first.

Adversarial, after the suite was green:

> This is finished and all tests pass. Attack it. Find the inputs where it silently accepts bad
> data or returns something the error contract does not define. Rank by severity.

The third produced four real defects (D-34 to D-37) and reversed one decision.

## A suggestion I accepted

D-15 rejected Pydantic `Literal` types for `type` and `aggregation`: hardcoding the registry's
contents in `models.py` is the coupling NFR-3 exists to forbid. The cost was a worse `/docs` page,
and I paid it twice (D-25).

Claude proposed a third option I had not considered — a `json_schema_extra` **callable** reading
`types.supported_types()` at schema-generation time. `/docs` now lists the supported types as an
enum while no type name appears in `models.py`: registering a `date` type at runtime still
requires zero edits there, and `/docs` picks it up. It recovered the documentation argument for
`Literal` without `Literal` (D-27).

## A suggestion I rejected

Opened off disk the UI's origin is `null`, so every `fetch` to the API is cross-origin and fails.
The suggestion was CORS middleware. It is the reflex fix and it works.

I served `frontend/` from FastAPI instead — four lines, same-origin, problem gone (D-31). CORS
middleware means shipping a permissive cross-origin policy to solve a problem created entirely by
how a file was opened. Removing the cause beats configuring around it, and an unrequested
security-relevant default is the wrong thing to hand a bank.

## How I validated the solution

In order of strength:

1. **`tests/test_genericity.py`** — a second, unrelated use case (`customer`) end to end in the
   same app instance as `trade`, both dashboards live and correct simultaneously, zero lines of
   `backend/` changed. This is the definition of done.
2. **Two guard tests** — RULE-0 asserts no domain vocabulary appears anywhere in `backend/`;
   `test_coverage.py` asserts every requirement ID is referenced by some test, and by more than
   the guard itself. The second caught a mistyped ID on its first run.
3. **529 tests written from the requirements, not the implementation** — the `bool`/`number`
   trap, `"1000"` against `number`, `null` in required vs optional, empty-dataset aggregations,
   multi-error batches.
4. **The adversarial pass**, which falsified a decision I had reasoned my way into. D-13 accepted
   `NaN` because its consequence would be *visible*. It is not: FastAPI's encoder turns `NaN` into
   `null`, and `null` is exactly what FR-4.8 reserves for "no data" — the dashboard reported an
   empty result over a non-empty dataset. Reversed, and recorded as a reversal rather than quietly
   corrected.

AI wrote most of this code. The pass condition was defined before the code existed, and the tests
were derived from the requirements rather than from what was built.
