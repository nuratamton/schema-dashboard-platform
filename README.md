# Schema-Driven Dashboard Platform

Register a data schema, ingest rows validated against it, register a dashboard configuration, and
generate the dashboard. Adding a new use case is configuration only — there is no
use-case-specific code anywhere in `backend/`, and multiple use cases run concurrently in one
process.

## Quick start

```bash
pip install -r requirements.txt
uvicorn backend.main:app --reload
```

- UI: http://127.0.0.1:8000/
- API docs: http://127.0.0.1:8000/docs

```bash
pytest -q          # 529 tests
```

Python 3.11+. Dependencies: FastAPI, uvicorn, Pydantic, pytest, httpx. No database, no build step.

The UI is served by the app at `/`. Opening `frontend/index.html` off disk does not work — over
`file://` the page's origin is `null`, so every `fetch` is cross-origin.

## Example

```bash
# 1. Register a schema
curl -X POST localhost:8000/schema -H 'Content-Type: application/json' -d '{
  "name": "trade",
  "fields": [
    { "name": "tradeId", "type": "string", "required": true },
    { "name": "amount",  "type": "number", "required": true, "aggregation": "sum" },
    { "name": "status",  "type": "string" }
  ]
}'

# 2. Ingest rows — validated against the schema, all-or-nothing
curl -X POST localhost:8000/ingest -H 'Content-Type: application/json' -d '{
  "schema": "trade",
  "rows": [
    { "tradeId": "T001", "amount": 10000, "status": "OPEN" },
    { "tradeId": "T002", "amount": 5000,  "status": "CLOSED" },
    { "tradeId": "T003", "amount": 10000 }
  ]
}'

# 3. Register a dashboard config — validated against the schema now, not at render time
curl -X POST localhost:8000/dashboard -H 'Content-Type: application/json' -d '{
  "name": "trade-dashboard",
  "schema": "trade",
  "views": [
    { "type": "summary", "field": "amount", "aggregation": "sum" },
    { "type": "table",   "columns": ["tradeId", "amount", "status"] }
  ]
}'

# 4. Generate it
curl localhost:8000/dashboard/trade-dashboard
```

```json
{
  "dashboard": "trade-dashboard",
  "schema": "trade",
  "rowCount": 3,
  "views": [
    { "type": "summary", "field": "amount", "aggregation": "sum", "value": 25000 },
    { "type": "table", "columns": ["tradeId", "amount", "status"], "rows": [
      { "tradeId": "T001", "amount": 10000, "status": "OPEN" },
      { "tradeId": "T002", "amount": 5000,  "status": "CLOSED" },
      { "tradeId": "T003", "amount": 10000, "status": null }
    ]}
  ]
}
```

## API

| Method | Path | Purpose | Status codes |
|---|---|---|---|
| `POST` | `/schema` | Register a schema | `201` · `409` taken name · `422` invalid definition |
| `GET` | `/schema` | List registered schema names | `200` |
| `GET` | `/schema/{name}` | Return one schema | `200` · `404` |
| `POST` | `/ingest` | Validate and store rows | `201` · `404` unknown schema · `422` validation failed |
| `POST` | `/dashboard` | Register a dashboard config | `201` · `404` unknown schema · `409` taken name · `422` invalid config |
| `GET` | `/dashboard` | List registered dashboard names | `200` |
| `GET` | `/dashboard/{name}` | Generate a dashboard | `200` · `404` |
| `GET` | `/health` | Liveness | `200` |
| `GET` | `/` | The UI | `200` |

### Error contract

Every failure on every endpoint has the same shape. `details` is always present and always a
list, empty for errors about a resource rather than its contents.

```json
{
  "error": "VALIDATION_FAILED",
  "message": "1 of 1 rows failed validation; no rows were ingested",
  "details": [
    { "row": 0, "field": "amount", "code": "TYPE_MISMATCH", "expected": "number", "actual": "string" },
    { "row": 0, "field": "currency", "code": "UNKNOWN_FIELD" }
  ]
}
```

FastAPI's default `422` body does not match this, so its `RequestValidationError` handler is
overridden. The fifteen error codes are listed in `REQUIREMENTS.md`.

## Architecture

```
backend/
  main.py            FastAPI app, router wiring, exception handlers
  api/               Transport only — parse, delegate, format. No logic.
    dependencies.py  Repository provider (Depends), overridden in tests
    schemas.py       POST /schema, GET /schema, GET /schema/{name}
    ingest.py        POST /ingest
    dashboards.py    POST /dashboard, GET /dashboard, GET /dashboard/{name}
  core/              All logic. Imports nothing from api/.
    models.py        Pydantic request models — the envelope only
    errors.py        Error codes + the single error contract
    types.py         Type registry: string, number, integer, boolean
    aggregations.py  Aggregation registry: sum, avg, min, max, count
    validation.py    Schema registration checks + row validation engine
    dashboards.py    Config validation (registration time) + generation
    views.py         View handler registry: summary, table
  store/             State. Imports nothing from api/ or core/.
    base.py          Repository interface (ABC)
    memory.py        In-memory implementation
frontend/            Vanilla HTML/CSS/JS, served at /. No build step.
```

Dependency direction is strictly `api → core → store`, asserted by a test that parses every
module's imports.

Three registries carry all the variability. A type is a name and a checker; an aggregation is a
name, a reducer, its legal field types and its empty-dataset result; a view type is a name and two
functions, `validate(config, schema)` and `resolve(config, schema, rows)`. `validate` runs at
registration, `resolve` at generation — which is why the whole of dashboard generation is:

```python
[views.get(v["type"]).resolve(v, schema, rows) for v in config.views]
```

## Behaviour worth knowing

- **Ingestion is all-or-nothing.** One invalid row rejects the batch; every failing row and field
  is reported in one response.
- **Rows are validated by our engine, not Pydantic.** Pydantic would coerce `"1000"` to `1000`.
  Type checking is strict in both directions: `5.0` is not an `integer`, and `True` satisfies no
  numeric type despite `isinstance(True, int)`.
- **Dashboard configs are validated at registration time**, not render time — every referenced
  field, aggregation and column is checked against the bound schema. `generate_dashboard` has one
  error path, `UnknownDashboard`.
- **Aggregation resolves view value → schema field default → error.** No implicit `sum`.
- **Aggregation legality is a trait on the type.** A registered type carries `numeric`;
  `aggregations.py` names no type, so a new numeric type gains all four arithmetic aggregations
  with no edit.
- **`count` means `COUNT(column)`** — aggregations read the field's non-null values. `rowCount`
  sits alongside in the response.
- **Re-registering a name is a `409`**, not an overwrite and not a new version.
- **`required` defaults to `false`** when omitted.

The brief's example dashboard config binds to no schema, so `schema` is optional and inferred only
when unambiguous. The binding is resolved once, at registration, and stored:

| `schema` key | Schemas registered | Result |
|---|---|---|
| present, known | any | bound to it |
| present, unknown | any | `404 UNKNOWN_SCHEMA` |
| omitted | 0 | `422 NO_SCHEMA_REGISTERED` |
| omitted | 1 | inferred |
| omitted | 2+ | `422 AMBIGUOUS_SCHEMA`, naming them |

Full reasoning for each of these, and the alternatives rejected, is in `DECISIONS.md`.

## Extension points

| To add | Change |
|---|---|
| A field type (`date`, `decimal`) | One `@register` in `core/types.py`; `numeric=True` makes the arithmetic aggregations legal for it |
| An aggregation (`median`, `stddev`) | One `@register` in `core/aggregations.py` with its legal types and empty-dataset result |
| A view type (`chart`, `distinct`) | One handler in `core/views.py` — `validate`, `resolve`, and a registration |
| Database persistence | One new implementation of `store/base.py`, wired in `api/dependencies.py` |

Each of the first three is proven by a test that registers a new one at runtime.

Not built, deliberately: authentication, databases, deployment, advanced visualisations (all named
out of scope by the brief), plus filtering, sorting, grouping, pagination, schema versioning,
concurrency control, caching and logging middleware.

## Tests

```bash
pytest -q                              # 529 tests
pytest tests/test_genericity.py -q     # the acceptance test
```

`test_genericity.py` runs two unrelated use cases end to end, concurrently, in one app instance,
and asserts registering the second leaves the first's output unchanged. It also invents a third
use case inside the test, guards against any use-case vocabulary appearing under `backend/`, and
checks the layering and type-hint rules.

`test_coverage.py` asserts every requirement ID in `REQUIREMENTS.md` is referenced by at least one
test, and that no test cites an ID that does not exist. The remaining files cover the type and
aggregation tables, row validation, dashboard config validation and generation, the store
contract, every status code, and the brief's own payloads replayed verbatim.

## Documents

| File | Contents |
|---|---|
| `REQUIREMENTS.md` | The specification: requirement IDs, error codes, pass condition |
| `DECISIONS.md` | Every non-obvious choice, the options weighed, and what was rejected |
| `AI_REPORT.md` | How AI tooling was used on the build |
| `TASKS.md` | The ordered implementation plan the build followed |
