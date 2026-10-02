import logging

from app.services.ingestion.statssa_service import StatsSAService

logger = logging.getLogger(__name__)


class JobIngestionService:
    """
    Orchestrates all labour market data ingestion
    """

    def __init__(self):
        pass

    # -----------------------------------------------------
    # Stats SA Extraction
    # -----------------------------------------------------
    def extract_statssa(self):

        logger.info("Triggering Stats SA ingestion...")

        service = StatsSAService()
        result = service.run_pipeline()

        return result