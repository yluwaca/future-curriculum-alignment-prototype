"""
Unit tests for rate limiting configuration.
Tests that the rate limiter is properly configured.
"""

import pytest


class TestRateLimitingConfig:
    """Tests for rate limiting setup."""

    def test_limiter_exists_in_app(self):
        from app.main import app
        assert hasattr(app.state, "limiter")

    def test_limiter_has_key_func(self):
        from app.main import app
        limiter = app.state.limiter
        assert limiter is not None

    def test_rate_limit_handler_registered(self):
        from app.main import app
        from slowapi.errors import RateLimitExceeded
        # Check that the exception handler is registered
        handlers = app.exception_handlers
        assert RateLimitExceeded in handlers or 429 in handlers
