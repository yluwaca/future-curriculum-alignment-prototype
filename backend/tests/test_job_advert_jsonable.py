from uuid import uuid4

from app.services.ingestion.job_advert_file_connector import JobAdvertFileConnector


def test_jsonable_converts_uuid_provenance_fields():
    value = uuid4()
    payload = JobAdvertFileConnector.jsonable({"source_id": value, "nested": [value]})
    assert payload == {"source_id": str(value), "nested": [str(value)]}
