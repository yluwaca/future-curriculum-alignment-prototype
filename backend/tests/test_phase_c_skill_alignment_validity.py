"""Production skill and alignment validity checks."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_skills_readiness_has_expected_sections(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.get("/api/v1/skills/readiness", headers=auth_headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["phase"] == "Skills Alignment Validity"
    assert 0 <= payload["score"] <= 1
    assert {"counts", "coverage", "next_actions"}.issubset(payload.keys())
    assert "esco_skill_coverage" in payload["coverage"]
    assert "calibrated_alignment_share" in payload["coverage"]


def test_alignment_calibration_summary_is_available(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.get("/api/v1/skills/alignment-calibration?limit=5", headers=auth_headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "alignment_scores" in payload
    assert "samples" in payload
    assert isinstance(payload["samples"], list)


def test_esco_import_dry_run_validates_payload_without_writing(client: TestClient, auth_headers: dict[str, str]) -> None:
    content = "conceptUri,preferredLabel,skillType,altLabels\nurn:test:esco,Test Skill,skill,test alias\n"
    response = client.post(
        "/api/v1/skills/esco/import?taxonomy_version=test&dry_run=true",
        headers=auth_headers,
        files={"file": ("esco_test.csv", content, "text/csv")},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["dry_run"] is True
    assert payload["records_seen"] == 1
    assert payload["valid_records"] == 1
    assert payload["skills_created"] == 0
    assert payload["esco_created"] == 0


def test_semantic_candidates_for_existing_skill(client: TestClient, auth_headers: dict[str, str]) -> None:
    skills_response = client.get("/api/v1/skills?limit=1", headers=auth_headers)
    assert skills_response.status_code == 200, skills_response.text
    skills = skills_response.json()
    if not skills:
        return
    skill_id = skills[0]["skill_id"]
    response = client.get(
        f"/api/v1/skills/semantic-candidates/{skill_id}?limit=3",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["source_skill"]["skill_id"] == skill_id
    assert isinstance(payload["candidates"], list)
