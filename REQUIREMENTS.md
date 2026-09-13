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
| FR-1.1 | A schema has a unique, usable `name` | Two schemas may not share a name (see FR-1.8). A name must round-trip through a URL path: `/` or whitespace-only → `422 INVALID_NAME` (D-35) |
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
| `number` | finite `int`, `float` | `bool`, numeric strings such as `"1000"`, and `NaN` / `Infinity` (D-13) |
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

`row` is a zero-based index into the submitted `rows` array. It is omitted entirely — not sent as
`null` — where there are no rows, which is every failure outside ingestion.

**The error vocabulary.** One enum, shared by every endpoint (`core/errors.py`). *Envelope* codes
answer "what kind of failure is this" and appear as the top-level `error`; *issue* codes answer
"what specifically is wrong" and appear as `code` inside a `details[]` entry. The split is by
typical role, not a partition — `DUPLICATE_NAME` is both, at resource scope and at field scope.

| Code | Role | Status | Raised by |
|---|---|---|---|
| `VALIDATION_FAILED` | envelope | `422` | any collected validation failure — FR-1, FR-2, FR-3, and the request-envelope override |
| `UNKNOWN_SCHEMA` | envelope | `404` | FR-2.1, FR-3.2 |
| `UNKNOWN_DASHBOARD` | envelope | `404` | FR-4.1 |
| `DUPLICATE_NAME` | both | `409` / issue | FR-1.8, FR-3.1 at resource scope; FR-1.3 and repeated `table` columns at field scope |
| `AMBIGUOUS_SCHEMA` | envelope | `422` | FR-3.2 — `schema` omitted and more than one is registered, so the binding is not unique |
| `NO_SCHEMA_REGISTERED` | envelope | `422` | FR-3.2 — `schema` omitted and none is registered at all |
| `INTERNAL_ERROR` | envelope | `500` | Anything unforeseen. NFR-5's promise is only true if the unanticipated also answers in the contract (D-36) |
| `TYPE_MISMATCH` | issue | `422` | FR-2.4 — a *value* failed a type that exists |
| `MISSING_REQUIRED_FIELD` | issue | `422` | FR-2.3, FR-2.6; also "no usable value supplied" for a config key (FR-3.3, FR-3.10) |
| `UNKNOWN_FIELD` | issue | `422` | FR-2.5, FR-3.6, FR-3.9 |
| `UNKNOWN_TYPE` | issue | `422` | FR-1.4 (field type) and FR-3.4 (view type) — a *type name* the registry does not know. `expected` says which registry |
| `UNKNOWN_AGGREGATION` | issue | `422` | FR-1.7, FR-3.7 — no such aggregation |
| `INVALID_AGGREGATION` | issue | `422` | FR-1.7, FR-3.8 — it exists, but not for this field's type |
| `AGGREGATION_REQUIRED` | issue | `422` | FR-3.7 — neither the view nor the schema supplied one |
| `INVALID_NAME` | issue | `422` | FR-1.1, FR-3.1 — a name containing `/` (unfetchable: the path is decoded before routing) or only whitespace (D-35) |

Five of these were added after the vocabulary was first written, each time because one code was
being asked to mean two things, or because a failure had no code at all. `UNKNOWN_TYPE` and
`UNKNOWN_AGGREGATION` arrived once FR-1 had a real consumer: reusing `TYPE_MISMATCH` for "that type
does not exist" would be actively misleading, and "no such aggregation" and "not on this field"
send whoever wrote the schema to two different places (D-17). `INVALID_NAME` separated from
`DUPLICATE_NAME` because a client that retries a duplicate with a suffix would loop forever on an
unusable one (D-35). `INTERNAL_ERROR` exists so that NFR-5's promise covers the unanticipated too,
not only the failures that were thought of (D-36). `NO_SCHEMA_REGISTERED` split off from
`AMBIGUOUS_SCHEMA` for the same reason — nothing is ambiguous when there is nothing to choose between, and the fix is to register
a schema rather than to name one of several (D-33).

The test for whether a new code is warranted is that one: **does it send the caller somewhere
different?** If two failures have the same remedy, one code is enough.

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
> as a gap in the brief, and the config is given a `schema` key. **This must be called out in
> `README.md`** — noticing the gap is worth more than the fix.
>
> The key is **optional**, not required. Making it mandatory would have rejected the brief's own
> example payload, which is a bad answer to a gap we identified ourselves. Omitted, the binding is
> inferred when exactly one schema is registered and refused when the answer is not unique — so
> nothing is ever guessed, and the brief's example works verbatim. The binding is resolved once at
> registration and stored, so a dashboard cannot change meaning when a later schema is registered.
> See D-22 and D-23. The example above shows the key present, which is the form to prefer when
> more than one use case is live.

| ID | Requirement | Acceptance criterion |
|---|---|---|
| FR-3.1 | A config has a unique, usable `name` | Duplicate → `409`. `/` or whitespace-only → `422 INVALID_NAME` (D-35) |
| FR-3.2 | A config *may* carry a `schema` naming a registered schema. Present but unknown → `404 UNKNOWN_SCHEMA`. Omitted: inferred when exactly one schema is registered; `422 AMBIGUOUS_SCHEMA` naming the candidates when more than one is; `422 NO_SCHEMA_REGISTERED` when none is. The resolved name is stored, so the binding never changes later | Present+known → bound; present+unknown → `404`; omitted+0 → `422 NO_SCHEMA_REGISTERED`; omitted+1 → inferred; omitted+n → `422 AMBIGUOUS_SCHEMA`. See D-22, D-23, D-33 |
| FR-3.3 | A config has a non-empty `views` array | Omitted or empty → `422` carrying `MISSING_REQUIRED_FIELD` on `views` in `details`. Unlike FR-1.2 this is **not** an envelope rejection: every FR-3 problem is reported in one collected response |
| FR-3.4 | Each view has a `type` present in the view registry, and no keys its handler does not declare | Unknown view type → `422` listing supported types. Unknown config key → `422 UNKNOWN_FIELD` at `views[n].<key>` (D-34) |
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

## 4. Bonus — the UI

`frontend/` — `index.html`, `styles.css`, `app.js`, and two self-hosted variable fonts. Vanilla:
no build step, no framework, no npm install, no CDN. **Served by FastAPI at `/`** (the app mounts
`frontend/` at `/static`) — open `http://127.0.0.1:8000/`, not the file on disk.

> Double-clicking the file does not work, and the reason is worth stating rather than leaving a
> grader to discover. Over `file://` the page's origin is `null`, so every `fetch` to the API is
> cross-origin and fails. The fix for that would be CORS middleware, which the brief does not ask
> for; serving the file from the app removes the cause instead of configuring around it. See D-31.

The brief's Bonus section asks for four things and names no constraints on how: *register schemas,
submit data, register dashboard configurations, view generated dashboard data*. This section's
earlier single-file, JSON-textarea specification was an elaboration of the brief, not the brief.
It was lifted at D-38; these are the four operations as built.

| ID | Requirement |
|---|---|
| BR-1 | Register a schema by building its fields in a form: name, type, required, default aggregation. The type and aggregation controls are built from the registries, so an illegal pairing cannot be constructed from the form — an aggregation a type cannot carry is shown with the reason and left unselectable (D-55) |
| BR-2 | Submit rows in a grid whose columns *are* the registered schema's fields, each cell typed by its field's declared type |
| BR-3 | Register a dashboard config by choosing views and picking fields from the bound schema. The `schema` key may be left blank, and the UI states what blank will do at the current registration count (inferred / `AMBIGUOUS_SCHEMA` / `NO_SCHEMA_REGISTERED`) |
| BR-4 | Fetch and render a dashboard: summary views as a determinations table, table views as results tables. No charts — the brief lists advanced visualisations as out of scope |
| BR-5 | Surface API validation errors: every failure is read back in plain language, one sentence per `details[]` entry, ending in the fix. The **verbatim** body — envelope code, message, and every entry with its `row`, `field`, `code`, `expected` and `actual` — stays one disclosure away, so nothing in the contract is reachable only by paraphrase (D-54) |
| BR-6 | Every write panel keeps a raw-JSON view of the exact request body, so the API shape stays visible |

Forms are prefilled with the brief's own example payloads, and the schema draft propagates live
into the intake grid and the config builder, so a grader can click straight down the page. BR-5 is
reached the way anyone reaches it — by getting something wrong, or by editing a payload in the
raw-JSON view BR-6 keeps on every panel. There is no button that fails on purpose; see D-57.

`tests/test_coverage.py` deliberately excludes `BR-*` from its assertion (see its module
docstring): these are UI requirements, and the test suite covers the API.

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
