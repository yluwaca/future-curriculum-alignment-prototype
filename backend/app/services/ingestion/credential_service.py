"""
Credential handling for ingestion sources.

The current deployment keeps source credentials in the application database,
but values should not be returned to clients in plain text.  This service
encrypts secrets using Fernet symmetric encryption.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any, Dict

from cryptography.fernet import Fernet

from app.core.config import settings


SECRET_FIELD_HINTS = {
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "token",
    "password",
    "client_secret",
    "secret",
}


class CredentialService:
    def __init__(self) -> None:
        digest = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(digest))

    def is_secret_field(self, key: str) -> bool:
        lowered = key.lower()
        return lowered in SECRET_FIELD_HINTS or any(hint in lowered for hint in SECRET_FIELD_HINTS)

    def encrypt_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        encrypted: Dict[str, Any] = {}
        for key, value in (config or {}).items():
            if self.is_secret_field(key) and value not in (None, ""):
                encrypted[key] = self.encrypt_value(str(value))
            else:
                encrypted[key] = value
        return {
            "_credential_format": "fernet",
            **encrypted,
        }

    def decrypt_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        decrypted: Dict[str, Any] = {}
        for key, value in (config or {}).items():
            if key == "_credential_format":
                continue
            if self.is_secret_field(key) and isinstance(value, str):
                decrypted[key] = self.decrypt_value(value)
            else:
                decrypted[key] = value
        return decrypted

    def mask_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        masked: Dict[str, Any] = {}
        for key, value in (config or {}).items():
            if key == "_credential_format":
                masked[key] = value
            elif self.is_secret_field(key) and value not in (None, ""):
                masked[key] = "***configured***"
            else:
                masked[key] = value
        return masked

    def encrypt_value(self, value: str) -> str:
        return "enc:" + self._fernet.encrypt(value.encode("utf-8")).decode("utf-8")

    def decrypt_value(self, value: str) -> str:
        if value.startswith("enc:"):
            return self._fernet.decrypt(value[4:].encode("utf-8")).decode("utf-8")
        raise ValueError(f"Invalid credential format: expected 'enc:' prefix, got '{value[:10]}...'")

    def fingerprint(self, config: Dict[str, Any]) -> str:
        safe = json.dumps(self.mask_config(config), sort_keys=True, default=str)
        return hashlib.sha256(safe.encode("utf-8")).hexdigest()[:16]


credential_service = CredentialService()
