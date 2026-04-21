"""Tests for first-install setup endpoints."""

from pathlib import Path

import pytest
from docker.errors import DockerException
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_setup_status_defaults_to_not_initialized(client: AsyncClient):
    res = await client.get("/api/setup/status")

    assert res.status_code == 200
    assert res.json()["initialized"] is False


@pytest.mark.asyncio
async def test_setup_preflight_returns_validation_errors(client: AsyncClient, monkeypatch):
    def _raise_docker_exception():
        raise DockerException("docker unavailable")

    monkeypatch.setattr("app.services.setup_service.docker.from_env", _raise_docker_exception)

    res = await client.post(
        "/api/setup/preflight",
        json={
            "domain": "bad_domain",
            "acme_email": "bad-email",
            "enable_https": True,
            "use_staging_acme": False,
            "cors_origins": ["http://localhost:5173"],
        },
    )

    assert res.status_code == 200
    payload = res.json()
    assert payload["valid"] is False
    assert any(issue["code"] == "invalid_domain" for issue in payload["errors"])
    assert any(issue["code"] == "invalid_email" for issue in payload["errors"])


@pytest.mark.asyncio
async def test_setup_preflight_allows_local_https_with_warning(client: AsyncClient, monkeypatch):
    class DockerClientMock:
        def ping(self):
            return True

        def close(self):
            return None

    monkeypatch.setattr("app.services.setup_service.docker.from_env", lambda: DockerClientMock())

    res = await client.post(
        "/api/setup/preflight",
        json={
            "domain": "127.0.0.1",
            "acme_email": "admin@example.com",
            "enable_https": True,
            "use_staging_acme": False,
            "cors_origins": ["https://127.0.0.1"],
        },
    )

    assert res.status_code == 200
    payload = res.json()
    assert payload["valid"] is True
    assert payload["errors"] == []
    assert any(issue["code"] == "local_cert_untrusted" for issue in payload["warnings"])
    assert any(
        check["name"] == "dns_lookup" and check["status"] == "pass"
        for check in payload["checks"]
    )


@pytest.mark.asyncio
async def test_setup_initialize_writes_env_and_persists_state(
    client: AsyncClient,
    monkeypatch,
    tmp_path: Path,
):
    (tmp_path / "backend").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("app.services.setup_service._repo_root", lambda: tmp_path)

    class DockerClientMock:
        def ping(self):
            return True

        def close(self):
            return None

    monkeypatch.setattr("app.services.setup_service.docker.from_env", lambda: DockerClientMock())

    res = await client.post(
        "/api/setup/initialize",
        json={
            "domain": "home.example.com",
            "acme_email": "admin@example.com",
            "enable_https": True,
            "use_staging_acme": True,
            "cors_origins": ["https://home.example.com"],
        },
    )

    assert res.status_code == 200
    payload = res.json()
    assert payload["status"] == "ok"

    status_res = await client.get("/api/setup/status")
    assert status_res.status_code == 200
    assert status_res.json()["initialized"] is True

    root_env = (tmp_path / ".env").read_text(encoding="utf-8")
    backend_env = (tmp_path / "backend" / ".env").read_text(encoding="utf-8")

    assert "DOMAIN=home.example.com" in root_env
    assert "ACME_EMAIL=admin@example.com" in root_env
    assert "SITE_ADDRESS=home.example.com" in root_env
    assert "acme-staging-v02.api.letsencrypt.org" in root_env
    assert "DOMAIN=https://home.example.com" in backend_env
    assert "CORS_ORIGINS=https://home.example.com" in backend_env
