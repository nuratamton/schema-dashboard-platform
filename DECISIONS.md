# Decision log

Append as you build. `AI_REPORT.md` and the README's design-decisions section are both written
from this file.

Two reasons this matters. `AI_REPORT.md` asks for **one AI suggestion you accepted and one you
rejected** — real entries logged in the moment read very differently from a plausible-sounding
rejection reconstructed at the end. And the panel discussion is 60–90 minutes on your reasoning,
so a written trail of what you considered and discarded is the difference between recalling and
reconstructing.

Keep entries short. One or two lines each.

**Format:**

```
### D-n — <decision>
- Context:
- Options considered:
- Chose: … because …
- Rejected: … because …
```

---

## Pre-build decisions

Settled before implementation started, during the requirements decomposition.

### D-1 — Ingestion is all-or-nothing
- Context: FR-2.8. A batch where some rows validate and some do not.
- Options: (a) reject the whole batch, (b) accept valid rows and report the rest.
- Chose: **(a)**, because a partially-applied ingest leaves the caller unable to say what state
  the dataset is in without re-reading it, and because financial data ingestion is conventionally
  atomic.
- Rejected: (b). It is friendlier for bulk imports and would be the right default if the platform
  had a retry/dead-letter path. It does not, so partial success would be a silent data-integrity
  hazard.
- **Flip this if** you would rather argue partial-accept to the panel — it is a defensible answer
  and the change is contained to `api/ingest.py` plus its tests.

### D-2 — Schema re-registration returns 409
- Context: FR-1.8. `POST /schema` with an existing name, possibly after data is ingested.
- Options: (a) `409`, (b) overwrite, (c) version the schema.
- Chose: **(a)**, because overwriting silently orphans or invalidates already-ingested rows, and
  versioning is a substantial feature the brief neither asks for nor excludes.
- Rejected: (c) versioning — the right production answer, and noted as an extension point in the
  README rather than built.

### D-3 — Dashboard configs carry an explicit `schema` key
- Context: FR-3.2. The brief's example config binds to no schema at all.
- Options: (a) require an explicit `schema` key, (b) infer the schema from the field names used.
- Chose: **(a)**. With `trade` and `customer` both registered, `field: amount` is ambiguous, and
  supporting concurrent use cases is the entire premise of the platform. Inference would be
  guesswork that breaks the moment two schemas share a field name.
- Note: this is a deliberate extension to the brief's example. Call it out in the README — the
  gap is a more interesting observation than the fix.
- **Superseded by D-22.**

### D-4 — Aggregation precedence: view → schema default → error
- Context: FR-3.7. `aggregation` can appear both as schema field metadata and in the view config.
- Chose: view config wins; schema metadata is the fallback default; neither present is an error
  rather than an implicit `sum`.
- Rejected: defaulting to `sum` when unspecified — convenient, but it makes a silently wrong
  dashboard easier to produce than a loud failure.

### D-5 — Configs are validated at registration time, not render time
- Context: FR-3.5. The brief only says configs are "stored in memory".
- Chose: full referential integrity check against the bound schema on `POST /dashboard`.
- Reasoning: a config referencing a field that does not exist is broken the moment it is written.
  Discovering that at `GET` time pushes the failure to whoever is looking at the dashboard rather
  than whoever misconfigured it.

### D-6 — Strict type checking, no coercion
- Context: FR-1.10, FR-2.4.
- Chose: `"1000"` does not satisfy `number`; `True` does not satisfy `number` despite
  `isinstance(True, int)` being `True` in Python.
- Rejected: Pydantic-modelled rows. Pydantic would coerce `"1000"` to `1000` and defeat FR-2.4
  silently. Pydantic validates the envelope only; the row engine is ours.

---

## Build decisions

Append below as you go.

### D-7 — The store has no error vocabulary (T1)
- Context: NFR-4. `get_schema` on a missing name, `save_schema` on an existing one.
- Options: (a) return `None` / overwrite and let the caller decide, (b) raise `NotFound` /
  `Duplicate` from the store.
- Chose: **(a)**. The same absent key is a `404` on ingest (FR-2.1) and a `409` on registration
  (FR-1.8) — only the caller knows which. Raising would also mean `store` importing `core.errors`,
  which NFR-7 forbids outright.
- Rejected: (b). It catches a caller that forgets to check `has_schema` first, but buys that with
  an upward dependency. The guard belongs where the status code is decided.

### D-8 — Rows are copied in and out of the store; schemas and configs are not (T1)
- Context: FR-4.9 — generation must never mutate stored data.
- Chose: `append_rows` and `get_rows` each shallow-copy every row, making FR-4.9 a property of the
  store rather than a rule every future caller has to remember. A shallow `dict()` copy is
  provably enough: validated values are scalars of the registered types, so there is no nested
  structure to share (FR-2.4 rejects a dict-valued field).
- Rejected: `deepcopy` — pays for a generality the type registry has already excluded. Also
  rejected: copying schemas and configs, which would require knowing their shape — exactly what
  this layer is forbidden to know. They are stored by reference and treated as immutable by `core`.

### D-9 — `count_rows` belongs on the repository interface (T1)
- Context: FR-4's response carries `rowCount`.
- Chose: an explicit `count_rows` on the port. Given D-8, `len(get_rows(name))` would deep-copy an
  entire dataset to produce an integer, and for a future database implementation it is the
  difference between `SELECT COUNT(*)` and loading the table.
- Rejected: leaving callers to take `len()`. Cheaper interface, worse implementation.

### D-10 — `VALIDATION_FAILED` is the envelope code; specific codes live in `details[]` (T2)
- Context: NFR-5 mandates one error shape. FR-3.6–3.8 read as though `UNKNOWN_FIELD` and
  `INVALID_AGGREGATION` are top-level codes, while the FR-2 example puts `VALIDATION_FAILED` at
  the top and the specific codes underneath.
- Chose: follow the FR-2 example everywhere. The envelope `error` says what kind of failure it is;
  `details[].code` says which things failed. A client can switch on four envelope codes, and a
  config with two bad columns reports both instead of only the first.
- Rejected: hoisting the first issue's code into the envelope. It reads closer to FR-3.6 literally,
  but makes the top-level code depend on how many things went wrong, which is not a contract.
- Note: `ValidationIssue.row` is optional for the same reason — one structure serves both
  registration-time (no row) and ingest-time (row index) failures, and the key is omitted rather
  than sent as `null`.

### D-11 — The type registry holds scalars only, and that is a cross-module invariant (T3)
- Context: NFR-3 says a new type is a one-line registration. D-8 says the store copies rows
  shallowly. Those two statements are only compatible while every registered type is scalar.
- Chose: state the invariant in `core/types.py` rather than leave it implicit. A scalar type
  (`date`, `decimal`) really is a free addition; a container type (`array`, `object`) would give a
  field value nested structure, at which point the store's `dict(row)` copy stops guaranteeing
  FR-4.9 and starts handing out shared references.
- Rejected: deep-copying in the store so any future type is safe — pays a per-row cost forever to
  buy generality for a type that does not exist, and hides the coupling instead of naming it.
- Note: this is the kind of invariant that is obvious while writing it and invisible six months
  later. The docstring names the file that has to change.

### D-12 — Checking against an unregistered type raises instead of returning False (T3)
- Context: `matches("date", value)` where `date` was never registered.
- Options: (a) raise `KeyError`, (b) return `False`.
- Chose: **(a)**. FR-1.4 rejects unknown types when the schema is registered, so a row can only
  ever be checked against a type that exists. Reaching this branch means our code is wrong.
- Rejected: (b). It never crashes, which is exactly the problem — a typo in a type name would
  surface as every row failing validation with `TYPE_MISMATCH`, sending whoever is debugging it
  to look at the data instead of at the schema.

### D-13 — `NaN` and `Infinity` are rejected by `number` — **reversed; original premise falsified**
- Context: Python's `json` parser accepts the literals `NaN`, `Infinity` and `-Infinity` by
  default. Both are `float`, so both passed the `number` checker.
- **Originally chose: accept them.** Nothing in the brief mentions non-finite numbers, and
  rejecting them looked like behaviour no requirement asks for. The stated reason for accepting was
  that the consequence would be *visible*: "a single `NaN` in a dataset makes `sum`, `avg`, `min`
  and `max` all return `NaN`, and a dashboard showing `NaN` is worse than one refusing the row."
  Ugly, but loud — and therefore tolerable.
- **The premise was wrong.** The adversarial pass ingested one `NaN` row and read the dashboard.
  FastAPI's encoder converts `NaN` to `null`, so the response was `{"rowCount": 1, …, "value":
  null}` — and `null` is precisely the value FR-4.8 reserves for *"there is no data"*. For `sum`,
  whose empty-dataset answer is `0`, `null` is a value the contract never defines at all. The
  outcome is not visible and ugly; it is invisible and misrepresenting. A client reading `value`
  concludes the dataset is empty while `rowCount` says it is not.
- **Now chose: reject** non-finite floats in `_is_number`, the one-line change the original entry
  said was available. `math.isfinite` is applied to floats only — it raises `OverflowError` on an
  int too large to convert to a float, and an int is never non-finite.
- Reversed because its premise was falsified, not because the reasoning was sloppy. The decision
  was sound given a belief about behaviour that turned out to be untrue; the way that surfaced was
  attacking the finished system rather than re-reading the argument.
- Still out of scope, deliberately: very large integers. `10**400` satisfies `number`, and `avg`
  over it raises `OverflowError` — now caught by D-36 rather than special-cased here.

### D-14 — Aggregation legality is a trait on the type, not a list of type names (T4)
- Context: FR-1.7 states legality as "sum, avg, min, max → number, integer". The literal reading is
  a set of type names held in `core/aggregations.py`.
- Options: (a) a `numeric: bool` trait on `FieldType` that arithmetic aggregations require,
  (b) `legal_types = {"number", "integer"}` on each aggregation.
- Chose: **(a)**. Under (b), registering a `decimal` type would require editing
  `aggregations.py` to add it to four separate sets — which directly contradicts NFR-3's "adding a
  type requires zero edits to existing modules". The trait moves the knowledge to the type that
  owns it, and `aggregations.py` ends up naming no type at all.
- Rejected: (b), and also rejected going further — a general trait or capability system with
  multiple named capabilities. One boolean covers the entire FR-1.7 matrix for four types. A
  capability framework here would be infrastructure for a requirement that does not exist.
- Evidence: `test_a_new_type_is_legal_for_arithmetic_without_editing_this_module` registers a
  `decimal` type inside the test and asserts all four arithmetic aggregations become legal for it
  with no edit to `aggregations.py`.

### D-15 — `type` and `aggregation` are plain `str` on the Pydantic model (T5)
- Context: FR-1.4 and FR-1.7 constrain both to a known set. Pydantic's idiomatic answer is
  `Literal["string", "number", "integer", "boolean"]` or a Python `Enum`.
- Options: (a) plain `str`, checked against the registries afterwards, (b) `Literal`/`Enum`.
- Chose: **(a)**. (b) looks like stronger typing and is in fact the same hard-coding NFR-3 exists
  to forbid, just relocated: the registered names would live in `models.py` as well as the
  registries, and adding a `date` type would mean editing a file that has nothing to do with types.
- Rejected: (b). It would also have produced a *better* auto-generated OpenAPI schema at `/docs`,
  which is the genuine cost of this choice and worth saying out loud.
- Evidence: a smoke run registers `date` at runtime and a schema using it is accepted with no edit
  to `models.py`; the string `"date"` never appears there.

### D-16 — A duplicate schema name is refused before the body is validated (T5)
- Context: `POST /schema` with a name already taken *and* a malformed body. 409 or 422?
- Chose: **409**. Re-registration is refused whatever the body says, so reporting problems in a
  schema that cannot be created either way is noise the caller cannot act on.
- Rejected: validating content first so the caller sees every problem at once. Defensible, and the
  argument for it is that content validation is stateless while the duplicate check is not — but
  it means answering "your aggregation is illegal" to a request whose real answer is "that name is
  taken".

### D-17 — `UNKNOWN_TYPE` and `UNKNOWN_AGGREGATION` added to the error vocabulary (T5)
- Context: T2 defined the codes from the FR-2 example, which is about row contents. FR-1.4 and
  FR-1.7 turn out to need two codes that list did not contain.
- Chose: add both. `TYPE_MISMATCH` means a *value* failed a type that exists — reusing it for
  "that type does not exist" would be actively misleading in an error body. Likewise
  `UNKNOWN_AGGREGATION` ("no such aggregation") and `INVALID_AGGREGATION` ("exists, but not on a
  `string` field") send whoever wrote the schema to two different places.
- Rejected: collapsing each pair into one code. Fewer codes, but the two failures have different
  fixes and the detail entry is the only place that distinction can live.
- Note: this is T2's vocabulary being corrected by its first real consumer, which is the argument
  for having built the registries before the endpoints rather than after.

### D-18 — `type_name_of` breaks ties by declaration order and returns `None` off-vocabulary (T6)
- Context: `TYPE_MISMATCH` reports `actual` as a type name (FR-2.4). `5` satisfies both `number`
  and `integer`, and a nested array satisfies nothing.
- Chose: first match in declaration order, so `5` reports as `number`; `None` when no registered
  type accepts the value, in which case the `actual` key is omitted from the detail.
- Reasoning: the ambiguity is unobservable where it would matter. A value satisfying the expected
  type never produces a mismatch, so the tie-break only surfaces against some *other* expected
  type — `{"tradeId": 5}` against a `string` field, reported as `number` — where either name is
  equally true.
- Rejected: inventing JSON-ish names (`array`, `object`, `null`) for values outside the registry.
  Error bodies would then speak two vocabularies, one of which corresponds to nothing a caller can
  write in a schema.

### D-19 — The ingest failure message counts failing rows, not issues (T6)
- Context: the FR-2 example message reads "3 of 5 rows failed validation".
- Chose: count distinct row indexes. A row with three bad fields is one failed row, reported with
  three entries in `details`.
- Rejected: counting issues, which would say "5 of 5 rows failed" for a two-row batch and make the
  message contradict the array beneath it.

### D-20 — `count` means `COUNT(column)`, not `COUNT(*)` (T7)
- Context: FR-4.5 aggregates "the field" across all rows. A `summary` view naming an *optional*
  field meets rows that simply do not carry it — T6 stores null optionals as absent.
- Options: (a) aggregate the field's non-null values, so `count` reports rows that have a value,
  (b) make `count` a special case that counts rows regardless of the field.
- Chose: **(a)**. Every aggregation then reads the same input: `sum` and `avg` cannot include a
  value that is not there, and (b) would make `count` the only aggregation whose answer ignores
  the field it names. Nothing is lost either — FR-4's response carries `rowCount` separately, so
  both numbers are available to a client.
- Rejected: (b). It matches the SQL reflex `COUNT(*)`, and on a required field the two are
  identical, which is exactly what makes the divergence easy to miss in review.
- Consequence worth stating: a `count` over an optional field can be lower than `rowCount`. That
  is the honest answer to "how many rows have a status", and the pair of numbers says so.

### D-21 — View configs are raw dicts, validated by their handler (T7)
- Context: `summary` carries `field`, `table` carries `columns`. There is no shape common to both.
- Options: (a) `dict[str, Any]`, with each handler owning its own config's shape, (b) a Pydantic
  discriminated union over the registered view types.
- Chose: **(a)**. (b) would put the view-type names in `models.py`, so adding a third view type
  would mean editing a file unrelated to views — the same trap as `Literal` for field types
  (D-15), and it would break the NFR-1 property outright.
- Rejected: (b), at a real cost: handlers hand-check presence and shape where Pydantic would have
  done it, and `/docs` cannot describe a view config.
- Consequence: two issue codes carry the shape checks. `MISSING_REQUIRED_FIELD` means the config
  supplied no usable value for a key the view needs — absent, wrong shape and empty are one event
  (FR-3.10) — and `UNKNOWN_FIELD` means a name was given that the schema does not declare
  (FR-3.6, FR-3.9).

### D-22 — **Amends D-3.** The `schema` key is optional, and inferred only when unambiguous (T8)
- Context: D-3 made `schema` a required key, which meant the brief's own example config — which
  carries no binding — could not be submitted as written. That is a poor answer to a gap we
  ourselves identified in the brief.
- Chose: explicit `schema` wins; omitted, infer it when exactly one schema is registered; omitted
  with more than one candidate, refuse with `AMBIGUOUS_SCHEMA` (422) naming them.
- Reasoning: this keeps everything D-3 was protecting — nothing is ever guessed when more than one
  answer is possible — while letting the brief's example work verbatim. The original objection was
  to inferring a binding from *field names*, which is still rejected: with two schemas registered
  the request is refused, not resolved by inspecting which fields it mentions.
- Consequence: `AMBIGUOUS_SCHEMA`, reserved with no producer at T2 and flagged then as a candidate
  for deletion, is now reachable and tested.
- Note: zero schemas registered also raises `AmbiguousSchema`, where the word is a stretch —
  there is nothing to be ambiguous between. The failure is the same one (no binding) and the
  message says which case it is. A distinct code is a one-line change if the distinction is
  wanted. — **Resolved in D-33; the distinction was wanted.**

### D-23 — An inferred binding is resolved once and frozen at registration (T8)
- Context: a config registered with no `schema` key, while exactly one schema exists. A second
  schema is registered later.
- Chose: `register_dashboard` stores the *resolved* config, so `schema_name` is always set in the
  store even when the request omitted it. Generation reads it and never re-infers.
- Rejected: storing the request as submitted and inferring again at `GET`. The dashboard would
  then start returning `AMBIGUOUS_SCHEMA` the moment an unrelated second schema was registered —
  a working dashboard broken by a change that has nothing to do with it, and exactly the kind of
  render-time failure FR-3.5 exists to prevent.

### D-24 — A repeated `table` column is refused at registration (T8)
- Context: `{"columns": ["a", "b", "a"]}`. Nothing in FR-3.9 or FR-3.10 mentions uniqueness.
- Chose: reject it with `DUPLICATE_NAME`, mirroring FR-1.3's field-uniqueness rule.
- Reasoning: this enforces FR-4.6 rather than adding a rule. "Rows projected to exactly the
  configured columns" is unsatisfiable when a column repeats — a JSON object cannot carry the same
  key twice, so the view would report three columns above rows containing two. FR-3.5 says a
  config that cannot produce valid output is refused when it is written.
- Rejected: leaving it, on the grounds that no requirement names it. That reading treats the spec
  as a checklist; the output would contradict its own column list, which is a correctness hole
  rather than a missing feature.

### D-25 — The dashboard response is a plain dict, not a Pydantic model (T9)
- Context: every request is modelled; the symmetric move is a `DashboardResponse` model.
- Chose: a plain `dict[str, Any]`. There is nothing to validate on the way out — the values come
  from our own handlers, not from a caller — and a response model would have to carry the same
  `schema`/`BaseModel` shadowing workaround as `IngestRequest` for a key that is purely output.
- Rejected: a response model, which would have improved the `/docs` schema. That is the second
  time typing the boundary loosely has cost documentation quality (D-15 was the first); worth
  naming as a pattern rather than pretending each was free.
- Note: the `views` array is heterogeneous by design — each handler decides its own payload shape
  — so a single response model could only have typed it as `list[dict[str, Any]]` regardless.

### D-26 — Generation has exactly one error path, and that is the point (T9)
- Context: `generate_dashboard` could re-check that fields exist, that aggregations are legal, that
  the bound schema is present.
- Chose: none of it. The only error is `UnknownDashboard` (FR-4.1). Every stored config was
  validated against its schema when it was written (FR-3.5) and its binding frozen (D-23), so
  there is nothing left that can fail.
- Reasoning: this is the dividend FR-3.5 pays, and the clearest way to show the two requirements
  are one design rather than two features. Re-validating at render time would also be the wrong
  place to discover a problem — see D-5.
- Assumption made explicit: `repository.get_schema(config.schema_name)` can never return `None`,
  because schemas cannot be re-registered (D-2) and the repository has no delete. **Adding a
  delete endpoint breaks this**, and the fix is a decision about semantics — cascade, refuse while
  dashboards reference it, or let generation 404 — not a null check.

### D-27 — **Recovers most of D-15's cost.** `/docs` documents the registries without naming them (T10)
- Context: D-15 and D-25 both gave up OpenAPI quality to keep registry names out of `models.py`.
  Twice paying the same price is worth a second look.
- Chose: a `json_schema_extra` callable on `type` and `aggregation` that injects
  `types.supported_types()` and `aggregations.supported_aggregations()` as an `enum`. It runs at
  schema-generation time, when the registries are populated, so `/docs` shows the supported names
  while no name is written down in `models.py` — registering a `date` type still requires no edit
  there, and `/docs` picks it up.
- Rejected: `Literal`, again, for D-15's original reason. The point is that the *documentation*
  argument for `Literal` was the real one, and it turns out not to require `Literal`.
- Not attempted for view configs: `views` is heterogeneous by design (D-21), so there is no single
  shape to document. That one stays a genuine cost.
- Detail worth keeping: an optional field renders as `anyOf[string, null]`, and setting `enum` on
  the union would have forbidden `null`. The enum goes on the string branch.

### D-28 — Pydantic's envelope errors are translated into our vocabulary, not passed through (T10)
- Context: NFR-5 wants one error contract. FastAPI's `RequestValidationError` produces
  `{"detail": [...]}` with Pydantic's own error types.
- Chose: an override that maps each Pydantic error to a `ValidationIssue` — `missing` →
  `MISSING_REQUIRED_FIELD`, `extra_forbidden` → `UNKNOWN_FIELD`, everything else →
  `TYPE_MISMATCH` — and renders `loc` as the same path form dashboard config errors use
  (`fields[0].name`, matching `views[0].<field>`). Pydantic's own message goes in `expected`.
- Rejected: mapping every Pydantic error type exactly. The remainder (`string_type`, `too_short`,
  `list_type`) are all "this is not the shape the envelope requires", which is what
  `TYPE_MISMATCH` says; enumerating them would couple us to Pydantic's error taxonomy for no gain
  a caller can use.
- Why it matters: without the override, the one failure a caller is most likely to hit first —
  a typo in the request body — is the only one that answers in a different format.

### D-29 — `status` is guarded as a whole word with two named exemptions (T11)
- Context: the RULE-0 guard checks for use-case vocabulary in `backend/`. `status` is a field name
  in the brief's example schema *and* ordinary HTTP vocabulary — it appeared 14 times, every one
  of them about HTTP.
- Options: (a) drop `status` from the guard, (b) reword the codebase to avoid the word,
  (c) whole-word matching plus a short list of named exemptions.
- Chose: **(c)**, after first removing the avoidable collisions — `from fastapi import status` and
  `status.HTTP_201_CREATED` became `status_code=201`, which reads better anyway and is not what a
  word-boundary match sees. What remains is `{"status": "ok"}`, mandated verbatim by FR-5.4, and
  the English phrase "status code" in docstrings. Both are exempted by name, so a domain use —
  `config["status"]`, a branch on a schema's contents — still fails.
- Rejected: (a), which quietly narrows the claim the guard makes. Also rejected: (b), rewording
  precise technical prose to satisfy a grep, which degrades the documentation to flatter the tool.
- Note: `status_code` never matches `\bstatus\b` — `_` is a word character. That is luck, not
  design, and it is worth knowing rather than relying on silently.

### D-30 — The coverage guard may not vouch for itself (T11)
- Context: `test_coverage.py` asserts every requirement id in `REQUIREMENTS.md` is referenced by
  some test. The file necessarily contains requirement ids itself, in its own sanity checks.
- Chose: a second assertion that no requirement is referenced *only* by the guard, with one stated
  exception — NFR-8 asks for tests covering every branch, and this file is that test.
- Rejected: excluding the guard from the scan entirely, which would leave NFR-8 with no home and
  invite a fake reference somewhere else to satisfy the check.
- Also added the reverse direction: a mistyped id (`FR-2.11`) reads as coverage while pointing at
  nothing. It caught one on the first run — in this file's own docstring, which is exactly the
  kind of thing that would have sat there unnoticed.
- Note: the forward check passed on the first run, which was not expected. That is a consequence
  of writing the `# FR-x.y` comments alongside each test from T1 onward rather than retrofitting
  them; verified by deleting the sole reference to `FR-1.1` and watching the guard fail.

### D-31 — The UI is served by the app, which is why there is no CORS middleware (T12)
- Context: the UI needs to `fetch` the API. Opened off disk over `file://` its origin is `null`,
  so every request is cross-origin and every request fails.
- Options: (a) serve `frontend/index.html` from FastAPI at `/`, (b) add CORS middleware so the
  file works when double-clicked.
- Chose: **(a)**, four lines with `FileResponse`. Same-origin, so the problem does not arise.
- Rejected: (b). It is the reflex fix, it is unrequested, and it would mean shipping a permissive
  cross-origin policy to solve a problem created by how the file was opened. Removing the cause
  beats configuring around it.
- Note: REQUIREMENTS.md section 4 says the UI "opens by double-click **or** is served by FastAPI".
  Only the second works, and this is why. Worth saying in the README rather than leaving a grader
  to discover it.

### D-32 — One affordance beyond the four panels: a row that omits the optional field (T12)
- Context: BR-4 asks that absent optionals render as `null` (FR-4.7). The brief's ingest example
  is a single complete row, so a grader clicking straight down the page never sees that path.
- Chose: keep the prefill exactly as the brief writes it, and add one secondary button that
  appends a row omitting the optional field.
- Rejected: editing the prefilled payload to include a partial row. The instruction to prefill
  with the brief's own payloads is worth more than the demo — a grader comparing the page against
  the PDF should find them identical.
- Scope note: this is an addition to a bonus deliverable, and the only one. Everything else on the
  page maps to BR-1 to BR-5. It is a debugging surface, so a button that produces a debugging case
  earns its place; a chart library would not.

### D-33 — **Amends D-22's known imprecision.** `NO_SCHEMA_REGISTERED` splits off from `AMBIGUOUS_SCHEMA`
- Context: D-22 made the `schema` key optional and inferred the binding when exactly one schema is
  registered. Both ways inference could fail — none registered, several registered — returned
  `AMBIGUOUS_SCHEMA`. D-22 recorded that as a known imprecision with a one-line fix available.
- Chose: take the fix. Zero schemas now returns `422 NO_SCHEMA_REGISTERED`; more than one still
  returns `422 AMBIGUOUS_SCHEMA` naming the candidates. An explicitly named but unregistered
  schema is unchanged at `404 UNKNOWN_SCHEMA`.
- Reasoning, in two parts. **"No schemas are registered" is not ambiguity** — there is nothing to
  be ambiguous between, and a code whose name misdescribes the failure is worse than no code, in a
  contract whose whole selling point is that the code tells you what went wrong. And the path is
  **reachable in ordinary use**: it is what happens the first time anyone posts a dashboard before
  posting a schema, which the UI's four numbered panels make an easy thing to do out of order. It
  was not a theoretical edge case.
- Rejected: leaving it. The argument for leaving it was that the message already distinguished the
  two cases in prose — but a client switching on `error` could not, and prose is not the contract.
- Test for whether a new code is justified, worth keeping: **does it send the caller somewhere
  different?** Here, "register a schema" versus "choose one of these". Two remedies, two codes.
  Where two failures share a remedy, one code is enough — which is why the shape complaints in the
  envelope override all collapse to `TYPE_MISMATCH` (D-28).

### D-34 — Each view handler declares the config keys it understands (adversarial fix 1)
- Context: `{"type": "summary", "field": "amount", "aggregations": "count"}` — note the plural —
  registered with a `201` and produced a dashboard reporting `sum`. The unknown key was ignored and
  the precedence chain fell through to the schema's field default.
- The gap: D-15 put `extra="forbid"` on the envelope models precisely so a misspelled `"agg"` could
  not be silently dropped. D-21 made view configs raw dicts precisely so a new view type needs no
  edit to `models.py`. Both correct; nothing covered the space between them.
- Chose: `ViewHandler` carries a `config_keys` frozenset, checked centrally in
  `validate_dashboard_config` against `config_keys | {"type"}`. Unknown keys are `UNKNOWN_FIELD`
  located as `views[n].<key>`.
- Why on the handler rather than in the checker: a third view type brings its own key set, so NFR-1
  survives. Why checked centrally rather than by each handler: no handler can forget to.
- Rejected: a per-handler Pydantic model. It would work, and it reintroduces the translation layer
  between Pydantic errors and our own issues that D-28 already has to maintain in one place.
- Severity: this was the highest-ranked finding of the pass, because the UI invites editing that
  textarea and the brief's own schema puts `aggregation: sum` on `amount` — the shape where the
  fallback is silent rather than an `AGGREGATION_REQUIRED` error. It defeated D-4's whole intent
  that a silently wrong dashboard be harder to produce than a loud failure.

### D-35 — Names must round-trip through a URL path (adversarial fix 2)
- Context: `POST /dashboard` with `{"name": "a/b"}` returned `201`, listed in `GET /dashboard`, and
  `GET /dashboard/a/b` returned `404`. Percent-encoding does not help — the path is decoded before
  routing. The dashboard was registered, visible, permanently unfetchable, and its name permanently
  taken. Whitespace-only names were also accepted, because `min_length=1` counts spaces.
- Chose: reject `/` and whitespace-only names at registration, via a shared `validate_name` used by
  both schema and dashboard registration. New code `INVALID_NAME`.
- Deliberately minimal: **no character whitelist.** Spaces, dots, hyphens and unicode all encode
  and route correctly, and a rule that rejected a name a grader reasonably tried would be a worse
  bug than the one being fixed. Verified that `"trade dash"` still registers and fetches.
- Why a new code rather than `DUPLICATE_NAME`: both mean "choose a different name", but a client
  that retries a duplicate with a numeric suffix would loop forever on this one. Different remedy,
  different code — the test set out in REQUIREMENTS.md.

### D-36 — A last-resort exception handler, because NFR-5 was not actually true (adversarial fix 3)
- Context: `avg` over an integer too large to convert to a float raises `OverflowError`, and the
  response was Starlette's `text/plain` "Internal Server Error". NFR-5 claims one error contract
  across every endpoint; that made the claim false, and the UI could not even render it because
  `response.json()` throws on that body.
- Chose: `@app.exception_handler(Exception)` registered below the typed `PlatformError` handler,
  formatting anything unforeseen as `{error: INTERNAL_ERROR, message, details: []}` with a 500.
- **Deliberately not** special-casing `avg`. The overflow is the edge that exposed the gap, not the
  gap. The next unanticipated exception will be a different one, and a handler that catches only
  the failure already known about is not a contract.
- Message is generic on purpose: echoing exception text back leaks internals to a caller who can do
  nothing with them.
- The known edge is recorded rather than fixed: a >1e308 integer still fails `avg`. It now fails
  inside the contract, with a 500, which is the honest status for "this input is beyond us".

### D-37 — `expected` names a type, never prose (adversarial fix 4)
- Context: the envelope override put Pydantic's `msg` into `expected`, producing
  `{"code": "MISSING_REQUIRED_FIELD", "expected": "Field required"}` and
  `{"code": "TYPE_MISMATCH", "expected": "Input should be a valid boolean"}`.
- The gap: `errors.py` documents `expected`/`actual` as naming *types*, and every domain-path error
  honours it — `"number"`, `"string, number, integer, boolean"`. The envelope path did not, so one
  field meant two different things depending on which producer filled it.
- Chose: omit the key. The code already carries the meaning — `MISSING_REQUIRED_FIELD` plus
  `expected: "Field required"` says the same thing twice, in two vocabularies.
- Rejected: translating Pydantic's messages into type names. That is a mapping table against
  Pydantic's error taxonomy, which D-28 already declined to maintain for exactly this reason.

---

## Frontend redesign decisions

Made before the redesign of `frontend/`, after re-reading `round_1_assignment.pdf` against
`REQUIREMENTS.md`.

### D-38 — The PDF outranks `REQUIREMENTS.md` where the two disagree on the UI
- Context: `REQUIREMENTS.md` §4 constrains the bonus UI to a single static file, no build step, no
  dependencies, no framework, JSON textareas, and "a debugging surface, not a product". The
  assignment PDF's entire Bonus section is four bullets: register schemas, submit data, register
  dashboard configurations, view generated dashboard data. None of those constraints appear in it.
- The gap: §4 was written as a decomposition of the brief and quietly became stricter than it. That
  is fine for the backend, where the extra rigour is the submission's argument. On the UI it was
  ruling out the very thing the bonus asks for — something a user can actually use.
- Chose: treat the PDF as the brief and §4 as the author's elaboration. A §4 constraint the PDF does
  not state is not binding on design.
- Held anyway, because the PDF does state them: FastAPI + in-memory, no auth/authz/database/
  deployment/LLM, no advanced dashboard visualizations, 2–3 hours of total effort, and the UI being
  optional and absent from the five evaluation criteria.
- Consequence: `REQUIREMENTS.md` §4 and the README's UI section now describe something that is not
  being built and must be rewritten to match. No test breaks — `tests/test_coverage.py` already
  excludes `BR-*` from its assertion, deliberately.

### D-39 — `frontend/` splits into real files rather than staying one blob
- Context: `index.html` was 405 lines of markup, CSS and JS in one file, per the §4 rule D-38 lifts.
- Chose: `index.html` + a stylesheet + a script, still vanilla, still served by FastAPI, still no
  build step and no npm install. A reviewer runs `uvicorn` and the app is there.
- Rejected: a framework with a build step. It would eat a large share of a 2–3 hour budget and put
  `npm install` in a reviewer's path, to improve a surface the PDF does not grade.
- Rejected: keeping one file. Portability was the only argument for it, and serving from FastAPI
  already provides that; three files cost the reviewer nothing and the CSS stops being unreadable.

### D-40 — Guided forms become the primary input, with JSON kept as an escape hatch
- Context: all three write panels were raw JSON textareas prefilled with the brief's payloads. That
  demonstrates the API honestly and asks the user to hand-write JSON, which is the opposite of the
  stated goal of a UI that is easy to use.
- Chose: build a schema by adding field rows with name / type / required / aggregation controls;
  build a dashboard config by choosing views and picking fields from the registered schema. The
  controls can only offer what the registry actually supports, so a whole class of `UNKNOWN_TYPE`
  and `INVALID_AGGREGATION` errors becomes unreachable from the UI.
- Rejected: forms only. The API shape is what is being evaluated, and hiding it behind a form would
  cost more than the tidiness gains. Raw JSON stays one toggle away on every panel.
- Unchanged: errors still render verbatim — code, message, and every `details[]` entry. Forms make
  fewer errors reachable; they do not make the error contract less worth seeing.

### D-41 — No charts, reading the PDF's exclusion literally
- Context: the PDF lists "advanced dashboard visualizations" among the things candidates are not
  expected to implement. A bar per numeric summary would arguably not be "advanced".
- Chose: no charts at all. Summary views stay value cards, table views stay tables.
- Why: the argument for one restrained chart is an argument about where a line sits in someone
  else's sentence, and the reward for winning it is a feature nobody asked for. Typography,
  hierarchy and data legibility are where the same effort actually shows.

### D-42 — The UI's world: a certificate of analysis
- Context: the redesign needed a visual system, and the category default for "dashboard platform"
  is the admin shell — sidebar, white cards on grey, stat tiles, a zebra table. Its predictable
  opposite, the black-and-mono terminal, is the same reflex wearing different clothes.
- Chose: the laboratory certificate of analysis. A schema *is* an acceptance specification; a row
  is a specimen tested against it; `{row, field, code, expected, actual}` *is* an
  out-of-specification log; `sum`/`avg`/`min`/`max`/`count` over a batch *are* lot statistics.
  The mapping is exact, so the metaphor does no work the product does not already do.
- Considered and declined: an architectural drawing set (schema as schedule legend — very close,
  and the line-weight discipline was borrowed rather than the look), an interactive type specimen
  (right interaction model, wrong audience), a design-annual plate section (handsome, but its
  registration marks are decoration where drafting line weights are semantic).
- Consequence: hierarchy is carried by rule weight, band fills and spaced caps. There are no cards
  and no shadows anywhere in `styles.css`, which is a constraint the world imposed, not a style.

### D-43 — Light only, and the dark-mode block was dropped
- Context: the previous `index.html` carried a `prefers-color-scheme: dark` palette.
- Chose: commit to one light palette on a pale form stock. The world is a printed document read at
  a daytime desk; a dark variant of a printed form is a costume, and a half-committed world reads
  worse than a committed one.
- Cost, stated plainly: a reviewer with dark mode on gets a bright page. That is how documents
  behave, and it is the honest trade for a coherent material.

### D-44 — `backend/` changed by exactly one line's worth of wiring
- Context: splitting the UI into `index.html` + `styles.css` + `app.js` + fonts means the app has
  to serve more than one file, and `main.py` served a single `FileResponse`.
- Chose: `app.mount("/static", StaticFiles(directory=_UI_DIR))`. Adding a UI asset now needs no
  further edit.
- Deliberately **not** mounted at `/`: that hands unknown paths to Starlette's HTML 404 page and
  would make NFR-5's "one error contract across every endpoint" false.
- RULE-0 is untouched: `grep -ri "trade\|customer\|tradeId\|amount" backend/` still returns zero.

### D-45 — "Errors verbatim" is a contract about values, not only about visibility
- Context: the finding log rendered `details[].row + 1`, because a 1-based specimen number reads
  more naturally in a table. The design review caught it: a `422` carrying `"row": 1` was being
  displayed as specimen 2.
- The gap: "surface errors verbatim" had been read as "show every field", when it also means
  "show every field *unaltered*". A reviewer comparing the UI against the raw response would have
  found them disagreeing, and the UI would have been the one that was wrong.
- Chose: print `row` exactly as the API sends it, and make the intake grid's own index column
  zero-based to match, so the grid and the log now agree with the response rather than with each
  other. A legend states that `row` is a zero-based index into the `rows` array.
- Also chose: head each finding column with the contract's own key name (`row`, `field`, `code`,
  `expected`, `actual`) and carry the world's noun underneath, plus a raw-response disclosure on
  every error. The world can own the vocabulary as long as it never *replaces* the contract.
- Rejected: keeping the 1-based number and footnoting it. A footnote does not help the one reader
  who matters here, who is diffing the page against `curl` output.

### D-46 — Two latent CSS bugs found while making the grids work on a phone
- `* { box-sizing: border-box }` does not match pseudo-elements. The stacked-grid label band was
  declared `width: 118px` with `padding: 0 10px` and therefore rendered 138px wide, covering the
  first character or two of every value. The reset is now `*, *::before, *::after`.
- The base column widths (`.grid .c-type { width: 132px }`, specificity 0-2-1) out-specified the
  narrow-viewport `td` rule that tried to unset them (0-1-2), so the stacked cells stayed narrow.
  The override now names the class and the element together.
- Worth recording because both were invisible in a full-page screenshot at phone width and only
  showed up on a 1:1 crop. Judging a mobile layout from a downscaled thumbnail hides exactly the
  class of defect the thumbnail is being used to look for.

### D-47 — An empty value is not a type error
- Context: submitting the form blank returned `{"field": "name", "code": "TYPE_MISMATCH"}`. The type
  was correct — `""` is a string. What was wrong was that there was no usable value.
- The gap: `_ENVELOPE_CODES` mapped Pydantic's `missing` and `extra_forbidden` and swept everything
  else into `TYPE_MISMATCH`, with a comment explicitly lumping `too_short` in. But `errors.py`
  already defines `MISSING_REQUIRED_FIELD` as covering "no usable value supplied" for a config key
  (FR-3.3, FR-3.10), which is exactly what a blank name and an empty array are.
- Chose: two more entries in the existing map — `string_too_short` and `too_short` →
  `MISSING_REQUIRED_FIELD`. No new mapping layer; the map already existed for this purpose.
- Not a reversal of D-28: that declined to translate Pydantic's English *messages* into type names.
  This maps Pydantic's stable machine error type, which is what the map was already doing.
- Sent the caller somewhere different, which is the test REQUIREMENTS.md sets for a code being
  worth distinguishing: `TYPE_MISMATCH` sends you hunting for a type error that does not exist.

### D-48 — A form that is not filled in yet should not have to ask the server
- Context: clicking Register on a blank form produced a full-bleed red findings table with three
  of five columns full of em-dashes, for what was really "you have not typed anything yet".
- Chose: a pre-send check per section. Blank names, duplicate parameter names, empty views and
  tables with no columns are caught in the page, the offending control is marked, and nothing is
  sent. It renders as a dashed-topped block, reusing the world's existing rule that dashed means
  *not issued* — so the vocabulary already carried the meaning.
- Deliberately skipped in JSON mode. The escape hatch exists so a deliberately invalid payload can
  reach the server; a client-side guard there would defeat the one affordance that proves the
  error contract. "Load a nonconforming batch" still round-trips exactly as before.
- Not a softening of the "errors verbatim" pin: this prevents a request, it never reinterprets a
  response. Every response that does come back is still rendered whole.

### D-49 — The finding log shows the columns the response actually has
- Context: the log always drew five columns. An envelope rejection carries no `row` and no
  `expected`/`actual`, so a missing form field was being presented in the shape of a failed
  measurement, and `DUPLICATE_NAME` — which carries no `details` at all — drew an empty table.
- Chose: build the column list from the keys the response actually carries. Zero details renders
  no table at all, just the code, the message, and the raw body.
- Added a remedy line keyed by envelope code (`DUPLICATE_NAME`, `UNKNOWN_SCHEMA`,
  `AMBIGUOUS_SCHEMA`, `NO_SCHEMA_REGISTERED`, …) saying what to do next. The API's own message says
  what happened; the remedy says what to do, and neither replaces the other.
- Also fixed here: the section descriptions sat as a narrow column beside the controls rather than
  under them. `flex: 1 0 100%` did not wrap them, because `max-width` clamps the hypothetical main
  size back under the container width — the fix was structural, moving the note out of the flex row
  rather than fighting the basis.

### D-50 — The pre-send check covers every section, and catches taken names too
- Context: D-48 added the check to section 1 only. Sections 2, 3 and 4 still round-tripped a blank
  or duplicate submission into the red finding log — submitting untouched specimen rows produced a
  six-entry `MISSING_REQUIRED_FIELD` table, and re-registering a report produced a bare `409`.
- Chose: the same check in all four. Section 2 catches empty rows and rows missing a required
  parameter, marking every offending cell; section 3 catches a blank report name, no views, a
  determination with no parameter and a table with no columns; section 4 catches no report chosen.
- Also chose: catch a name that is already registered. The UI holds the registered list from
  `GET /schema` and `GET /dashboard`, so it can say "already on file, choose another name" without
  asking. The server still enforces uniqueness — this removes an avoidable round trip, it does not
  move the rule into the client.
- Copy corrected: the summary line said "N fields need a value", which is false for a duplicate
  name — the field has a value, it is simply taken. It now reads "Nothing was sent. N problems to
  fix."
- Unchanged: JSON mode still skips the check entirely, so every one of these failures is still
  reachable on purpose. The point was never to hide them.

### D-51 — Section descriptions were set too narrow for the column they sit in
- Context: the sheet is 1120px wide because the data grids need it. The section notes were capped
  at 68ch, then 78ch, and still read as a narrow column against a large empty right side.
- Chose: 16px at 92ch, which fills roughly 79% of the column and reads as a lede rather than a
  secondary caption. The binding notes follow at 14px/92ch.
- Knowingly past the 65-75ch measure that is good practice for running prose. These are one- and
  two-line intros, not body copy, and the alternative was leaving a third of every section blank.

### D-52 — The failure demonstration had to stop looking like a normal action
- Context: "Load a nonconforming batch" sat in the action row beside "Submit batch". Clicking it
  only *loaded* an invalid payload; the failure arrived on the next click of Submit. So a user who
  had not read the label carefully submitted what looked like their own data and got a red 422 they
  had not asked for. Reported from real use, twice.
- Chose: one action, one click, kept apart. It is now "Demonstrate a rejected batch", below a
  dashed rule, outside the action row, with a sentence beside it saying what it builds and that
  **this one is meant to fail**. Loading and submitting are a single gesture, so an invalid payload
  can no longer be submitted by someone who thinks it is theirs.
- Rejected: removing the demonstration. It is the only way to see the full error contract without
  hand-writing JSON, and BR-5 is the requirement it serves. The problem was its placement, not its
  existence.
- Rejected: suppressing the error it produces. The user asked for one, and the contract is the
  thing being shown.

### D-53 — The section description spans the section, not a reading measure
- Context: raised three times from real use. At 92ch the description stopped about 220px short of
  the right edge of the grid directly beneath it, so the text did not line up with its own section
  and the block read as unfinished.
- Chose: `max-width: none`, so the description runs to the same right edge as the grid below it,
  with `text-wrap: pretty` and 1.55 line-height to keep the rag and the last line reasonable.
- Knowingly long: about 138ch at the sheet's full width. The alternative was a paragraph that does
  not align with anything else in its own section, and every section here is one or two lines of
  intro rather than running copy. Recorded so that a future surface with real prose does not read
  this as licence: that one goes back to a measure.

### D-54 — Error codes left the UI; findings became sentences
- Context: a rejected registration led with `VALIDATION_FAILED`, `HTTP 422`, and a finding table
  whose columns were `field / code / expected / actual`. Reported from real use: the row read
  `test · INVALID_AGGREGATION · — · string`, and `actual: "string"` is the *field's type*, not the
  aggregation that failed on it. A reader who has not read `errors.py` concludes the string was the
  problem. Every honest value in that row, and the row still misleads.
- Chose: the panel says what happened, what it cost, and what to do — "The specification was not
  registered. One thing to fix; nothing was stored." followed by one sentence per finding:
  *"sum" cannot apply to "test", which holds text. Use count instead, or change the parameter to a
  number type.* Codes never reach the page. Each sentence ends in an action, and names a section
  when the fix is somewhere else.
- The sentence needs the aggregation the response does not carry, so `chosenAggregation` reads it
  back off the body the panel posted. The alternative was widening the contract to carry it, which
  is a backend change for a frontend problem (D-44 holds: `backend/` stays as it is).
- Rejected: dropping the raw body. D-45 is a contract about values, not about visibility, and the
  error contract is a graded deliverable. It moved behind a "Technical details" disclosure with the
  status line, so it is one click away and never the first thing a reader meets.
- Rejected: keeping the table alongside the prose. Two accounts of the same failure, and the reader
  has to work out that they agree.
- A locator chip is printed only when it adds location the sentence does not already carry:
  `Row 0 · amount` earns one, a finding on a single named parameter does not.

### D-55 — Every aggregation is offered; the illegal ones say why
- Context: the aggregation select was built from `aggsFor(type)`, so a `string` parameter offered
  exactly `count`. Read from real use as "this platform has one aggregation" — the opposite of what
  the registry says, and NFR-2's whole argument is that the registry is the interesting part.
- Chose: every registered aggregation appears on every parameter. The ones the type cannot carry
  are `disabled` and labelled with the reason — `sum — numeric parameters only`. The legality rule
  is now visible instead of being enforced by absence.
- A value the type cannot carry can still arrive from the JSON hatch. The option stays selected and
  the control is marked, so the select never reads as something other than what will be sent, and
  the pre-send check (D-48) names it before the round trip rather than after.
- Rejected: hiding illegal options but adding a note under the grid. A note is read once; the
  disabled option is read at the moment the question is asked.

### D-56 — A failure with one obvious next move offers it
- Context: a duplicate name (409) is the only failure here where the fix is mechanical — the name
  is taken, and the user wants a free one.
- Chose: the panel offers it as a button — `Use "trade-2" instead` — which fills the name field and
  focuses it. The same button appears on the pre-send check, which catches most duplicates before
  they are sent, so the two paths behave identically. Other failures get the same treatment where
  the move is unambiguous: an unknown or ambiguous schema focuses the binding select, an empty
  platform sends the reader to section 1.
- Rejected: renaming automatically and resending. Naming is the user's decision, and D-2 exists
  because silently resolving a name collision is precisely what this platform refuses to do.
- A network failure is now a diagnosis too, not an unhandled rejection: `fetch` rejecting returns
  status 0, which the panel reports as "The platform did not answer" with the note that this page
  is served by the API it just failed to reach.

### D-57 — "Demonstrate a rejected batch" removed; D-52 reversed
- Context: checked back against `round_1_assignment.pdf`. The Bonus section asks for a UI that
  does four things — register schemas, submit data, register dashboard configurations, view
  generated dashboard data. A control whose purpose is to fail is not one of them. "Return
  validation errors where appropriate" sits in requirement 2, *Ingest Data*, and is a statement
  about the API, not about the UI.
- Chose: removed the button, its note, `nonconformingBatch`, `sampleValue` and the `.demo` styles.
  BR-5 is now reached the way anyone reaches it — by getting something wrong, or by editing a
  payload in the raw-JSON view BR-6 keeps on every panel.
- This reverses D-52, which kept the demonstration and fixed its placement. D-52's premise was
  that it is "the only way to see the full error contract without hand-writing JSON", and both
  halves of that have since weakened: D-54 made every real failure legible without reading the
  contract at all, and the JSON view was always the other way in. What is left is a self-inflicted
  failure on a page whose four other actions are the brief's four actions — which reads as an
  unrequested feature, and the brief's own scope discipline is what is being graded.
- D-52's finding stands as history and is worth keeping in the log: the control confused real users
  twice before it was isolated. That it needed two rounds of placement work to stop misfiring is
  itself an argument that it did not belong.
- Kept: the pre-send check (D-48, D-50) and the JSON escape hatch (BR-6). Nothing about the error
  contract became unreachable.

### D-58 — The failure panel fills its own box, the way D-53 made descriptions fill theirs
- Context: the panel's headline, lead, and finding sentences were capped at `--measure` (68ch)
  inside a box roughly 1120px wide. The result was a column of text against a wide field of red,
  and the box read as a fragment rather than as a block — the same complaint D-53 answered for
  section descriptions, on a surface that had kept the old cap.
- Chose: `max-width: none` on `.oos-msg`, `.oos-lead`, `.oos-list`, `.oos-more` and the two
  `.precheck` blocks, with `text-wrap: pretty` to keep the rag and the last line reasonable. Most
  findings now set on one line, which is also the honest shape for them: each is a single sentence
  about a single thing.
- The flex rows needed `min-width: 0` on the text child so a long unbroken token cannot push the
  line past the box instead of wrapping inside it.
- Checked at 560px: the sentences wrap, the box keeps its 16px gutter, and `scrollWidth` still
  equals `clientWidth`, so nothing gained a horizontal scroll.

### D-59 — The sheet scales with the display, so the page opens at a readable size
- Context: reported from real use — "completely zoomed out, I have to zoom in and scroll". Every
  dimension here is px, tuned at the 1120px the data grids need (D-51). On a 2560px display that
  lands as a 1120px band of 15px type occupying 44% of the screen, and the first thing a reader
  does is reach for the browser's own zoom. The page was correct and unreadable at the same time.
- Chose: `:root { zoom }` in steps — 1.1 at 1440px, up to 2 at 3600px — so the page arrives at the
  size the reader would have zoomed it to. Below 1440px nothing changes; the design as drawn is
  what a laptop already gets.
- Rejected: a fluid `vw` type scale. The stylesheet is px throughout — type, rules, control
  heights, grid column widths — so a fluid scale means converting ~80 declarations and re-tuning
  the grids at every size. `zoom` scales all of it in one move and keeps the proportions exactly
  as drawn.
- Rejected: widening the sheet on large displays instead. That gives more grid room but leaves the
  type at 15px, which is the half of the problem the reader actually feels.
- `zoom` and `vw` do not mix — `vw` resolves against the unzoomed viewport and would then be
  multiplied by the zoom. Checked: every `vw` here is inside a `clamp()` whose px ceiling is
  reached long before these widths, so none of them is live where the zoom is.
- Verified at 1512, 2560 and 3840: `scrollWidth` equals `clientWidth` at each, so nothing gained a
  horizontal scrollbar, and the fixed footer still measures the full viewport width (`left` 0,
  `right` = `innerWidth`) rather than being scaled inside it.
