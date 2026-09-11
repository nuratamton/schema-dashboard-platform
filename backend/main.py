"""FastAPI application entry point.

Wires the routers, mounts the frontend, and installs the exception handlers
that map core exceptions onto the single error contract (NFR-5, NFR-6).

Note: FastAPI's default RequestValidationError response body does not match our
contract. Override it.

Run:
    uvicorn backend.main:app --reload

TODO(T10): create the app, include routers, install exception handlers.
TODO(T12): serve frontend/index.html at "/".
"""
