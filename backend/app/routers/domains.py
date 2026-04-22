"""Domains and SSL router for runtime route visibility and Caddy sync actions."""

from __future__ import annotations

import ipaddress
import socket
import ssl
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Mapping

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.app import App
from app.models.setting import Setting
from app.services.marketplace_service import sync_caddy_marketplace_routes
from app.services.setup_service import _repo_root

router = APIRouter(prefix="/api/domains", tags=["domains"])

_SETUP_KEYS = (
    "setup_domain",
    "setup_acme_email",
    "setup_https_enabled",
    "setup_acme_staging",
)

_TRUTHY = {"1", "true", "yes", "on"}


class CaddyRuntimeStatus(BaseModel):
    generated_globals_exists: bool
    generated_site_exists: bool
    marketplace_routes_exists: bool
    marketplace_route_count: int


class DomainRouteStatus(BaseModel):
    host: str
    source: Literal["dashboard", "marketplace"]
    target: str
    app_name: str | None = None
    dns_resolves: bool | None = None
    resolved_ips: list[str]
    ssl_status: Literal["disabled", "local", "active", "pending", "error"]
    cert_expiry: str | None = None
    cert_days_remaining: int | None = None
    cert_issuer: str | None = None
    cert_subject: str | None = None
    check_message: str


class DomainsOverviewResponse(BaseModel):
    configured: bool
    domain: str | None
    https_enabled: bool
    acme_email: str | None
    acme_staging: bool
    routes: list[DomainRouteStatus]
    caddy_runtime: CaddyRuntimeStatus


@dataclass
class _RouteProbe:
    dns_resolves: bool | None
    resolved_ips: list[str]
    ssl_status: Literal["disabled", "local", "active", "pending", "error"]
    cert_expiry: str | None
    cert_days_remaining: int | None
    cert_issuer: str | None
    cert_subject: str | None
    check_message: str


def _to_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in _TRUTHY


def _normalize_domain(value: str | None) -> str | None:
    if not value:
        return None
    domain = value.strip().lower()
    domain = domain.replace("http://", "").replace("https://", "")
    domain = domain.split("/", 1)[0]
    return domain or None


def _is_local_target(host: str) -> bool:
    if host == "localhost":
        return True

    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return host.endswith((".localhost", ".local", ".internal", ".home.arpa"))


def _extract_name(entries: object) -> str | None:
    if not isinstance(entries, tuple):
        return None

    parts: list[str] = []
    for group in entries:
        if not isinstance(group, tuple):
            continue
        for item in group:
            if not isinstance(item, tuple) or len(item) != 2:
                continue
            key, value = item
            if not isinstance(key, str) or not isinstance(value, str):
                continue
            parts.append(f"{key}={value}")

    return ", ".join(parts) if parts else None


def _resolve_dns(host: str) -> tuple[bool, list[str], str]:
    try:
        infos = socket.getaddrinfo(host, 443)
    except OSError as exc:
        return False, [], f"DNS lookup failed: {exc}"

    addresses_set: set[str] = set()
    for info in infos:
        sockaddr = info[4]
        if len(sockaddr) < 1:
            continue
        address = sockaddr[0]
        if isinstance(address, str):
            addresses_set.add(address)

    addresses = sorted(addresses_set)
    if not addresses:
        return False, [], "DNS lookup returned no IP addresses"
    return True, addresses, "DNS lookup succeeded"


def _fetch_tls_certificate(host: str) -> tuple[Mapping[str, object] | None, str | None]:
    context = ssl.create_default_context()
    try:
        with socket.create_connection((host, 443), timeout=3.5) as raw_sock:
            with context.wrap_socket(raw_sock, server_hostname=host) as tls_sock:
                cert = tls_sock.getpeercert()
                if isinstance(cert, dict):
                    return cert, None
                return None, "No TLS certificate received"
    except (TimeoutError, OSError, ssl.SSLError) as exc:
        return None, f"TLS probe failed: {exc}"


def _parse_not_after(value: object) -> tuple[str | None, int | None]:
    if not isinstance(value, str):
        return None, None

    try:
        expiry = datetime.strptime(value, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=UTC)
    except ValueError:
        return None, None

    delta_days = int((expiry - datetime.now(UTC)).total_seconds() // 86400)
    return expiry.isoformat(), delta_days


def _probe_route_ssl(host: str, https_enabled: bool, live_checks: bool) -> _RouteProbe:
    if not https_enabled:
        return _RouteProbe(
            dns_resolves=None,
            resolved_ips=[],
            ssl_status="disabled",
            cert_expiry=None,
            cert_days_remaining=None,
            cert_issuer=None,
            cert_subject=None,
            check_message="HTTPS is disabled in setup configuration.",
        )

    if _is_local_target(host):
        return _RouteProbe(
            dns_resolves=True,
            resolved_ips=[host],
            ssl_status="local",
            cert_expiry=None,
            cert_days_remaining=None,
            cert_issuer=None,
            cert_subject=None,
            check_message="Local or IP target detected; Caddy local CA certificates are expected.",
        )

    if not live_checks:
        return _RouteProbe(
            dns_resolves=None,
            resolved_ips=[],
            ssl_status="pending",
            cert_expiry=None,
            cert_days_remaining=None,
            cert_issuer=None,
            cert_subject=None,
            check_message=(
                "Live SSL checks are disabled. "
                "Enable them to probe DNS and certificates."
            ),
        )

    dns_ok, resolved_ips, dns_message = _resolve_dns(host)
    if not dns_ok:
        return _RouteProbe(
            dns_resolves=False,
            resolved_ips=resolved_ips,
            ssl_status="pending",
            cert_expiry=None,
            cert_days_remaining=None,
            cert_issuer=None,
            cert_subject=None,
            check_message=dns_message,
        )

    cert, cert_error = _fetch_tls_certificate(host)
    if cert is None:
        return _RouteProbe(
            dns_resolves=True,
            resolved_ips=resolved_ips,
            ssl_status="error",
            cert_expiry=None,
            cert_days_remaining=None,
            cert_issuer=None,
            cert_subject=None,
            check_message=cert_error or "TLS probe failed",
        )

    expiry, days_remaining = _parse_not_after(cert.get("notAfter"))
    issuer = _extract_name(cert.get("issuer"))
    subject = _extract_name(cert.get("subject"))
    ssl_status: Literal["active", "error"] = "active"

    if days_remaining is not None and days_remaining < 0:
        ssl_status = "error"

    message = "TLS certificate is available"
    if ssl_status == "error":
        message = "TLS certificate appears expired"

    return _RouteProbe(
        dns_resolves=True,
        resolved_ips=resolved_ips,
        ssl_status=ssl_status,
        cert_expiry=expiry,
        cert_days_remaining=days_remaining,
        cert_issuer=issuer,
        cert_subject=subject,
        check_message=message,
    )


def _count_marketplace_routes(path: Path) -> int:
    if not path.exists():
        return 0

    count = 0
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.endswith("{"):
            count += 1
    return count


def _read_caddy_runtime() -> CaddyRuntimeStatus:
    caddy_dir = _repo_root() / "caddy"
    generated_globals = caddy_dir / "generated_globals.caddy"
    generated_site = caddy_dir / "generated_site.caddy"
    marketplace_routes = caddy_dir / "marketplace_apps.caddy"

    return CaddyRuntimeStatus(
        generated_globals_exists=generated_globals.exists(),
        generated_site_exists=generated_site.exists(),
        marketplace_routes_exists=marketplace_routes.exists(),
        marketplace_route_count=_count_marketplace_routes(marketplace_routes),
    )


async def _load_setup_values(db: AsyncSession) -> dict[str, str]:
    rows = await db.execute(select(Setting.key, Setting.value).where(Setting.key.in_(_SETUP_KEYS)))
    values: dict[str, str] = {}
    for key, value in rows.all():
        if value is None:
            continue
        values[key] = value
    return values


@router.get("")
async def get_domains_overview(
    live_checks: bool = Query(False, description="Probe DNS and TLS certificate data"),
    db: AsyncSession = Depends(get_db),
) -> DomainsOverviewResponse:
    """Return setup domain configuration and per-route SSL visibility."""
    values = await _load_setup_values(db)
    domain = _normalize_domain(values.get("setup_domain"))
    https_enabled = _to_bool(values.get("setup_https_enabled"), default=True)
    acme_email = values.get("setup_acme_email")
    acme_staging = _to_bool(values.get("setup_acme_staging"), default=False)

    routes: list[DomainRouteStatus] = []
    if domain:
        root_probe = _probe_route_ssl(domain, https_enabled=https_enabled, live_checks=live_checks)
        routes.append(
            DomainRouteStatus(
                host=domain,
                source="dashboard",
                target="backend:8000",
                app_name=None,
                dns_resolves=root_probe.dns_resolves,
                resolved_ips=root_probe.resolved_ips,
                ssl_status=root_probe.ssl_status,
                cert_expiry=root_probe.cert_expiry,
                cert_days_remaining=root_probe.cert_days_remaining,
                cert_issuer=root_probe.cert_issuer,
                cert_subject=root_probe.cert_subject,
                check_message=root_probe.check_message,
            )
        )

        apps = await db.execute(select(App.app_name, App.host_port).order_by(App.app_name.asc()))
        for app_name, host_port in apps.all():
            host = f"{app_name}.{domain}"
            probe = _probe_route_ssl(host, https_enabled=https_enabled, live_checks=live_checks)
            routes.append(
                DomainRouteStatus(
                    host=host,
                    source="marketplace",
                    target=f"host.docker.internal:{host_port}",
                    app_name=app_name,
                    dns_resolves=probe.dns_resolves,
                    resolved_ips=probe.resolved_ips,
                    ssl_status=probe.ssl_status,
                    cert_expiry=probe.cert_expiry,
                    cert_days_remaining=probe.cert_days_remaining,
                    cert_issuer=probe.cert_issuer,
                    cert_subject=probe.cert_subject,
                    check_message=probe.check_message,
                )
            )

    return DomainsOverviewResponse(
        configured=domain is not None,
        domain=domain,
        https_enabled=https_enabled,
        acme_email=acme_email,
        acme_staging=acme_staging,
        routes=routes,
        caddy_runtime=_read_caddy_runtime(),
    )


@router.post("/sync")
async def sync_domain_routes(db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    """Force-sync marketplace domain routes into Caddy include configuration."""
    values = await _load_setup_values(db)
    domain = _normalize_domain(values.get("setup_domain"))

    rows = await db.execute(select(App.app_name, App.host_port))
    apps = [(name, port) for name, port in rows.all()]
    message = sync_caddy_marketplace_routes(apps, domain)

    return {
        "status": "ok",
        "message": message,
    }
