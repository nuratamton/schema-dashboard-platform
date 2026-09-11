# AI Report

> **Skeleton — fill in at T14. Hard limit: one page.** Write it from `DECISIONS.md`.
> Delete this blockquote when you fill it in.

<!-- This is one of five evaluation criteria, and the recruiter's framing ("we are interested in
     how effectively you leverage available tools") says the process is being graded as much as
     the code. Treat it as a deliverable, not a cover note.

     One page means roughly 400-500 words. Cut ruthlessly. -->

## Tools used

<!-- Which tools, and what each was actually for -- not a list of everything you have installed.
     e.g. requirements decomposition and spec-gap analysis in one tool; per-task implementation
     in Claude Code at the terminal, one task per session against TASKS.md.

     The interesting claim available to you: the spec was decomposed and the gaps found BEFORE
     any code was written, and the implementation was then driven task by task against that
     spec. That is a workflow, not just usage. -->

## Example prompts

<!-- Two or three real ones, verbatim, chosen to show range:
       - one structural  (decompose this brief into numbered testable requirements)
       - one implementation (the T6 or T8 prompt from TASKS.md)
       - one adversarial (find the cases where this validation engine silently passes bad data)
     The third is the most differentiating -- most candidates only show generation prompts. -->

## A suggestion I accepted

<!-- One concrete case. What was suggested, why you took it, what it changed.
     Good candidate: the registry pattern for view handlers, if it came from the tool rather
     than from you. Be accurate about the provenance. -->

## A suggestion I rejected

<!-- The highest-signal item in this report. It must be real and specific.

     Log candidates as they occur during the build -- an over-engineered abstraction, a Pydantic
     model for row contents that would have silently coerced "1000" to 1000 and defeated the
     type-mismatch requirement, an unrequested feature, a convenient default that hides
     misconfiguration.

     State what was suggested, why it was plausible, and the specific reason it was wrong here.
     A rejection with a real technical reason behind it is what demonstrates judgement rather
     than compliance. Do not invent one. -->

## How I validated the solution

<!-- Say what you actually did, in order of strength:
       - the genericity acceptance test: a second unrelated use case end to end, zero backend
         changes (tests/test_genericity.py)
       - the grep assertion: no domain terms anywhere in backend/
       - edge-case tests written from the requirements, not from the implementation -- bool
         against number, "1000" against number, null in required vs optional, empty-dataset
         aggregations, multi-error batches
       - manual pass through the UI and /docs

     The point to land: AI wrote code, but the pass condition was defined before the code existed
     and the tests were derived from the requirements rather than from what was built. -->
