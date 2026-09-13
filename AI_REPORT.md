# AI Report

## Tools used

**Claude (web)** — Used to to turn the brief into a specification: numbered requirements each with a test that would prove it, and fourteen tasks in dependency order. This is also where I found the gap in the brief (the example dashboard config doesn't say which schema it belongs to, which stops working the moment a second schema is registered.)

**Claude Code (terminal)** — to build it, one task per session against that specification. Implement, test, write down the decision, stop. No session ran ahead into the next task.

## Example prompts

Planning, before any code:

> Turn this brief into a numbered list of requirements. Each one needs a test that would prove it works. Where the brief is ambiguous, flag it — don't pick an answer for me

Building, one task at a time:

> Build the row validation engine, requirements FR-2.3 to FR-2.9. Rows arrive as plain dicts and must be validated by our own code, not by Pydantic — Pydantic would turn the string "1000" into the number 1000 and hide the exact bug we're testing for. Collect every error across every row; don't stop at the first one.

Breaking it, once everything passed:

> All the tests pass. Now try to break it. Where does this accept bad data without complaining, or return something the error contract doesn't cover? Rank what you find by how bad it is.

## A suggestion I accepted

I turned down the obvious way to document the API, because it meant writing the list of supported field types into a second file and the whole point of the design is that adding a type touches one file. I took the worse documentation as the price.

Claude offered a third option I hadn't thought of: generate that list at startup by asking the type registry what it holds. The docs now show every supported type, no type name is written down outside the registry, and adding one still touches one file. It removed a cost I had assumed was unavoidable.

## A suggestion I rejected

Opened directly from disk, the UI can't talk to the API — the browser treats it as a different origin and blocks every request. The suggestion was to add CORS middleware.

I rejected that and had FastAPI serve the page instead. CORS middleware would have meant shipping a permissive cross-origin policy in a submission to a bank, to fix a problem caused by how a file was opened. Removing the cause beats configuring around it.

## How I validated it

The test`tests/test_genericity.py`: a completely different use case where customers run end to end in the same app, both dashboards live at once, with zero lines of the backend changed. If that passes the platform is generic.

Two guard tests back it up. One greps the backend for domain words like `trade` and`amount` and fails if it finds any, so genericity is enforced rather than remembered. The other checks every requirement ID is referenced by a real test, it caught a typo'd ID on its first run. Underneath those, 529 tests written from the requirements rather than from the finished code.

The most useful thing I did was the breaking prompt above, because it proved one of my own decisions wrong. I'd allowed **`NaN` values through, reasoning that a dashboard showing**`NaN` would be obviously broken and someone would notice.FastAPI quietly converts`NaN` to`null`, and`null` is what this API returns for "no data here" so the dashboard reported an empty result while also reporting three rows.
