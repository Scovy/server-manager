"""Tests for domains and SSL overview endpoints."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app import App
from app.models.setting import Setting
from app.routers import domains as domains_router


@pytest.mark.asyncio
async def test_domains_overview_unconfigured(client: AsyncClient):
    res = await client.get("/api/domains")

    assert res.status_code == 200
    payload = res.json()
    assert payload["configured"] is False
    assert payload["domain"] is None
    assert payload["routes"] == []
    assert "caddy_runtime" in payload


@pytest.mark.asyncio
async def test_domains_overview_returns_root_and_marketplace_routes(
    client: AsyncClient,
    async_db: AsyncSession,
    monkeypatch,
):
    async_db.add_all(
        [
            Setting(key="setup_domain", value="scovy.vip"),
            Setting(key="setup_acme_email", value="admin@scovy.vip"),
            Setting(key="setup_https_enabled", value="true"),
            Setting(key="setup_acme_staging", value="false"),
            App(
                template_id="gitea",
                app_name="gitea",
                container_name="gitea",
                host_port=3000,
                app_dir="/tmp/gitea",
                compose_path="/tmp/gitea/docker-compose.yml",
                status="deployed",
            ),
        ]
    )
    await async_db.flush()

    monkeypatch.setattr(
        domains_router,
        "_probe_route_ssl",
        lambda *_args, **_kwargs: domains_router._RouteProbe(
            dns_resolves=True,
            resolved_ips=["203.0.113.10"],
            ssl_status="active",
            cert_expiry="2030-01-01T00:00:00+00:00",
            cert_days_remaining=999,
            cert_issuer="CN=Example Issuer",
            cert_subject="CN=Example Subject",
            check_message="TLS certificate is available",
        ),
    )

    res = await client.get("/api/domains?live_checks=true")

    assert res.status_code == 200
    payload = res.json()
    assert payload["configured"] is True
    assert payload["domain"] == "scovy.vip"
    assert payload["https_enabled"] is True

    routes = payload["routes"]
    assert len(routes) == 2
    hosts = {route["host"] for route in routes}
    assert "scovy.vip" in hosts
    assert "gitea.scovy.vip" in hosts
    assert all(route["ssl_status"] == "active" for route in routes)


@pytest.mark.asyncio
async def test_domains_sync_routes_calls_marketplace_sync(
    client: AsyncClient,
    async_db: AsyncSession,
    monkeypatch,
):
    async_db.add_all(
        [
            Setting(key="setup_domain", value="scovy.vip"),
            App(
                template_id="gitea",
                app_name="gitea",
                container_name="gitea",
                host_port=3000,
                app_dir="/tmp/gitea",
                compose_path="/tmp/gitea/docker-compose.yml",
                status="deployed",
            ),
        ]
    )
    await async_db.flush()

    monkeypatch.setattr(
        "app.routers.domains.sync_caddy_marketplace_routes",
        lambda apps, domain: f"synced {domain} ({len(apps)} apps)",
    )

    res = await client.post("/api/domains/sync")

    assert res.status_code == 200
    payload = res.json()
    assert payload["status"] == "ok"
    assert payload["message"] == "synced scovy.vip (1 apps)"
