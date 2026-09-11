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

### D-7 —
- Context:
- Options considered:
- Chose:
- Rejected:
