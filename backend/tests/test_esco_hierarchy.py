"""Tests for ESCO occupation hierarchy and ISCO-08 bridge."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_list_esco_occupations_returns_paged_results(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.get("/api/v1/skills/occupations?limit=10", headers=auth_headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert isinstance(payload, list)
    if payload:
        occ = payload[0]
        assert "esco_occupation_id" in occ
        assert "preferred_label" in occ
        assert "code" in occ
        assert "top_concept" in occ


def test_list_occupations_top_concept_only(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.get(
        "/api/v1/skills/occupations?top_concept_only=true&limit=10",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    for occ in payload:
        assert occ["top_concept"] is True


def test_get_occupation_detail_includes_hierarchy(client: TestClient, auth_headers: dict[str, str]) -> None:
    list_resp = client.get("/api/v1/skills/occupations?limit=1", headers=auth_headers)
    assert list_resp.status_code == 200, list_resp.text
    occupations = list_resp.json()
    if not occupations:
        return
    occ_id = occupations[0]["esco_occupation_id"]
    detail_resp = client.get(f"/api/v1/skills/occupations/{occ_id}", headers=auth_headers)
    assert detail_resp.status_code == 200, detail_resp.text
    detail = detail_resp.json()
    assert detail["esco_occupation_id"] == occ_id
    assert "parent_id" in detail
    assert "broader_occupation_uri" in detail
    assert "children" in detail
    assert "essential_skills" in detail


def test_get_occupation_not_found_returns_404(client: TestClient, auth_headers: dict[str, str]) -> None:
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = client.get(f"/api/v1/skills/occupations/{fake_id}", headers=auth_headers)
    assert response.status_code == 404, response.text


def test_get_occupation_skills_returns_links(client: TestClient, auth_headers: dict[str, str]) -> None:
    list_resp = client.get("/api/v1/skills/occupations?limit=5", headers=auth_headers)
    assert list_resp.status_code == 200, list_resp.text
    occupations = list_resp.json()
    for occ in occupations:
        occ_id = occ["esco_occupation_id"]
        skills_resp = client.get(
            f"/api/v1/skills/occupations/{occ_id}/skills",
            headers=auth_headers,
        )
        assert skills_resp.status_code == 200, skills_resp.text
        skills = skills_resp.json()
        assert isinstance(skills, list)
        if skills:
            link = skills[0]
            assert "link_id" in link
            assert "occupation_id" in link
            assert "skill_id" in link
            assert "relationship_type" in link


def test_isco_bridge_returns_coverage(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.get("/api/v1/skills/occupations/isco-bridge", headers=auth_headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "total_occupations" in payload
    assert "unique_isco_codes" in payload
    assert "isco_coverage" in payload
    assert "isco_hierarchy" in payload
    hierarchy = payload["isco_hierarchy"]
    assert "major_groups" in hierarchy
    assert "unit_groups" in hierarchy
    assert payload["total_occupations"] > 0


def test_list_esco_skills_returns_skills(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.get("/api/v1/skills/esco?limit=10", headers=auth_headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert isinstance(payload, list)
    if payload:
        skill = payload[0]
        assert "esco_skill_id" in skill
        assert "preferred_label" in skill
        assert "taxonomy_version" in skill


def test_esco_crosswalk_returns_mapping_stats(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.get("/api/v1/skills/esco/crosswalk", headers=auth_headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "total_curriculum_skills" in payload
    assert "covered_by_esco" in payload
    assert "esco_coverage_pct" in payload
    assert "items" in payload
