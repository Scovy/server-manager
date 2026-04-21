"""Setup service for first-install onboarding and configuration writes."""

from __future__ import annotations

import ipaddress
import logging
import os
import re
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import docker
from docker.errors import DockerException, NotFound
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.setting import Setting

SETUP_INITIALIZED_KEY = "setup_initialized"
logger = logging.getLogger(__name__)

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
    explicit_root = os.getenv("SETUP_CONFIG_ROOT", "").strip()
    if explicit_root:
        return Path(explicit_root).expanduser().resolve()

    candidates = [
        Path(__file__).resolve().parents[3],
        Path.cwd(),
        Path("/workspace"),
        Path("/vagrant"),
    ]
    markers = ("docker-compose.prod.yml", "docker-compose.yml", ".env.example", "caddy")

    for candidate in candidates:
        if candidate.exists() and all((candidate / marker).exists() for marker in markers):
            return candidate

    return candidates[0]


def _resolve_env_paths() -> tuple[Path, Path]:
    """Resolve root and backend env paths in both dev and container layouts."""
    root = _repo_root()
    root_env = root / ".env"

    backend_dir = root / "backend"
    if backend_dir.is_dir():
        backend_env = backend_dir / ".env"
    else:
        # In container images, backend code typically lives directly under /app.
        backend_env = root_env

    return root_env, backend_env


def _normalize_domain(value: str) -> str:
    domain = value.strip().lower()
    domain = domain.replace("http://", "").replace("https://", "")
    domain = domain.split("/", 1)[0]
    return domain


def _is_local_or_ip_target(domain: str) -> bool:
    if not domain:
        return False

    if domain in {"localhost"}:
        return True

    try:
        ipaddress.ip_address(domain)
        return True
    except ValueError:
        return domain.endswith((".localhost", ".local", ".internal", ".home.arpa"))


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


def _render_caddy_globals(acme_email: str, acme_ca: str) -> str:
    return "\n".join(
        [
            "{",
            f"    email {acme_email}",
            f"    acme_ca {acme_ca}",
            "}",
            "",
        ]
    )


def _render_caddy_site(domain: str, https_enabled: bool) -> str:
    site_address = domain if https_enabled else f"http://{domain}"
    tls_lines: list[str] = []
    if https_enabled and _is_local_or_ip_target(domain):
        tls_lines = [
            "",
            "    tls internal",
        ]
    return "\n".join(
        [
            f"{site_address} {{",
            "    handle /api/* {",
            "        reverse_proxy backend:8000",
            "    }",
            "",
            "    handle /ws/* {",
            "        reverse_proxy backend:8000",
            "    }",
            "",
            "    handle {",
            "        reverse_proxy frontend:3000",
            "    }",
            *tls_lines,
            "",
            "    encode gzip zstd",
            "}",
            "",
        ]
    )


def _write_caddy_runtime_config(
    root: Path,
    *,
    domain: str,
    acme_email: str,
    acme_ca: str,
    https_enabled: bool,
) -> None:
    caddy_dir = root / "caddy"
    globals_path = caddy_dir / "generated_globals.caddy"
    site_path = caddy_dir / "generated_site.caddy"

    caddy_dir.mkdir(parents=True, exist_ok=True)
    globals_path.write_text(_render_caddy_globals(acme_email.strip(), acme_ca), encoding="utf-8")
    site_path.write_text(
        _render_caddy_site(domain=domain, https_enabled=https_enabled),
        encoding="utf-8",
    )


def _restart_caddy_container() -> tuple[str, str]:
    container_name = os.getenv("CADDY_CONTAINER_NAME", "homelab_caddy").strip() or "homelab_caddy"
    client = docker.from_env()
    try:
        container = client.containers.get(container_name)
        container.restart(timeout=20)
        return ("applied", f"Reloaded container {container_name} with updated domain/SSL config.")
    except NotFound:
        return ("skipped", f"Caddy container '{container_name}' was not found. Config saved only.")
    except DockerException as exc:
        return ("warning", f"Config saved, but Caddy reload failed: {exc}")
    except Exception as exc:  # pragma: no cover - defensive guard for runtime env mismatches
        return ("warning", f"Config saved, but Caddy reload could not be completed: {exc}")
    finally:
        client.close()


def apply_runtime_handover() -> None:
    """Apply runtime handover by reloading Caddy after setup response is returned."""
    status, message = _restart_caddy_container()
    if status == "applied":
        logger.info(message)
    elif status == "skipped":
        logger.warning(message)
    else:
        logger.error(message)


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
    local_https_target = _is_local_or_ip_target(domain)

    if payload.enable_https:
        if not domain:
            errors.append(
                SetupIssue(
                    code="invalid_domain",
                    message="Domain cannot be empty when HTTPS is enabled.",
                    field="domain",
                )
            )
        elif local_https_target:
            checks.append(
                SetupCheck(
                    "domain_format",
                    "pass",
                    "Local/IP HTTPS target detected. Caddy will use local certificates.",
                )
            )
            warnings.append(
                SetupIssue(
                    code="local_cert_untrusted",
                    message=(
                        "Local HTTPS certificates are not publicly trusted. "
                        "Trust Caddy's local CA on client devices to remove browser warnings."
                    ),
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

    root_env, backend_env = _resolve_env_paths()
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

    if payload.enable_https and local_https_target:
        checks.append(
            SetupCheck(
                "dns_lookup",
                "pass",
                "Skipped public DNS check for local/IP HTTPS target.",
            )
        )
    elif payload.enable_https and not payload.use_staging_acme:
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

    root_env, backend_env = _resolve_env_paths()

    _upsert_env_value(root_env, "DOMAIN", domain)
    _upsert_env_value(root_env, "ACME_EMAIL", payload.acme_email.strip())
    _upsert_env_value(root_env, "ACME_CA", acme_ca)
    site_address = domain if https_enabled else f"http://{domain}"
    _upsert_env_value(root_env, "SITE_ADDRESS", site_address)
    _write_caddy_runtime_config(
        _repo_root(),
        domain=domain,
        acme_email=payload.acme_email.strip(),
        acme_ca=acme_ca,
        https_enabled=https_enabled,
    )

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
        "message": "Initial setup completed. Runtime handover scheduled.",
        "handover": {
            "status": "scheduled",
            "message": "Caddy reload scheduled in background.",
            "target_url": backend_domain,
        },
        "preflight": _serialize_preflight(result),
    }


def _serialize_preflight(result: SetupPreflightResult) -> dict[str, object]:
    return {
        "valid": result.valid,
        "errors": [issue.__dict__ for issue in result.errors],
        "warnings": [issue.__dict__ for issue in result.warnings],
        "checks": [check.__dict__ for check in result.checks],
    }
