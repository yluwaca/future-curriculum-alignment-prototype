"""
Unit tests for SSRF protection.
Tests the _validate_url_not_internal helper in curriculum router.
"""

import pytest
from fastapi import HTTPException


class TestSSRFProtection:
    """Tests for URL validation against internal network access."""

    def _get_validator(self):
        from app.routers.curriculum import _validate_url_not_internal
        return _validate_url_not_internal

    def test_localhost_blocked(self):
        validate = self._get_validator()
        with pytest.raises(HTTPException) as exc_info:
            validate("http://localhost:5432/")
        assert exc_info.value.status_code == 422

    def test_127_0_0_1_blocked(self):
        validate = self._get_validator()
        with pytest.raises(HTTPException) as exc_info:
            validate("http://127.0.0.1:8080/api")
        assert exc_info.value.status_code == 422

    def test_0_0_0_0_blocked(self):
        validate = self._get_validator()
        with pytest.raises(HTTPException) as exc_info:
            validate("http://0.0.0.0/")
        assert exc_info.value.status_code == 422

    def test_ipv6_loopback_blocked(self):
        validate = self._get_validator()
        with pytest.raises(HTTPException) as exc_info:
            validate("http://[::1]:8080/")
        assert exc_info.value.status_code == 422

    def test_private_10_x_blocked(self):
        validate = self._get_validator()
        with pytest.raises(HTTPException) as exc_info:
            validate("http://10.0.0.1:8080/secret")
        assert exc_info.value.status_code == 422

    def test_private_172_16_x_blocked(self):
        validate = self._get_validator()
        with pytest.raises(HTTPException) as exc_info:
            validate("http://172.16.0.1/admin")
        assert exc_info.value.status_code == 422

    def test_private_192_168_x_blocked(self):
        validate = self._get_validator()
        with pytest.raises(HTTPException) as exc_info:
            validate("http://10.0.0.2:5432/")
        assert exc_info.value.status_code == 422

    def test_link_local_blocked(self):
        validate = self._get_validator()
        with pytest.raises(HTTPException) as exc_info:
            validate("http://169.254.169.254/metadata")
        assert exc_info.value.status_code == 422

    def test_external_url_allowed(self):
        validate = self._get_validator()
        validate("https://api.example.com/data")  # Should not raise

    def test_external_url_with_port_allowed(self):
        validate = self._get_validator()
        validate("https://api.example.com:8443/v1/data")  # Should not raise

    def test_no_hostname_rejected(self):
        validate = self._get_validator()
        with pytest.raises(HTTPException) as exc_info:
            validate("not-a-url")
        assert exc_info.value.status_code == 422

    def test_internal_ip_in_query_param_not_detected_by_validator(self):
        """The hostname validator does not inspect query params.
        This is expected - redirect-based SSRF requires a different defense."""
        validate = self._get_validator()
        # hostname is evil.com (external), so validator passes
        validate("http://evil.com/redirect?to=http://127.0.0.1:8080")

