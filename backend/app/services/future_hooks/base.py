"""
Shared contracts for future external data and intelligence hooks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Protocol


@dataclass(frozen=True)
class HookHealth:
    status: str
    message: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HookResult:
    status: str
    message: str
    payload: Dict[str, Any] = field(default_factory=dict)


class ExternalSourceConnector(Protocol):
    connector_key: str
    display_name: str
    source_category: str
    source_type: str
    connector_type: str
    capabilities: List[str]

    def validate_config(self, config: Dict[str, Any]) -> HookHealth:
        ...

    def health_check(self, config: Dict[str, Any]) -> HookHealth:
        ...

    def discover(self, config: Dict[str, Any]) -> HookResult:
        ...

    def ingest(self, config: Dict[str, Any]) -> HookResult:
        ...


class PlannedConnector:
    """
    Base class for connectors whose integration contract exists before the
    external system is configured.
    """

    connector_key = ""
    display_name = ""
    source_category = "institutional"
    source_type = "planned_connector"
    connector_type = "planned"
    capabilities: List[str] = []

    def validate_config(self, config: Dict[str, Any]) -> HookHealth:
        configured = bool(config.get("enabled") and config.get("endpoint"))
        if configured:
            return HookHealth(
                status="configured",
                message="Connector has enough configuration to be implemented.",
                details={"required_runtime": "adapter_implementation"},
            )

        return HookHealth(
            status="not_configured",
            message="Connector contract is registered, but no external system is configured yet.",
            details={
                "required_fields": ["enabled", "endpoint"],
                "capabilities": self.capabilities,
            },
        )

    def health_check(self, config: Dict[str, Any]) -> HookHealth:
        return self.validate_config(config)

    def discover(self, config: Dict[str, Any]) -> HookResult:
        return HookResult(
            status="not_implemented",
            message="Discovery is available as a contract and will run once an adapter is implemented.",
            payload={"connector_key": self.connector_key},
        )

    def ingest(self, config: Dict[str, Any]) -> HookResult:
        return HookResult(
            status="not_implemented",
            message="Ingestion is available as a contract and will run once an adapter is implemented.",
            payload={"connector_key": self.connector_key},
        )

