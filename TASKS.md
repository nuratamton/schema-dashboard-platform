# TASKS — ordered implementation plan

Twelve tasks, bottom-up. Each is one Claude Code session: implement, test, commit, stop.

Order matters — every task depends only on the ones above it, so nothing is ever stubbed twice.

A suggested prompt is given for each. `REQUIREMENTS.md` is the spec; `CLAUDE.md` is the
standing context.

---

## Phase 1 — Foundations

### ☐ T1 — Storage layer
**Files:** `backend/store/base.py`, `backend/store/memory.py`
**Requirements:** NFR-4, FR-1.9, FR-2.10, FR-3.11
**Tests:** `tests/test_store.py`

Repository interface as an ABC: save/get/exists/list for schemas, dashboards, and row datasets.
In-memory implementation backed by dicts. No FastAPI imports. No domain knowledge.

> Implement T1 from TASKS.md. Read REQUIREMENTS.md sections FR-1.9, FR-2.10, FR-3.11 and NFR-4
> first. Define the repository interface in store/base.py as an ABC and the in-memory
> implementation in store/memory.py. Write tests/test_store.py alongside. Do not touch any other
> file.

---

### ☐ T2 — Error contract
**Files:** `backend/core/errors.py`
**Requirements:** NFR-5, NFR-6

Error code enum (`TYPE_MISMATCH`, `MISSING_REQUIRED_FIELD`, `UNKNOWN_FIELD`, `UNKNOWN_SCHEMA`,
`UNKNOWN_FIELD`, `INVALID_AGGREGATION`, `AGGREGATION_REQUIRED`, `DUPLICATE_NAME`, …), a
`ValidationIssue` dataclass (`row`, `field`, `code`, `expected`, `actual`), and the exception
types the API layer maps to status codes.

> Implement T2 from TASKS.md. Define the single error contract described in REQUIREMENTS.md
> NFR-5 and the FR-2 error response example. Nothing else.

---

### ☐ T3 — Type registry
**Files:** `backend/core/types.py`
**Requirements:** FR-1.4, FR-1.10, NFR-3
**Tests:** `tests/test_types.py`

A registry mapping type name → checker. `string`, `number`, `integer`, `boolean`. Strict: no
coercion.

> Implement T3 from TASKS.md. Read the type table in REQUIREMENTS.md FR-1. Build it as a
> registry, not an if/elif chain — adding `date` later must be a one-line registration. Write
> tests/test_types.py covering every accept and reject in that table, and include an explicit
> test that `True` fails the `number` check (Python's bool/int trap, FR-1.10).

---

### ☐ T4 — Aggregation registry
**Files:** `backend/core/aggregations.py`
**Requirements:** NFR-2, FR-1.7, FR-3.8, FR-4.8
**Tests:** `tests/test_aggregations.py`

`sum`, `avg`, `min`, `max`, `count`. Each declares which types it is legal for. Each defines its
empty-dataset result.

> Implement T4 from TASKS.md. Registry pattern, same shape as the type registry. Each
> aggregation declares its legal field types and its empty-input result per FR-4.8. Tests must
> cover the empty-dataset behaviour for all five.

---

## Phase 2 — Schema and validation

### ☐ T5 — Schema models and registration logic
**Files:** `backend/core/models.py`, schema half of `backend/core/validation.py`
**Requirements:** FR-1.1 → FR-1.8
**Tests:** `tests/test_schema.py`

Pydantic models for the schema payload. Registration-time checks: unique field names, known
types, aggregation legal for field type, `required` defaults to `false`.

> Implement T5 from TASKS.md. Pydantic models in core/models.py for the schema request, plus the
> schema-registration validation in core/validation.py. Cover FR-1.1 through FR-1.8. Note
> FR-1.5: `required` defaults to false when omitted.

---

### ☐ T6 — Row validation engine
**Files:** `backend/core/validation.py`
**Requirements:** FR-2.3 → FR-2.9
**Tests:** `tests/test_validation.py`

Takes a schema and a list of rows, returns a list of `ValidationIssue`. Required present, types
match, unknown fields rejected, null semantics, **all** issues collected across **all** rows.

> Implement T6 from TASKS.md — the row validation engine, REQUIREMENTS.md FR-2.3 to FR-2.9.
> Important: rows arrive as plain dicts and are validated by this engine, NOT by Pydantic —
> Pydantic would coerce "1000" to 1000. Collect every issue across every row; do not stop at the
> first. Tests must cover: missing required, type mismatch per type, unknown field, null in
> required, null in optional, and a multi-error batch.

---

## Phase 3 — Dashboards

### ☐ T7 — View handler registry
**Files:** `backend/core/views.py`
**Requirements:** NFR-1, FR-3.6 → FR-3.10, FR-4.5 → FR-4.7
**Tests:** `tests/test_views.py`

Each handler exposes two operations: **validate** (config against schema, at registration time)
and **resolve** (config + rows → output). `summary` and `table`.

> Implement T7 from TASKS.md. Each view handler needs both a validate(config, schema) and a
> resolve(config, rows) method, registered by type name. Implement `summary` and `table` per
> FR-3.6–3.10 and FR-4.5–4.7. The registry must make a third view type a pure addition.

---

### ☐ T8 — Dashboard config validation
**Files:** `backend/core/dashboards.py`
**Requirements:** FR-3.1 → FR-3.11
**Tests:** `tests/test_dashboard_config.py`

Validates the whole config against the bound schema **at registration time** by delegating to
each view handler's validate. Resolves the aggregation precedence chain.

> Implement T8 from TASKS.md — dashboard config validation, FR-3.1 to FR-3.11. This is the
> highest-signal requirement in the assignment: configs are fully validated against the schema at
> REGISTRATION time, not render time. Include the aggregation precedence chain from FR-3.7 (view
> value → schema field default → error). Tests must prove that a config naming a nonexistent
> field is rejected by POST /dashboard, not later by GET.

---

### ☐ T9 — Dashboard generation
**Files:** `backend/core/dashboards.py`
**Requirements:** FR-4.1 → FR-4.9
**Tests:** `tests/test_dashboard_generation.py`

Loads schema + rows + config, dispatches each view to its handler, assembles the response. No
per-type branching in this module.

> Implement T9 from TASKS.md — dashboard generation, FR-4.1 to FR-4.9. Dispatch through the view
> registry; there must be no if/elif on view type in this module. Tests must include the empty
> dataset case (FR-4.8) and confirm generation does not mutate stored rows.

---

## Phase 4 — API and delivery

### ☐ T10 — API layer
**Files:** `backend/main.py`, `backend/api/*.py`
**Requirements:** FR-1, FR-2, FR-3, FR-4, FR-5, NFR-6, NFR-7
**Tests:** `tests/test_api.py`

All seven endpoints. Routes parse and delegate only. Exception handlers map core exceptions to
status codes and the single error contract. Override FastAPI's default `422` body.

> Implement T10 from TASKS.md — the FastAPI layer. All endpoints in REQUIREMENTS.md FR-1 to
> FR-5. Routes must contain no logic: parse, delegate to core, format. Add exception handlers in
> main.py mapping core exceptions to the error contract, including an override of FastAPI's
> RequestValidationError handler so its 422 body matches ours. Tests with TestClient covering
> every status code in NFR-6.

---

### ☐ T11 — Genericity acceptance test
**Files:** `tests/test_genericity.py`
**Requirements:** RULE-0, section 6

The test that decides whether the assignment is solved. Runs `trade` and `customer` end to end
in the same app instance, concurrently.

> Implement T11 from TASKS.md. Write tests/test_genericity.py per REQUIREMENTS.md section 6: run
> the trade use case and an entirely different customer use case end to end in one app instance,
> concurrently, asserting both dashboards return correct output. Add a test that greps backend/
> for domain terms and asserts zero hits.

---

### ☐ T12 — Minimal UI
**Files:** `frontend/index.html`
**Requirements:** BR-1 → BR-5

One static file. Four panels, prefilled with working examples. No build step, no framework.

> Implement T12 from TASKS.md — the bonus UI, REQUIREMENTS.md section 4. A single self-contained
> index.html: no framework, no build step, no CDN. Four panels (register schema, ingest, register
> dashboard, view dashboard), each prefilled with a working example so a grader can click
> straight through. Render summary views as value cards and table views as HTML tables. Show API
> errors verbatim. Serve it from FastAPI at `/`.

---

## Phase 5 — Documentation

### ☐ T13 — README
**File:** `README.md`

Setup, API reference, architecture, **the design decisions and why**, the spec gaps found and
how they were resolved, extension points, what was deliberately left out.

> Fill in README.md. Read DECISIONS.md first. The design-decisions section matters most — the
> panel discussion is about reasoning, not code. Lead the spec-gaps section with the missing
> schema binding in the dashboard config example.

### ☐ T14 — AI report
**File:** `AI_REPORT.md`

**Maximum one page.** Written from `DECISIONS.md`.

> Fill in AI_REPORT.md from DECISIONS.md. Hard limit: one page. Cover AI tools used, example
> prompts, one suggestion accepted, one suggestion rejected with the reasoning, and how the
> solution was validated. Use real entries from the log — do not invent a rejection.

---

## Progress

| Phase | Tasks | Done |
|---|---|---|
| 1 Foundations | T1–T4 | ☐☐☐☐ |
| 2 Schema & validation | T5–T6 | ☐☐ |
| 3 Dashboards | T7–T9 | ☐☐☐ |
| 4 API & delivery | T10–T12 | ☐☐☐ |
| 5 Documentation | T13–T14 | ☐☐ |
