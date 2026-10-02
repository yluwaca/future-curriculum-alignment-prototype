"""
Connector definition and source classification service.
"""

from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.connector_definition import ConnectorDefinition
from app.models.data_source import DataSource


class ConnectorRegistryService:
    """
    Resolves reusable connector definitions and applies source classification.
    """

    def list_definitions(
        self,
        db: Session,
        source_category: Optional[str] = None,
        ingestion_mode: Optional[str] = None,
        active_only: bool = True,
    ) -> List[ConnectorDefinition]:
        query = db.query(ConnectorDefinition)
        if source_category:
            query = query.filter(ConnectorDefinition.source_category == source_category)
        if ingestion_mode:
            query = query.filter(ConnectorDefinition.ingestion_mode == ingestion_mode)
        if active_only:
            query = query.filter(ConnectorDefinition.status == "active")
        return query.order_by(ConnectorDefinition.source_category, ConnectorDefinition.name).all()

    def get_definition_by_key(
        self,
        db: Session,
        connector_key: str,
    ) -> Optional[ConnectorDefinition]:
        return (
            db.query(ConnectorDefinition)
            .filter(ConnectorDefinition.connector_key == connector_key)
            .first()
        )

    def get_definition_by_id(
        self,
        db: Session,
        connector_definition_id: UUID,
    ) -> Optional[ConnectorDefinition]:
        return (
            db.query(ConnectorDefinition)
            .filter(ConnectorDefinition.connector_definition_id == connector_definition_id)
            .first()
        )

    def apply_definition_to_source(
        self,
        source: DataSource,
        definition: ConnectorDefinition,
        override_config: Optional[Dict[str, Any]] = None,
    ) -> DataSource:
        source.connector_definition_id = definition.connector_definition_id
        source.connector_type = definition.connector_key
        source.source_category = definition.source_category
        source.ingestion_mode = definition.ingestion_mode
        source.source_format = definition.source_format
        source.normaliser_key = definition.normaliser_key
        source.config = {
            **(definition.default_config or {}),
            **(source.config or {}),
            **(override_config or {}),
            "connector_family": definition.connector_family,
            "is_streaming_capable": definition.is_streaming_capable,
            "requires_auth": definition.requires_auth,
        }
        return source

    def source_classification(self, source: DataSource) -> Dict[str, Any]:
        return {
            "source_id": str(source.source_id),
            "source_key": source.source_key,
            "tenant_id": str(source.tenant_id) if source.tenant_id else None,
            "source_scope": source.source_scope,
            "source_category": source.source_category,
            "source_type": source.source_type,
            "connector_type": source.connector_type,
            "connector_definition_id": str(source.connector_definition_id) if source.connector_definition_id else None,
            "ingestion_mode": source.ingestion_mode,
            "source_format": source.source_format,
            "normaliser_key": source.normaliser_key,
            "is_shared_platform_source": source.tenant_id is None and source.source_scope == "shared",
            "is_tenant_source": source.tenant_id is not None or source.source_scope == "tenant",
            "resilience": {
                "retry_policy": source.retry_policy or {},
                "last_success_at": source.last_success_at.isoformat() if source.last_success_at else None,
                "last_failure_at": source.last_failure_at.isoformat() if source.last_failure_at else None,
                "consecutive_failures": source.consecutive_failures or 0,
                "circuit_state": source.circuit_state,
                "circuit_open_until": source.circuit_open_until.isoformat() if source.circuit_open_until else None,
            },
            "config": source.config or {},
        }


connector_registry_service = ConnectorRegistryService()
