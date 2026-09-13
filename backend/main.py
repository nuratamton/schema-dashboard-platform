"""FastAPI application entry point.

Wires the routers, mounts the frontend, and installs the exception handlers
that map core exceptions onto the single error contract (NFR-5, NFR-6).

Note: FastAPI's default RequestValidationError response body does not match our
contract. Override it.

The bonus UI is served from "/" by this app rather than opened off disk. That is
not a convenience: a page loaded over file:// would make every fetch
cross-origin, and the fix for *that* is CORS middleware the brief never asked
for. Serving the file same-origin removes the problem instead of configuring
around it.

Run:
    uvicorn backend.main:app --reload
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.api import dashboards, ingest, schemas
from backend.core.errors import (
    ErrorCode,
    PlatformError,
    ValidationIssue,
    error_response,
)

app = FastAPI(
    title="Schema-Driven Dashboard Platform",
    description=(
        "Register a schema, ingest rows against it, configure a dashboard, and "
        "generate it. Adding a use case is configuration; there is no "
        "use-case-specific code in the backend."
    ),
    version="1.0.0",
)

app.include_router(schemas.router)
app.include_router(ingest.router)
app.include_router(dashboards.router)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    """Liveness check (FR-5.4)."""
    return {"status": "ok"}


_UI_DIR = Path(__file__).resolve().parent.parent / "frontend"


@app.get("/", include_in_schema=False)
def ui() -> FileResponse:
    """Serve the bonus UI (REQUIREMENTS.md section 4)."""
    return FileResponse(_UI_DIR / "index.html", media_type="text/html")


# The UI's stylesheet, script and self-hosted fonts. Mounted rather than routed
# one-by-one so adding an asset needs no edit here. Deliberately *not* mounted at
# "/" -- that would hand unknown paths to Starlette's HTML 404 and break the one
# error contract NFR-5 promises.
app.mount("/static", StaticFiles(directory=_UI_DIR), name="static")


# ----------------------------------------------------------------------
# The single error contract (NFR-5, NFR-6)
# ----------------------------------------------------------------------


@app.exception_handler(PlatformError)
async def handle_platform_error(
    request: Request, exc: PlatformError
) -> JSONResponse:
    """Map every domain error to its status code and the NFR-5 envelope.

    One handler for every error type the platform raises. The status code is
    read off the instance rather than decided here, so adding an error type
    requires no edit to this function and there is no if-chain over exception
    types to fall out of date.

    ``content`` is JSONResponse's *first* positional parameter. Passing
    ``JSONResponse(exc.status_code, exc.to_response())`` would serialise the
    status code as the response body and return 200 -- hence the keywords.
    """
    return JSONResponse(content=exc.to_response(), status_code=exc.status_code)


#: Pydantic error types that have an exact counterpart in our vocabulary.
_ENVELOPE_CODES: dict[str, ErrorCode] = {
    "missing": ErrorCode.MISSING_REQUIRED_FIELD,
    "extra_forbidden": ErrorCode.UNKNOWN_FIELD,
    # An empty string and an empty list are not type problems -- the type is
    # exactly right, there is simply no usable value. `errors.py` already
    # defines MISSING_REQUIRED_FIELD as covering "no usable value supplied",
    # which is what a blank name and an empty fields/rows/views array are.
    # Calling those TYPE_MISMATCH sent the caller looking for a type error
    # that does not exist (DECISION-47).
    "string_too_short": ErrorCode.MISSING_REQUIRED_FIELD,
    "too_short": ErrorCode.MISSING_REQUIRED_FIELD,
}


def _location(location: tuple[Any, ...]) -> str | None:
    """Render a Pydantic error ``loc`` as a path: ``fields[0].name``.

    Matches the ``views[1].<field>`` form dashboard config errors already use,
    so one reading of ``field`` works across the whole contract.
    """
    parts = list(location)
    if parts and parts[0] in ("body", "query", "path", "header", "cookie"):
        parts = parts[1:]
    if not parts:
        return None

    rendered = str(parts[0])
    for part in parts[1:]:
        rendered += f"[{part}]" if isinstance(part, int) else f".{part}"
    return rendered


def _issue(error: dict[str, Any]) -> ValidationIssue:
    """Translate one Pydantic error into one :class:`ValidationIssue`."""
    error_type = str(error.get("type", ""))
    code = _ENVELOPE_CODES.get(error_type)
    if code is None:
        # Pydantic's remaining types are shape complaints -- string_type,
        # list_type, int_parsing. They are all "this is not the type the
        # envelope requires", which is what TYPE_MISMATCH says.
        code = ErrorCode.TYPE_MISMATCH
    # Pydantic's `msg` is an English sentence. `expected` names a *type*
    # everywhere else in the contract, and every domain-path error honours that,
    # so the key is omitted rather than filled with prose (DECISION-37). The code
    # already carries the meaning.
    return ValidationIssue(
        field=_location(tuple(error.get("loc", ()))),
        code=code,
    )


@app.exception_handler(RequestValidationError)
async def handle_request_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Reshape FastAPI's default 422 body into the NFR-5 contract.

    Without this, a malformed envelope returns ``{"detail": [...]}`` while every
    other failure returns ``{"error", "message", "details"}`` -- one API with two
    error formats, and the one a caller meets first is the odd one out.
    """
    issues = [_issue(error) for error in exc.errors()]
    problem = "problem" if len(issues) == 1 else "problems"
    return JSONResponse(
        content=error_response(
            ErrorCode.VALIDATION_FAILED,
            f"{len(issues)} {problem} found in the request body",
            issues,
        ),
        status_code=422,
    )


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    """Last resort. Anything unforeseen still answers in the NFR-5 contract.

    Registered below the typed :class:`PlatformError` handler, which keeps
    precedence -- Starlette resolves the most specific registered class first, so
    a 404 stays a 404 and only genuinely unexpected exceptions reach here.

    Without this, NFR-5's claim of one error contract across every endpoint is
    false: an unhandled exception returns Starlette's `text/plain` "Internal
    Server Error", which no client parsing our envelope can read, and which the
    UI cannot render because it fails `response.json()`.

    The edge that exposed it: `avg` over an integer too large to convert to a
    float raises OverflowError deep in the aggregation registry. That input is
    not special-cased -- a generic handler is the fix, because the next unforeseen
    exception will not be that one (DECISION-36).

    The message is deliberately generic. Echoing the exception text back would
    leak internals to a caller who can do nothing with them.
    """
    return JSONResponse(
        content=error_response(
            ErrorCode.INTERNAL_ERROR,
            "The request could not be completed because of an unexpected error",
        ),
        status_code=500,
    )
