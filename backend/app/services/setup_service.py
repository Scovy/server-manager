"""Setup service for first-install onboarding and configuration writes."""

from __future__ import annotations

import os
import re
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import docker
from docker.errors import DockerException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.setting import Setting

SETUP_INITIALIZED_KEY = "setup_initialized"

DOMAIN_PATTERN = re.compile(
    r"^(?=.{1,253}$)(?!-)(?:[a-zA-Z0-9-]{1,63}\.)+[a-zA-Z]{2,63}$"
)
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass
class SetupCheck:
    name: str
    status: str
    message: str


@dataclass
class SetupIssue:
    code: str
    message: str
    field: str | None = None


@dataclass
class SetupPreflightResult:
    valid: bool
    errors: list[SetupIssue]
    warnings: list[SetupIssue]
    checks: list[SetupCheck]


@dataclass
class SetupPayload:
    domain: str
    acme_email: str
    enable_https: bool
    use_staging_acme: bool
    cors_origins: list[str]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _normalize_domain(value: str) -> str:
    domain = value.strip().lower()
    domain = domain.replace("http://", "").replace("https://", "")
    domain = domain.split("/", 1)[0]
    return domain


def _check_bindable(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("0.0.0.0", port))
            return True
        except OSError:
            return False


def _upsert_env_value(env_path: Path, key: str, value: str) -> None:
    lines: list[str] = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()

    prefix = f"{key}="
    replaced = False
    updated_lines: list[str] = []
    for line in lines:
        if line.startswith(prefix):
            updated_lines.append(f"{key}={value}")
            replaced = True
        else:
            updated_lines.append(line)

    if not replaced:
        updated_lines.append(f"{key}={value}")

    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text("\n".join(updated_lines).rstrip() + "\n", encoding="utf-8")


async def get_setup_status(db: AsyncSession) -> dict[str, object]:
    row = await db.execute(select(Setting).where(Setting.key == SETUP_INITIALIZED_KEY))
    initialized = row.scalar_one_or_none()
    return {
        "initialized": bool(initialized and initialized.value == "true"),
    }


def run_preflight(payload: SetupPayload) -> SetupPreflightResult:
    errors: list[SetupIssue] = []
    warnings: list[SetupIssue] = []
    checks: list[SetupCheck] = []

    domain = _normalize_domain(payload.domain)

    if payload.enable_https:
        if not domain or domain in {"localhost", "127.0.0.1"}:
            errors.append(
                SetupIssue(
                    code="invalid_domain",
                    message="HTTPS requires a public domain name (not localhost).",
                    field="domain",
                )
            )
        elif not DOMAIN_PATTERN.fullmatch(domain):
            errors.append(
                SetupIssue(
                    code="invalid_domain",
                    message="Domain format is invalid.",
                    field="domain",
                )
            )
        else:
            checks.append(SetupCheck("domain_format", "pass", "Domain format looks valid."))
    else:
        checks.append(SetupCheck("domain_format", "pass", "HTTP mode enabled for local setup."))

    if not EMAIL_PATTERN.fullmatch(payload.acme_email.strip()):
        errors.append(
            SetupIssue(
                code="invalid_email",
                message="ACME email format is invalid.",
                field="acme_email",
            )
        )
    else:
        checks.append(SetupCheck("acme_email", "pass", "ACME email format looks valid."))

    try:
        client = docker.from_env()
        client.ping()
        client.close()
        checks.append(SetupCheck("docker", "pass", "Docker daemon is reachable."))
    except DockerException as exc:
        errors.append(
            SetupIssue(
                code="docker_unavailable",
                message=f"Docker daemon check failed: {exc}",
            )
        )
        checks.append(SetupCheck("docker", "fail", "Docker daemon is not reachable."))

    if payload.enable_https:
        for port in (80, 443):
            if _check_bindable(port):
                checks.append(SetupCheck(f"port_{port}", "pass", f"Port {port} is available."))
            else:
                warnings.append(
                    SetupIssue(
                        code="port_in_use",
                        message=(
                            f"Port {port} is already in use. "
                            "Ensure reverse proxy setup is correct."
                        ),
                        field="domain",
                    )
                )
                checks.append(
                    SetupCheck(
                        f"port_{port}",
                        "warn",
                        f"Port {port} appears occupied.",
                    )
                )

    root_env = _repo_root() / ".env"
    backend_env = _repo_root() / "backend" / ".env"
    for label, env_path in (("root_env", root_env), ("backend_env", backend_env)):
        try:
            parent = env_path.parent
            parent_exists = parent.exists() and parent.is_dir()
            parent_writable = parent_exists and os.access(parent, os.W_OK)
            file_writable = not env_path.exists() or os.access(env_path, os.W_OK)
            if not (parent_writable and file_writable):
                raise OSError("insufficient write permissions")
            checks.append(SetupCheck(label, "pass", f"{env_path} is writable."))
        except OSError as exc:
            errors.append(
                SetupIssue(
                    code="file_not_writable",
                    message=f"Cannot write {env_path}: {exc}",
                )
            )
            checks.append(SetupCheck(label, "fail", f"{env_path} is not writable."))

    if payload.enable_https and not payload.use_staging_acme:
        try:
            socket.getaddrinfo(domain, 443)
            checks.append(SetupCheck("dns_lookup", "pass", "Domain resolves via DNS."))
        except OSError:
            warnings.append(
                SetupIssue(
                    code="dns_unresolved",
                    message=(
                        "Domain does not currently resolve from this host. "
                        "Certificate issuance may fail until DNS propagates."
                    ),
                    field="domain",
                )
            )
            checks.append(SetupCheck("dns_lookup", "warn", "Domain does not resolve yet."))

    return SetupPreflightResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        checks=checks,
    )


async def initialize_setup(db: AsyncSession, payload: SetupPayload) -> dict[str, object]:
    result = run_preflight(payload)
    if not result.valid:
        return {
            "status": "error",
            "preflight": _serialize_preflight(result),
        }

    domain = _normalize_domain(payload.domain)
    https_enabled = payload.enable_https
    acme_ca = (
        "https://acme-staging-v02.api.letsencrypt.org/directory"
        if payload.use_staging_acme
        else "https://acme-v02.api.letsencrypt.org/directory"
    )

    root_env = _repo_root() / ".env"
    backend_env = _repo_root() / "backend" / ".env"

    _upsert_env_value(root_env, "DOMAIN", domain)
    _upsert_env_value(root_env, "ACME_EMAIL", payload.acme_email.strip())
    _upsert_env_value(root_env, "CADDY_AUTO_HTTPS", "on" if https_enabled else "off")
    _upsert_env_value(root_env, "ACME_CA", acme_ca)

    backend_domain = f"{'https' if https_enabled else 'http'}://{domain}"
    _upsert_env_value(backend_env, "DOMAIN", backend_domain)
    _upsert_env_value(backend_env, "CORS_ORIGINS", ",".join(payload.cors_origins))

    values = {
        SETUP_INITIALIZED_KEY: "true",
        "setup_domain": domain,
        "setup_acme_email": payload.acme_email.strip(),
        "setup_https_enabled": "true" if https_enabled else "false",
        "setup_acme_staging": "true" if payload.use_staging_acme else "false",
        "setup_cors_origins": ",".join(payload.cors_origins),
        "setup_completed_at": datetime.now(timezone.utc).isoformat(),
    }

    for key, value in values.items():
        row = await db.execute(select(Setting).where(Setting.key == key))
        setting = row.scalar_one_or_none()
        if setting is None:
            db.add(Setting(key=key, value=value))
        else:
            setting.value = value

    return {
        "status": "ok",
        "message": "Initial setup completed.",
        "preflight": _serialize_preflight(result),
    }


def _serialize_preflight(result: SetupPreflightResult) -> dict[str, object]:
    return {
        "valid": result.valid,
        "errors": [issue.__dict__ for issue in result.errors],
        "warnings": [issue.__dict__ for issue in result.warnings],
        "checks": [check.__dict__ for check in result.checks],
    }
