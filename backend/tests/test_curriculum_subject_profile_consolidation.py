from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from app.routers.curriculum import _latest_subject_profiles


def _profile(document_id, subject_code, created_at):
    return SimpleNamespace(
        profile_id=uuid4(),
        document_id=document_id,
        subject_code=subject_code,
        created_at=created_at,
    )


def test_latest_version_profile_is_authoritative_per_document_and_subject():
    document_id = uuid4()
    earlier = _profile(document_id, "PFD470S", datetime(2026, 9, 6, 10, 0, 0))
    latest = _profile(document_id, "PFD470S", earlier.created_at + timedelta(minutes=5))

    result = _latest_subject_profiles([latest, earlier])

    assert result == [latest]


def test_profiles_from_different_documents_remain_independently_reviewable():
    now = datetime(2026, 9, 6, 10, 0, 0)
    first = _profile(uuid4(), "PFD470S", now)
    second = _profile(uuid4(), "PFD470S", now)

    result = _latest_subject_profiles([first, second])

    assert set(profile.profile_id for profile in result) == {first.profile_id, second.profile_id}
