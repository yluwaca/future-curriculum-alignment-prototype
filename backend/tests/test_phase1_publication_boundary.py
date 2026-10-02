"""Static publication-boundary checks for portable deployment files."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_uat_compose_requires_injected_database_password() -> None:
    compose = (ROOT / "scripts" / "uat" / "docker-compose.yml").read_text(
        encoding="utf-8"
    )

    assert "POSTGRES_PASSWORD must be injected" in compose
    assert "1Np3ns10ns" not in compose


def test_uat_environment_generator_creates_database_password() -> None:
    generator = (ROOT / "scripts" / "uat" / "01-generate-env.sh").read_text(
        encoding="utf-8"
    )

    assert "PG_PASS=$(openssl rand -hex 24)" in generator
    assert 'cat "$ENV_FILE"' not in generator
    assert "1Np3ns10ns" not in generator


def test_reviewed_environment_examples_can_be_versioned() -> None:
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

    assert "!.env.example" in ignore
    assert "!.env.production.example" in ignore
