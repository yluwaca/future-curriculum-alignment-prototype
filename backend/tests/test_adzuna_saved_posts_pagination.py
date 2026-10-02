"""Saved-post browsing preserves pagination and duplicate-run provenance."""
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from app.routers.ingestion import adzuna_posts


def test_saved_posts_apply_offset_limit_and_return_total(monkeypatch):
    tenant = uuid4()
    source = SimpleNamespace(name='Adzuna')
    posting = SimpleNamespace(posting_id=uuid4(), job_id='ADZUNA-TRIAL-123', job_title='Python Developer', region='Cape Town', posted_date=None, job_description='Python', source_url='https://example.com', ingestion_job_id=uuid4())
    query = MagicMock()
    query.join.return_value = query
    query.filter.return_value = query
    query.order_by.return_value = query
    query.offset.return_value = query
    query.limit.return_value = query
    query.count.return_value = 151
    query.all.return_value = [(posting, source)]
    db = MagicMock(); db.query.return_value = query
    result = adzuna_posts(job_id=None, limit=50, offset=100, db=db, current_user=SimpleNamespace(tenant_id=tenant))
    query.offset.assert_called_once_with(100)
    query.limit.assert_called_once_with(50)
    assert result['total'] == 151 and result['has_more'] is True
    assert result['items'][0]['job_id'] == 'ADZUNA-TRIAL-123'


def test_duplicate_only_job_uses_raw_record_membership():
    tenant = uuid4(); job_id = uuid4()
    query = MagicMock()
    for method in ('join', 'filter', 'order_by', 'offset', 'limit'):
        getattr(query, method).return_value = query
    query.count.return_value = 150; query.all.return_value = []
    db = MagicMock(); db.query.return_value = query
    db.get.return_value = SimpleNamespace(tenant_id=tenant)
    # Use a real SQLAlchemy subquery so the membership expression is exercised.
    from sqlalchemy import select
    from app.models.raw_ingestion_record import RawIngestionRecord
    raw = SimpleNamespace(filter=lambda *args: select(RawIngestionRecord.source_record_id).where(*args))
    db.query.side_effect = [query, raw]
    result = adzuna_posts(job_id=job_id, limit=50, offset=0, db=db, current_user=SimpleNamespace(tenant_id=tenant))
    clause = str(query.filter.call_args_list[-1].args[0])
    assert 'raw_ingestion_record' in clause and 'source_record_id' in clause
    assert result['total'] == 150


def test_saved_posts_reject_another_tenants_job():
    db = MagicMock(); db.get.return_value = SimpleNamespace(tenant_id=uuid4())
    with pytest.raises(HTTPException) as error:
        adzuna_posts(job_id=uuid4(), limit=50, offset=0, db=db, current_user=SimpleNamespace(tenant_id=uuid4()))
    assert error.value.status_code == 404
