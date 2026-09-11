# REQUIREMENTS — Schema-Driven Dashboard Platform

Implementation specification. Every requirement has an ID, an acceptance criterion, and a home
in the module tree. Implement in the order given in `TASKS.md`.

**Source:** Bank of America Round 1 assignment brief.
**Stack:** Python 3.11+, FastAPI, in-memory storage, no database.

---

## 0. The governing constraint

> Build a generic platform whose behaviour is controlled through configuration.

Restated as a hard rule that overrides every other requirement:

**RULE-0 — No use-case-specific code.** No identifier, branch, class, or string literal anywhere
in `backend/` may reference `trade`, `customer`, `tradeId`, `amount`, or any other domain concept.
Domain names exist only in runtime data. A grep for `trade` across `backend/` must return zero hits.

If a requirement below appears to conflict with RULE-0, RULE-0 wins and the requirement is
misread.

---

## 1. Domain model

### FR-1 — Schema registration

**Endpoint:** `POST /schema`

**Request:**

```json
{
  "name": "trade",
  "fields": [
    { "name": "tradeId", "type": "string", "required": true },
    { "name": "amount",  "type": "number", "required": true, "aggregation": "sum" },
    { "name": "status",  "type": "string" }
  ]
}
```

| ID | Requirement | Acceptance criterion |
|---|---|---|
| FR-1.1 | A schema has a unique `name` | Two schemas may not share a name (see FR-1.8) |
| FR-1.2 | A schema has a non-empty `fields` array | Empty `fields` → `422` |
| FR-1.3 | Each field has a `name`, unique within the schema | Duplicate field name → `422` |
| FR-1.4 | Each field has a `type` drawn from the type registry | Unknown type → `422` naming the supported types |
| FR-1.5 | Each field has an optional `required` boolean, **defaulting to `false`** | A field omitting `required` is optional |
| FR-1.6 | Each field has an optional `aggregation` string, acting as the field's *default* aggregation | Used by FR-3.7 |
| FR-1.7 | An `aggregation` declared on a field must be legal for that field's type | `"aggregation": "sum"` on a `string` field → `422` |
| FR-1.8 | Re-registering an existing schema name is rejected | → `409 Conflict`. See DECISION-2 |
| FR-1.9 | Registered schemas are held in memory | No persistence |

**Supported types** (`backend/core/types.py`, a registry not a conditional chain):

| Type | Accepts | Explicitly rejects |
|---|---|---|
| `string` | `str` | everything else, including numbers |
| `number` | `int`, `float` | `bool`, numeric strings such as `"1000"` |
| `integer` | `int` | `bool`, `float`, numeric strings |
| `boolean` | `bool` | `0`, `1`, `"true"` |

> **FR-1.10 — The `bool` trap.** In Python `isinstance(True, int)` is `True`. Every numeric type
> check must exclude `bool` explicitly. There must be a test asserting `{"amount": true}` fails
> validation against a `number` field.

**Aggregation legality by type** (`backend/core/aggregations.py`):

| Aggregation | Legal for |
|---|---|
| `sum`, `avg`, `min`, `max` | `number`, `integer` |
| `count` | any type |

---

### FR-2 — Data ingestion

**Endpoint:** `POST /ingest`

**Request:**

```json
{
  "schema": "trade",
  "rows": [
    { "tradeId": "T001", "amount": 1000, "status": "OPEN" }
  ]
}
```

| ID | Requirement | Acceptance criterion |
|---|---|---|
| FR-2.1 | `schema` must name a registered schema | Unknown schema → `404` |
| FR-2.2 | `rows` must be a non-empty array of objects | Empty array → `422` |
| FR-2.3 | Every required field must be present in every row | Missing → `MISSING_REQUIRED_FIELD` |
| FR-2.4 | Every present value must match its declared type | Mismatch → `TYPE_MISMATCH` |
| FR-2.5 | Fields not declared in the schema are rejected | Extra key → `UNKNOWN_FIELD` |
| FR-2.6 | `null` does **not** satisfy a required field | → `MISSING_REQUIRED_FIELD` |
| FR-2.7 | `null` in an optional field is accepted and stored as absent | No error |
| FR-2.8 | **Ingestion is all-or-nothing.** One invalid row rejects the entire batch; nothing is stored | See DECISION-1 |
| FR-2.9 | The error response reports **every** failing row and field, not just the first | A batch with 3 bad rows returns 3+ errors |
| FR-2.10 | Accepted rows are appended to the schema's dataset in memory | Order preserved |

**Validation failure response — `422`:**

```json
{
  "error": "VALIDATION_FAILED",
  "message": "3 of 5 rows failed validation; no rows were ingested",
  "details": [
    { "row": 1, "field": "amount",  "code": "TYPE_MISMATCH",           "expected": "number", "actual": "string" },
    { "row": 2, "field": "tradeId", "code": "MISSING_REQUIRED_FIELD" },
    { "row": 4, "field": "currency","code": "UNKNOWN_FIELD" }
  ]
}
```

`row` is a zero-based index into the submitted `rows` array.

---

### FR-3 — Dashboard configuration

**Endpoint:** `POST /dashboard`

**Request:**

```json
{
  "name": "trade-dashboard",
  "schema": "trade",
  "views": [
    { "type": "summary", "field": "amount", "aggregation": "sum" },
    { "type": "table",   "columns": ["tradeId", "amount", "status"] }
  ]
}
```

> **Note on the `schema` key.** The brief's example config omits any binding to a schema. With
> more than one schema registered, a view referencing `field: amount` cannot be resolved. Since
> supporting multiple concurrent use cases is the entire point of the platform, this is treated
> as a gap in the brief and a required `schema` key is added. **This must be called out in
> `README.md`** — noticing the gap is worth more than the fix.

| ID | Requirement | Acceptance criterion |
|---|---|---|
| FR-3.1 | A config has a unique `name` | Duplicate → `409` |
| FR-3.2 | A config has a `schema` naming a registered schema | Unknown → `404` |
| FR-3.3 | A config has a non-empty `views` array | Empty → `422` |
| FR-3.4 | Each view has a `type` present in the view registry | Unknown type → `422` listing supported types |
| FR-3.5 | **Configs are fully validated against the schema at registration time, not at render time** | See below |
| FR-3.6 | `summary` view: `field` must exist in the schema | Unknown field → `422 UNKNOWN_FIELD` |
| FR-3.7 | `summary` view: `aggregation` resolves as *view value → schema field default → error* | Neither present → `422 AGGREGATION_REQUIRED` |
| FR-3.8 | `summary` view: the resolved aggregation must be legal for the field's type | `sum` on `string` → `422 INVALID_AGGREGATION` |
| FR-3.9 | `table` view: every entry in `columns` must exist in the schema | Unknown column → `422 UNKNOWN_FIELD` |
| FR-3.10 | `table` view: `columns` must be non-empty | → `422` |
| FR-3.11 | Configs are held in memory | No persistence |

> **FR-3.5 is the highest-signal requirement in the assignment.** The brief says configs are
> merely "stored in memory", which invites a blind write. Validating referential integrity up
> front — every referenced field exists, every aggregation is type-legal — is what separates a
> platform from a dictionary. It must be a distinct, testable step.

---

### FR-4 — Dashboard generation

**Endpoint:** `GET /dashboard/{name}`

**Response:**

```json
{
  "dashboard": "trade-dashboard",
  "schema": "trade",
  "rowCount": 3,
  "views": [
    { "type": "summary", "field": "amount", "aggregation": "sum", "value": 25000 },
    { "type": "table",   "columns": ["tradeId", "amount", "status"], "rows": [ … ] }
  ]
}
```

| ID | Requirement | Acceptance criterion |
|---|---|---|
| FR-4.1 | Unknown dashboard name → `404` | |
| FR-4.2 | Resolution reads the registered schema, the ingested dataset, and the config | All three |
| FR-4.3 | Views are resolved in declaration order | Output order matches config order |
| FR-4.4 | Each view type is resolved by its registered handler; the generator contains no per-type branching | Adding a handler requires no edit to the generator |
| FR-4.5 | `summary` returns the aggregate of the field across all rows of the bound schema | |
| FR-4.6 | `table` returns rows projected to exactly the configured columns, in configured order | No extra keys |
| FR-4.7 | Missing optional values project as `null` | Not omitted — keeps rows rectangular |
| FR-4.8 | Empty dataset: `sum` → `0`, `count` → `0`, `avg`/`min`/`max` → `null`, `table` → `[]` | Must not raise |
| FR-4.9 | Generation never mutates stored data | |

---

### FR-5 — Introspection

Not requested in the brief. Added because a configuration-driven platform that cannot report its
own configuration is difficult to defend.

| ID | Endpoint | Returns |
|---|---|---|
| FR-5.1 | `GET /schema` | List of registered schema names |
| FR-5.2 | `GET /schema/{name}` | The full schema, `404` if absent |
| FR-5.3 | `GET /dashboard` | List of registered dashboard names |
| FR-5.4 | `GET /health` | `{"status": "ok"}` |

---

## 2. Non-functional requirements

| ID | Requirement |
|---|---|
| NFR-1 | **Extensible view types.** Adding a view type = adding one handler + registering it. Zero edits to existing modules. Proven by adding a third type in under 20 lines |
| NFR-2 | **Extensible aggregations.** Same property, via an aggregation registry |
| NFR-3 | **Extensible types.** Same property, via a type registry |
| NFR-4 | **Storage behind an interface.** `store/base.py` defines the contract; `store/memory.py` is the only implementation. Swapping in a database touches one file |
| NFR-5 | **One error contract** across every endpoint: `{error, message, details[]}` |
| NFR-6 | **Correct status codes** — `200` read, `201` create, `404` unknown resource, `409` duplicate, `422` validation failure |
| NFR-7 | **Layer discipline.** `api/` parses and formats only. `core/` holds all logic and imports nothing from `api/`. `store/` holds state and imports nothing from either |
| NFR-8 | **Tests** covering every validation branch and every edge case named above |
| NFR-9 | **Type hints** throughout; the codebase should read as production Python |

---

## 3. Out of scope

Named by the brief as not expected. Implementing these is a scope error, not credit:
authentication, authorization, databases, production deployment, LLM integrations, advanced
visualisations.

Also deliberately excluded: filtering, grouping, sorting, pagination, schema versioning,
concurrency control. Each is listed in `README.md` as an extension point with a one-line note on
how the registries accommodate it.

---

## 4. Bonus — minimal UI

`frontend/index.html`. Single static file, no build step, no dependencies, no framework. Opens by
double-click or is served by FastAPI at `/`.

| ID | Requirement |
|---|---|
| BR-1 | Register a schema from a JSON textarea |
| BR-2 | Submit rows from a JSON textarea |
| BR-3 | Register a dashboard config from a JSON textarea |
| BR-4 | Fetch and render a dashboard: summary views as value cards, table views as HTML tables |
| BR-5 | Surface API validation errors verbatim — this is a debugging surface, not a product |

Textareas prefilled with working examples so a grader can click through in 30 seconds.

---

## 5. Deliverables

| File | State |
|---|---|
| `README.md` | Skeleton present — fill last |
| `AI_REPORT.md` | Skeleton present — **max 1 page**. Fill from `DECISIONS.md` |
| `backend/` | Stubs present |
| `frontend/` | Stub present |
| `tests/` | Stubs present |

`AI_REPORT.md` must cover: AI tools used · example prompts · **one suggestion accepted** · **one
suggestion rejected** · how the solution was validated. It is one of five evaluation criteria.
Log decisions in `DECISIONS.md` as they happen; reconstructing a plausible rejection afterwards
reads as invented, and it usually is.

---

## 6. Definition of done

The assignment is complete when this passes:

```
1. POST /schema      { "name": "customer", "fields": [customerId, name, country] }
2. POST /ingest      3 customer rows
3. POST /dashboard   { "name": "customer-dashboard", "schema": "customer",
                       "views": [ {summary, count}, {table, [customerId, name, country]} ] }
4. GET  /dashboard/customer-dashboard   → correct output
```

…with **zero lines of `backend/` changed** since the `trade` use case worked, and with both
dashboards live and correct simultaneously.

`tests/test_genericity.py` should assert exactly this.
