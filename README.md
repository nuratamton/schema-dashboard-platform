# Schema-Driven Dashboard Platform

> **Skeleton — fill in at T13.** Prompts for each section are in the HTML comments.
> Delete this blockquote when you fill it in.

A generic platform for registering data schemas, ingesting validated data, configuring
dashboards, and generating dashboard output — where adding a new use case requires configuration
only, never code.

---

## Quick start

```bash
pip install -r requirements.txt
uvicorn backend.main:app --reload
```

- API docs: http://127.0.0.1:8000/docs
- UI: http://127.0.0.1:8000/

```bash
pytest -q
```

---

## Try it in 60 seconds

<!-- Four curl commands: register a schema, ingest rows, register a dashboard, GET it.
     A grader should be able to paste these straight into a terminal and see output.
     Use the brief's own trade example so it is instantly recognisable. -->

---

## API

<!-- One table: method, path, purpose, status codes. Keep it to a screen.
     FR-1 to FR-5 in REQUIREMENTS.md have everything you need. -->

---

## Architecture

<!-- The module tree from CLAUDE.md, plus two or three sentences on the dependency rule
     (api -> core -> store, never the reverse) and why the three registries exist.

     Then the sentence that matters most:
       "There is no use-case-specific code anywhere in backend/. `grep -ri trade backend/`
        returns nothing. Trade and Customer are both supported by configuration alone." -->

---

## Design decisions

<!-- THE MOST IMPORTANT SECTION. The panel spends 60-90 minutes on your reasoning, not your
     syntax. Pull D-1 to D-6 from DECISIONS.md plus anything logged during the build.

     For each: what you chose, what you rejected, and why. Show the tradeoff, not just the
     verdict. A decision presented without its discarded alternative reads as a default. -->

---

## Gaps in the specification

<!-- Lead with the dashboard-config schema binding (D-3). The brief's example config references
     `field: amount` but binds to no schema, so with two schemas registered it cannot be
     resolved -- on an assignment whose whole premise is supporting multiple use cases at once.

     Then the smaller ones: aggregation declared in two places with no stated precedence,
     undefined batch semantics on ingest, undefined re-registration behaviour, unspecified type
     system, undefined `required` default, no read endpoints.

     Say how each was resolved and why. This section is the clearest evidence that the brief was
     read as a specification rather than a checklist. -->

---

## Extension points

<!-- Short. For each, name the one file that changes:
       new field type       -> core/types.py registration
       new aggregation      -> core/aggregations.py registration
       new view type        -> one handler in core/views.py
       database persistence -> one new implementation of store/base.py
     Then filtering, grouping, sorting, pagination, schema versioning -- named as deliberate
     exclusions with a line on where each would attach. -->

---

## What was deliberately left out

<!-- The brief's exclusions: auth, authz, databases, deployment, LLM integrations, advanced
     visualisations. Plus your own: filtering, sorting, pagination, versioning, concurrency.

     Keep this section. Scope discipline is a signal, and stating it explicitly stops a grader
     from reading an omission as an oversight. -->

---

## Testing

<!-- What the suite covers and how to run it. Call out tests/test_genericity.py by name:
     it runs a second, unrelated use case end to end with zero backend changes, which is the
     assignment's actual pass condition. -->
