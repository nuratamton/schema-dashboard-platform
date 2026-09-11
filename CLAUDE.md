# CLAUDE.md

Context for Claude Code working in this repository.

## What this is

An interview take-home: a **schema-driven dashboard platform**. A generic backend where all
use-case-specific behaviour lives in runtime configuration rather than code.

`REQUIREMENTS.md` is the specification. `TASKS.md` is the ordered implementation plan. Work one
task at a time.

## The rule that overrides everything

**No domain-specific code.** `grep -ri "trade\|customer\|tradeId\|amount" backend/` must return
zero hits. Domain names appear only in runtime data, tests, and documentation. If an
implementation seems to need a branch on a schema name, the design is wrong — fix the design.

## Working agreement

- **One task per session.** Implement the numbered task from `TASKS.md`, run its tests, stop.
  Do not implement ahead.
- **Tests are written with the code, not after.** Each task names the tests it must satisfy.
- **Do not add features that are not in `REQUIREMENTS.md`.** No filtering, sorting, pagination,
  caching, auth, logging middleware, or Docker. Section 3 lists what is deliberately excluded.
  Scope discipline is being graded; unrequested features read as poor judgement, not initiative.
- **Append to `DECISIONS.md`** whenever a non-obvious choice is made, whenever a suggestion is
  rejected, and whenever an alternative was seriously considered. `AI_REPORT.md` is written from
  that log and is a graded deliverable.
- **Stubs are stubs.** Every file in `backend/` currently contains a docstring and `TODO`
  markers referencing requirement IDs. Replace them; keep the ID references in comments.

## Architecture

```
backend/
  main.py            FastAPI app, router wiring, exception handlers
  api/               Transport only — parse, delegate, format. No logic.
    schemas.py       POST /schema, GET /schema, GET /schema/{name}
    ingest.py        POST /ingest
    dashboards.py    POST /dashboard, GET /dashboard, GET /dashboard/{name}
  core/              All logic. Imports nothing from api/.
    models.py        Pydantic request/response models
    errors.py        Error codes + the single error contract
    types.py         Type registry: string, number, integer, boolean
    aggregations.py  Aggregation registry: sum, avg, min, max, count
    validation.py    Row-against-schema validation engine
    dashboards.py    Config validation (registration time) + generation
    views.py         View handler registry: summary, table
  store/             State. Imports nothing from api/ or core/.
    base.py          Repository interface (ABC)
    memory.py        In-memory implementation
```

Dependency direction is strictly `api → core → store`. Never the reverse.

## Design decisions already made

These are settled. Do not relitigate them mid-implementation; if one turns out to be wrong,
change it deliberately and record the change in `DECISIONS.md`.

| # | Decision |
|---|---|
| 1 | Ingestion is all-or-nothing — one bad row rejects the batch |
| 2 | Re-registering a schema name returns `409`; no versioning |
| 3 | Dashboard configs carry an explicit `schema` key (the brief's example omits it — a gap) |
| 4 | Aggregation resolves view value → schema field default → error |
| 5 | Configs are validated against the schema at registration time, not at render time |
| 6 | `required` defaults to `false` when omitted |
| 7 | Type checking is strict — no coercion, `bool` never satisfies a numeric type |

## Traps

- `isinstance(True, int)` is `True` in Python. Every numeric check must exclude `bool` explicitly.
- Pydantic will happily coerce `"1000"` into `1000` if you let it model the row payloads. Rows
  must arrive as `dict[str, Any]` and be validated by **our** engine, not by Pydantic. Pydantic
  validates the envelope (`schema`, `rows`); it does not validate row contents.
- Empty dataset aggregations must not raise. `sum` → `0`, `avg`/`min`/`max` → `null`.
- FastAPI's default `422` body does not match our error contract. Override the
  `RequestValidationError` handler in `main.py`.

## Commands

```bash
pip install -r requirements.txt
uvicorn backend.main:app --reload     # docs at http://127.0.0.1:8000/docs
pytest -q
pytest tests/test_genericity.py -q    # the acceptance test that matters
```

## Definition of done

`tests/test_genericity.py` passes: a second, entirely different use case works end to end with
zero changes to `backend/`.
