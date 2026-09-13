# Schema-Driven Dashboard Platform

A generic platform for registering data schemas, ingesting validated data, configuring
dashboards, and generating dashboard output — where adding a new use case requires configuration
only, never code.

There is no use-case-specific code anywhere in `backend/`. `grep -ri trade backend/` returns
nothing. Trade and Customer are both supported by configuration alone, concurrently, in one
process.

---

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

Python 3.11+. Five dependencies: FastAPI, uvicorn, Pydantic, pytest, httpx. No database, no
build step, no CDN.

> The UI is served by the app at `/`. Opening `frontend/index.html` off disk does **not** work:
> over `file://` the page's origin is `null`, so every `fetch` is cross-origin. The fix for that
> would be CORS middleware the brief never asked for; serving the file same-origin removes the
> cause instead.

---

## Try it in 60 seconds

Paste these in order against a running server.

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

# 3. Register a dashboard config — fully validated against the schema now, not at render time
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

Two things to notice. The third row omitted `status`, and it comes back as `null` rather than
being dropped — rows stay rectangular. And step 3's `schema` key can be omitted entirely, which
is how the assignment brief writes it; see [Gaps in the specification](#gaps-in-the-specification).

Try breaking it — the error contract is the most informative thing here:

```bash
curl -X POST localhost:8000/ingest -H 'Content-Type: application/json' -d '{
  "schema": "trade",
  "rows": [{ "tradeId": "T004", "amount": "5000", "currency": "USD" }]
}'
```

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

`"5000"` is not a number, and both problems are reported, not just the first.

---

## The UI

`frontend/` — open `http://127.0.0.1:8000/` after starting the app. Vanilla HTML, CSS and JS in
three files plus two self-hosted variable fonts (51 KB). No build step, no framework, no npm
install, no CDN: the app serves it and it works offline.

The brief's Bonus section asks for four things — register schemas, submit data, register dashboard
configurations, view generated dashboard data — and names no constraints on how. The page presents
them as the four stages of a certificate of analysis, because that is what this platform actually
does: a schema is an acceptance specification, rows are specimens tested against it, and a
dashboard is the certificate issued at the end.

Four things are worth a grader's attention:

- **The specification propagates.** Editing a field in section 1 immediately rewrites section 2's
  column headers and section 3's field pickers, before anything is registered. The downstream
  sections are marked *provisional* and stay disabled until the schema is real. This is the whole
  claim of the platform, made visible in one gesture.
- **Errors are the design, not an afterthought.** A rejected batch is read back to the user as
  prose: what happened, what it cost, and one sentence per `details[]` entry that ends in the thing
  to do — *"sum" cannot apply to "test", which holds text. Use count instead, or change the
  parameter to a number type.* No code reaches the page. Codes are the right thing to put on the
  wire and the wrong thing to put in front of a person; the verbatim response body, envelope code
  and all, sits one disclosure away under **Technical details**, so nothing in the contract is
  reachable only by paraphrase (D-54). Where a failure has one obvious next move the panel offers
  it as a button — a taken name comes back with `Use "trade-2" instead` — and where the fix is in
  another section, the sentence says which one.
- **A form that is not filled in yet does not ask the server.** Every section runs the same
  pre-send check: blank names, duplicate parameter names, empty specimen rows, rows missing a
  required parameter, empty view lists, and tables with no columns. A name that is already
  registered is caught too, so re-registering never has to come back as a `409`. The offending
  controls are marked, nothing is sent, and the block is dashed rather than solid because dashed
  already means *nothing has been committed* elsewhere in the interface. This is skipped in JSON
  mode on purpose: the escape hatch exists so a deliberately invalid payload *can* reach the API
  when someone wants to see what the contract does with it.
- **The form cannot construct an illegal request, and says why.** Type and aggregation controls
  are built from the registries, so `UNKNOWN_TYPE` and `INVALID_AGGREGATION` are unreachable from
  the form. Every aggregation is still *offered* on every parameter — the ones a type cannot carry
  are disabled and labelled with the reason, `sum — numeric parameters only`, because a text
  parameter that lists only `count` reads as a platform with one aggregation rather than as a
  legality rule (D-55). Every panel keeps a raw-JSON view of the exact request body for the cases
  that matter.

Section 3's binding selector states what leaving `schema` blank will do at the current
registration count — inferred with one schema on file, `AMBIGUOUS_SCHEMA` with more, and
`NO_SCHEMA_REGISTERED` with none. That is the specification gap in the section below, visible in
the UI rather than only in prose.

No charts: the brief lists advanced dashboard visualisations as out of scope. Summary views render
as a determinations table, table views as results tables.


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

### One error contract

Every failure, on every endpoint, has the same shape:

```json
{ "error": "CODE", "message": "human readable", "details": [] }
```

`details` is always present and always a list, empty for errors about a resource rather than its
contents. FastAPI's default `422` body does not look like this, so its `RequestValidationError`
handler is overridden — otherwise the failure a caller meets first, a typo in the request body,
would be the only one answering in a different format.

Fifteen codes, listed in `REQUIREMENTS.md`. The test for whether a new one is warranted:
**does it send the caller somewhere different?** `UNKNOWN_AGGREGATION` ("no such aggregation")
and `INVALID_AGGREGATION` ("exists, but not on a `string` field") are separate because they have
different fixes. Envelope shape complaints all collapse to one code because they do not.

---

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
```

Dependency direction is strictly `api → core → store`, never the reverse. That is asserted, not
just intended: `test_genericity.py` parses every module's imports and fails if `core/` reaches for
`fastapi` or `api/`, or if `store/` reaches for either.

**Three registries carry all the variability.** A type is a name and a checker; an aggregation is
a name, a reducer, its legal field types and its empty-dataset result; a view type is a name and
two functions, `validate(config, schema)` and `resolve(config, schema, rows)`. Everything
use-case-specific lives in runtime data that flows through them. Adding a capability means adding
a registration, never editing a conditional.

**The two-operation view handler is the load-bearing idea.** `validate` runs when a dashboard is
registered, `resolve` when it is generated. That single split is what makes configs checkable up
front (FR-3.5) while keeping the generator free of any knowledge of view types (FR-4.4) — the
whole of dashboard generation is:

```python
[views.get(v["type"]).resolve(v, schema, rows) for v in config.views]
```

---

## Design decisions

The full log, fifty-nine entries written as the work happened, is in `DECISIONS.md` — decisions
settled before implementation, decisions taken during it, and the frontend redesign log. These are
the ones worth arguing about.

### Rows are validated by our engine, never by Pydantic

The idiomatic FastAPI move is to model row contents with Pydantic. It is wrong here, and
silently so: Pydantic coerces `"1000"` into `1000`, so FR-2.4 ("data types must match") would
pass its test while the engine did nothing. Pydantic validates the *envelope* — a schema name and
a non-empty list of objects — and rows arrive as `dict[str, Any]` for our own type registry to
check.

Type checking is strict in both directions. `"1000"` does not satisfy `number`; `5.0` does not
satisfy `integer`; and `True` does not satisfy either, despite `isinstance(True, int)` being
`True` in Python. Every numeric checker excludes `bool` explicitly, and there are tests asserting
it.

*Rejected:* modelled rows, for the reason above. This was the single most consequential thing
declined in the build.

### Ingestion is all-or-nothing

One invalid row rejects the batch; nothing is stored. The alternative — accept the good rows,
report the rest — is friendlier for bulk imports and would be right if the platform had a
retry or dead-letter path. It does not, so a partial success leaves the caller unable to say what
state the dataset is in without re-reading it.

The response reports *every* failing row and field, so one round trip is enough to fix the batch.
It also falls out cleanly in the implementation: the store is touched exactly once, after the
whole batch has passed, so atomicity needs no transaction.

*Rejected:* partial accept. Defensible, and the change is contained to one function plus its
tests if the tradeoff is ever worth revisiting.

### Configs are validated at registration time, not render time

The brief says dashboard configs are "stored in memory", which invites a blind write. Instead,
`POST /dashboard` checks full referential integrity against the bound schema: every referenced
field exists, every aggregation is legal for its field's type, every column is real and named
once.

A config referencing a field that does not exist is broken the moment it is written. Discovering
that at `GET` time pushes the failure onto whoever is *looking* at the dashboard rather than
whoever misconfigured it — and does so repeatedly, forever.

The dividend is visible in the code: `generate_dashboard` has exactly one error path,
`UnknownDashboard`. It validates nothing, because there is nothing left that can fail. A test
pulls every stored config back out and re-validates it to assert that property holds.

### Aggregation resolves view → schema default → error

`aggregation` can appear in two places: as field metadata on the schema, and on a summary view.
The view wins; the schema's is the fallback; neither present is an error.

*Rejected:* defaulting to `sum`. Convenient, and it makes a silently wrong dashboard easier to
produce than a loud failure. The precedence chain lives in one function used by both `validate`
and `resolve`, so the aggregation a dashboard reports is by construction the one its registration
was checked against.

### Aggregation legality is a trait on the type, not a list of type names

The literal reading of the spec — `sum`, `avg`, `min`, `max` are legal for `number` and
`integer` — puts those two names inside `aggregations.py`. Then registering a `decimal` type
means editing four sets in a module that has nothing to do with types, which contradicts the
extensibility property the registries exist for.

Instead a registered type carries one boolean, `numeric`, and arithmetic aggregations require it.
`aggregations.py` names no type at all. A test registers a `decimal` type at runtime and asserts
all four become legal for it with no edit anywhere.

*Rejected:* a general trait or capability system. One boolean covers the entire legality matrix
for four types; anything more is infrastructure for a requirement that does not exist.

### The store has no error vocabulary

`get_schema` on a missing name returns `None`; `save_schema` on an existing one overwrites. The
same absent key is a `404` on ingest and a `409` on registration, and only the caller knows
which. Raising from the store would also mean `store/` importing `core.errors`, which the layer
rule forbids.

The store does own one guarantee: rows are copied on the way in and on the way out, so
"generation never mutates stored data" is a property of the storage layer rather than a rule
every future caller has to remember. A shallow copy is provably enough, because every registered
type is scalar — a constraint stated explicitly in `types.py`, because registering a container
type later would quietly invalidate it.

### `count` means `COUNT(column)`, not `COUNT(*)`

A summary view over an *optional* field meets rows that do not carry it. Every aggregation reads
the same input — the field's non-null values — so `count` reports how many rows have a value.
Making it count rows regardless would make it the only aggregation whose answer ignores the field
it names, when `sum` and `avg` plainly cannot include a value that is not there. Nothing is lost:
`rowCount` sits alongside in the response, so both numbers are available.

On a required field the two readings are identical, which is exactly what makes the divergence
easy to miss in review.

### Registry names are not hard-coded into the request models

`type` and `aggregation` are plain `str` on the Pydantic models, checked against the registries
afterwards. `Literal["string", "number", ...]` looks like stronger typing and is the same
hard-coding the registries exist to avoid, just relocated — adding a type would mean editing
`models.py`.

The real argument for `Literal` was documentation: it produces a better OpenAPI schema. That
turned out not to require `Literal`. A `json_schema_extra` callable injects the live registry
contents at schema-generation time, so `/docs` lists the supported names while no name is written
down in `models.py`. A test registers a type at runtime and finds it in the generated schema.

*Still a genuine cost:* view configs. `summary` carries `field`, `table` carries `columns`, and
there is no shape common to both, so `views` is `list[dict[str, Any]]` and `/docs` cannot
describe it. A discriminated union would have put the view-type names in `models.py` and broken
the extensibility property outright.

### Re-registering a schema name is a `409`

Not an overwrite, which silently orphans already-ingested rows, and not a new version, which is a
substantial feature the brief neither asks for nor excludes. Versioning is the right production
answer and is named below as an extension point rather than built.

### A known inconsistency, left in place: FR-1.2 vs FR-3.3

Both requirements say the same kind of thing — a schema needs a non-empty `fields`, a dashboard
config needs a non-empty `views` — and they are enforced in two different places.

`fields` has `min_length=1` on the Pydantic model, so an empty array is rejected by the envelope
before any handler runs. `views` has no such constraint; an empty or omitted array is reported by
the config validator as a `MISSING_REQUIRED_FIELD` issue inside the normal collected `422`.

**The argument for the envelope:** it is the cheapest possible check, it needs no code, and it is
what Pydantic is for. Shape belongs to the model; meaning belongs to the domain. An empty list is
shape.

**The argument for collecting it:** every other problem with a dashboard config comes back in one
response listing everything wrong. An empty `views` arriving in a different format — FastAPI's
envelope path rather than the domain path — splits one endpoint's failures across two mechanisms
for no reason a caller can see.

The collected direction also turns out to be the one that preserves the ordering principle
uniformly. Registration deliberately refuses a duplicate name *before* validating the body, on
the grounds that re-registration is refused whatever the body says, so reporting problems in a
resource that cannot be created either way is noise. Envelope checks run before the route
function, so they run before that duplicate check — and the ordering silently inverts:

| Request | Result | |
|---|---|---|
| `POST /schema`, taken name + **invalid** fields | `409` | as intended |
| `POST /schema`, taken name + **empty** fields | `422` | ordering inverted |
| `POST /dashboard`, taken name + **invalid** views | `409` | as intended |
| `POST /dashboard`, taken name + **empty** views | `409` | as intended |

So `views` is the better of the two designs, and `fields` has a hole that opens only when two
independent errors combine.

**It was left as it is.** The behaviours are indistinguishable to a caller except in that one
combination — a duplicate name submitted together with an empty `fields` array, where the answer
is a well-formed `422` describing a real problem rather than a `409` describing a different real
problem. No caller is misled and nothing is unreportable. Changing it after the implementation
was complete and verified would mean touching a model, a validator and their tests to buy
consistency and nothing else, and a change whose entire justification is symmetry is a poor
trade against the risk of making a working, tested path worse. It is recorded here rather than
quietly evened out, because an inconsistency you can explain is a smaller problem than one you
cannot see.

---

## Gaps in the specification

### The dashboard config binds to no schema — found, closed, reopened, hardened

This is the most interesting thing in the brief, and the resolution took three passes. The arc
matters more than the endpoint: a decision tested against reality twice is worth more than either
end of it on its own.

**The gap.** The brief's example dashboard config is:

```json
{
  "name": "trade-dashboard",
  "views": [
    { "type": "summary", "field": "amount", "aggregation": "sum" },
    { "type": "table",   "columns": ["tradeId", "amount", "status"] }
  ]
}
```

There is no binding to a schema anywhere in it. With one schema registered that is merely
implicit; with two, `field: amount` cannot be resolved at all. On an assignment whose entire
premise is supporting multiple concurrent use cases, the example config cannot express which use
case it belongs to.

**First pass — closed it strictly.** A required `schema` key. Unambiguous, and it rejects
nothing that matters, because a config that cannot name its schema is a config that cannot be
rendered. Inferring the binding from which field names a config mentions was considered and
rejected outright: it is guesswork, and it breaks the moment two schemas share a field name.

**Second pass — reopened it.** Writing the test that replays the brief's payloads verbatim made
the cost visible. A required key rejects the brief's own example with a `422`. That is a poor
answer to a gap we identified ourselves: the first thing a reader of the brief will do is paste
that config in, and telling them it is malformed makes the observation look like an excuse for
an incompatibility.

So the key became optional, with the binding inferred **only when it is unambiguous** — exactly
one schema registered. More than one, and the request is refused with `AMBIGUOUS_SCHEMA` naming
the candidates. This keeps everything the strict version was protecting: nothing is ever guessed
where more than one answer is possible. The rejected option was inferring from *field names*, and
that is still rejected. And it is a better answer for a discussion, because the failure can be
demonstrated live by registering a second schema.

**Third pass — hardened it.** The reopened version had a bug that the strict version could not
have had. If the store keeps the config as submitted, the inference has to run again at `GET`
time — so a dashboard registered while one schema existed would start returning
`AMBIGUOUS_SCHEMA` the moment somebody registered an unrelated second schema. A working dashboard
broken by a change with nothing to do with it, and precisely the render-time failure that
validating configs up front exists to prevent.

The fix: resolve the binding once, at registration, and store the resolved name. A config posted
without a `schema` key is echoed back carrying the one it was bound to, and generation never
infers anything. A test registers a dashboard by inference, registers a second schema, and
asserts the first is untouched.

A fourth, smaller correction followed. Both ways inference could fail originally returned
`AMBIGUOUS_SCHEMA`, including the case where *no* schemas are registered — where the word
misdescribes the failure, since there is nothing to be ambiguous between. That case is now
`NO_SCHEMA_REGISTERED`, and it is not a theoretical edge: it is what happens the first time
anyone posts a dashboard before posting a schema, which the UI's four numbered panels make easy
to do out of order.

| `schema` key | Schemas registered | Result |
|---|---|---|
| present, known | any | bound to it |
| present, unknown | any | `404 UNKNOWN_SCHEMA` |
| omitted | 0 | `422 NO_SCHEMA_REGISTERED` |
| omitted | 1 | inferred |
| omitted | 2+ | `422 AMBIGUOUS_SCHEMA`, naming them |

### The smaller gaps

| Gap | Resolution |
|---|---|
| `aggregation` appears both as schema field metadata and in a view config, with no stated precedence | View wins, schema default is the fallback, neither is an error rather than an implicit `sum` |
| Batch semantics on ingest are undefined — what happens when some rows are valid | All-or-nothing; the batch is rejected and every failing row is reported |
| Re-registering an existing schema name is undefined | `409`. Not an overwrite, which orphans ingested rows; not versioning, which is unrequested |
| The type system is unspecified beyond four names in an example | A strict registry: `string`, `number`, `integer`, `boolean`, no coercion, `bool` excluded from both numeric types |
| `required` has no stated default | `false` when omitted, matching the brief's own example where one field omits it |
| Configs are "stored in memory" — no mention of validating them | Full referential integrity at registration time |
| Aggregating an *optional* field is undefined | Aggregations read non-null values, so `count` is `COUNT(column)`; `rowCount` carries the other number |
| No read endpoints at all | `GET /schema`, `GET /schema/{name}`, `GET /dashboard`, `GET /health` added — a configuration-driven platform that cannot report its own configuration is hard to defend |

---

## Extension points

Each of these is a single edit in a single file.

| To add | Change | Cost |
|---|---|---|
| A field type (`date`, `decimal`) | One `@register` in `core/types.py` | One registration. Set `numeric=True` and every arithmetic aggregation accepts it, `/docs` lists it, and no other module changes |
| An aggregation (`median`, `stddev`) | One `@register` in `core/aggregations.py` | Declare its legal types and its empty-dataset result |
| A view type (`chart`, `distinct`) | One handler in `core/views.py` | Two functions and a registration, under 20 lines |
| Database persistence | One new implementation of `store/base.py` | The interface is the only thing `core/` knows about storage; `api/dependencies.py` chooses which one to wire |

Each of the first three is proven by a test that registers a new one at runtime and asserts it
works end to end with no edit to any existing module.

Deliberately **not** built, with where each would attach:

| Feature | Where it would go |
|---|---|
| Filtering | A view-config key, validated by the handler's `validate` and applied in its `resolve` |
| Sorting | The same — a per-view concern, not a platform one |
| Grouping | A new view type; `summary` and `table` stay untouched |
| Pagination | `Repository.get_rows` gains offset/limit, and the response carries a page marker |
| Schema versioning | The store's key becomes `(name, version)`; `FR-1.8`'s `409` becomes a new version |
| Concurrency control | The repository interface is the seam; the in-memory implementation would need locking |

---

## What was deliberately left out

The brief names these as not expected, and implementing them is a scope error rather than credit:
authentication, authorization, databases, production deployment, LLM integrations, advanced
dashboard visualisations.

Also excluded by choice: filtering, sorting, grouping, pagination, schema versioning, concurrency
control, caching, logging middleware, Docker.

None of them are present. No Dockerfile, no CI config, no ORM, no charting library, no auth
middleware. The dependency list is the shortest version of the same claim: a web framework, a
server, a validator, and the test tooling.

The UI is one page over the same four endpoints, not a product. It renders summary views as a
determinations table and table views as results tables, and puts every failure in front of the
user in prose, with the verbatim response body — envelope code, message, and every entry in
`details` — one disclosure away under **Technical details** (D-54). That is the whole of the bonus
requirement, and a charting library would have been a worse answer, not a better one.

---

## Known edges

The implementation was attacked after it was finished — inputs chosen to find places where two
individually-correct guarantees leave a gap between them. Five findings were fixed (D-34 to D-37,
and D-13 reversed). These are the ones left, recorded rather than quietly carried.

| Edge | Behaviour | Why it is left |
|---|---|---|
| `avg` over an integer larger than ~1e308 | `500 INTERNAL_ERROR`, inside the error contract | Python ints are unbounded; the float conversion is not. Special-casing `avg` would fix the one input already known about, not the class. The generic handler (D-36) is the fix, and the status is honest |
| `INVALID_AGGREGATION` does not name the aggregation | `{"field": "views[0].note", "code": "INVALID_AGGREGATION", "actual": "string"}` | The reader has it in the payload they just sent. It can only come from an explicit view value — FR-1.7 rejects an illegal schema default at schema-registration time, so an inherited one is unreachable |
| A non-string `columns` entry echoes as a name | `columns: [123]` reports `views[0].123` | Reads as a column *named* `"123"`. The remedy is identical either way: that column does not exist |
| Off-vocabulary values report no `actual` | `{"amount": {"nested": 1}}` gives `expected: "number"` and no `actual` | Deliberate (D-18). Inventing JSON type names would make error bodies speak a vocabulary no schema can use |
| A failed batch reports every issue | 2000 bad rows → 6000 details, ~360 KB | FR-2.9 requires every failing row and field. A cap would be a different requirement, not this one |
| `count` can be lower than `rowCount` | `count` is `COUNT(column)` (D-20) | Correct and deliberate, but the certificate shows `count` as a determination and `rowCount` as *specimens on file*, and the divergence reads as a bug until you know the rule. On a required field they are identical, which is what makes it easy to miss |

## Testing

```bash
pytest -q                              # 529 tests
pytest tests/test_genericity.py -q     # the acceptance test that matters
```

| File | What it proves |
|---|---|
| `test_genericity.py` | **The pass condition.** Two unrelated use cases end to end, concurrently, in one app instance, with zero lines of `backend/` changed. Plus the RULE-0 guard, the layering check and the type-hint check |
| `test_brief_examples.py` | The brief's own payloads, replayed verbatim, asserting the documented responses — including the documented error bodies |
| `test_coverage.py` | Every requirement ID in `REQUIREMENTS.md` is referenced by at least one test, and no test cites an ID that does not exist |
| `test_store.py` | The repository contract, and that a caller cannot mutate stored data through a returned value |
| `test_types.py` / `test_aggregations.py` | Every accept and reject in the spec's tables, the `bool` trap, the empty-dataset result for all five aggregations, and extensibility proven by registering a new one inside a test |
| `test_schema.py` / `test_validation.py` | Every registration and row-validation branch: missing required, type mismatch per type, unknown field, null in required vs optional, multi-error batches |
| `test_views.py` / `test_dashboard_config.py` / `test_dashboard_generation.py` | The aggregation precedence chain in all three outcomes, registration-time rejection, and that generation never mutates what it reads |
| `test_api.py` | Every status code, and that a malformed envelope answers in the same error contract as everything else |

Three of these are worth singling out.

**`test_genericity.py` is the one that decides the assignment.** Not because `customer` works — a
hard-coded single-use-case implementation would pass every other file in the suite — but because
`trade` and `customer` are correct *at the same time*, and because registering the second is
proven not to disturb the first's output byte for byte. It also invents a third use case inside
the test, with field names the codebase has never seen, in case the two fixtures were somehow
special.

**The RULE-0 guard is the answer to "how do you know it is generic".** It walks every module
under `backend/` and fails on any appearance of the use-case vocabulary, naming the file and
line. `status` is handled separately, as a whole word with two named exemptions, because it is a
field name in the brief's example *and* ordinary HTTP vocabulary — the exemptions are the
`{"status": "ok"}` body the spec mandates and the English phrase "status code" in docstrings. A
domain use would still fail, and there is a test asserting the matcher itself works.

**Tests were written from the requirements, not from the implementation.** The pass condition was
defined in `REQUIREMENTS.md` section 6 before any code existed, each task's tests were written
alongside its code rather than after, and every assertion carries the `# FR-x.y` comment that
`test_coverage.py` checks. That guard passed on its first run — and was verified to be capable of
failing by deleting a requirement's only reference and watching it break.
