"""
Registry for planned external source connectors.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.data_source import DataSource
from app.services.future_hooks.base import ExternalSourceConnector, HookHealth
from app.services.future_hooks.connectors import (
    ERPConnector,
    IndustryAssociationSource,
    LMSConnector,
    ProfessionalBodySource,
    SISConnector,
)


class FutureHookRegistry:
    def __init__(self) -> None:
        connectors = [
            LMSConnector(),
            SISConnector(),
            ERPConnector(),
            ProfessionalBodySource(),
            IndustryAssociationSource(),
        ]
        self._connectors: Dict[str, ExternalSourceConnector] = {
            connector.connector_key: connector for connector in connectors
        }

    def list_connectors(self) -> List[ExternalSourceConnector]:
        return list(self._connectors.values())

    def get_connector(self, connector_key: str) -> Optional[ExternalSourceConnector]:
        return self._connectors.get(connector_key)

    def get_source(self, db: Session, connector_key: str) -> Optional[DataSource]:
        return (
            db.query(DataSource)
            .filter(DataSource.source_key == connector_key)
            .first()
        )

    def connector_metadata(
        self,
        db: Session,
        connector: ExternalSourceConnector,
    ) -> Dict[str, object]:
        source = self.get_source(db, connector.connector_key)
        config = source.config if source else {}
        health = connector.health_check(config or {})

        return {
            "connector_key": connector.connector_key,
            "display_name": connector.display_name,
            "source_category": connector.source_category,
            "source_type": connector.source_type,
            "connector_type": connector.connector_type,
            "capabilities": connector.capabilities,
            "registered_source_id": str(source.source_id) if source else None,
            "source_status": source.status if source else "missing",
            "is_authorised": bool(source.is_authorised) if source else False,
            "health": health,
        }

    def health_check(
        self,
        db: Session,
        connector_key: str,
    ) -> Optional[HookHealth]:
        connector = self.get_connector(connector_key)
        if not connector:
            return None

        source = self.get_source(db, connector_key)
        return connector.health_check(source.config if source else {})


future_hook_registry = FutureHookRegistry()

