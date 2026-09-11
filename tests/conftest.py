"""Shared pytest fixtures.

Suggested fixtures:
    client        -- FastAPI TestClient against a fresh app
    trade_schema  -- the brief's example schema payload
    trade_rows    -- valid example rows
    customer_*    -- a second, unrelated use case for tests/test_genericity.py

Keep domain fixtures HERE, never in backend/ (RULE-0).

TODO(T1+): add fixtures as the layers land.
"""
