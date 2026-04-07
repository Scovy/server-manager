"""Marketplace service for application template catalog operations."""

from __future__ import annotations

import re
import socket
import subprocess
from pathlib import Path
from typing import TypedDict

import docker
from docker.errors import APIError, NotFound

from app.config import settings


class MarketplaceTemplate(TypedDict):
    """Template metadata used by marketplace list/detail endpoints."""

    id: str
    name: str
    description: str
    category: str
    image: str
    version: str
    homepage: str
    default_port: int
    container_port: int
    default_env: dict[str, str]


class MarketplaceDeployRequest(TypedDict):
    """Payload used to deploy a template instance."""

    template_id: str
    app_name: str
    host_port: int
    env: dict[str, str]


class MarketplaceDeployResult(TypedDict):
    """Deploy operation result returned to API callers."""

    status: str
    template_id: str
    app_name: str
    host_port: int
    app_dir: str
    compose_path: str
    output: str


APP_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{2,40}$")


_TEMPLATES: list[MarketplaceTemplate] = [
    {
        "id": "nextcloud",
        "name": "Nextcloud",
        "description": "Private cloud with files, calendar, and collaboration.",
        "category": "productivity",
        "image": "nextcloud:latest",
        "version": "latest",
        "homepage": "https://nextcloud.com",
        "default_port": 8080,
        "container_port": 80,
        "default_env": {},
    },
    {
        "id": "gitea",
        "name": "Gitea",
        "description": "Lightweight self-hosted Git service.",
        "category": "dev",
        "image": "gitea/gitea:latest",
        "version": "latest",
        "homepage": "https://about.gitea.com",
        "default_port": 3000,
        "container_port": 3000,
        "default_env": {
            "USER_UID": "1000",
            "USER_GID": "1000",
        },
    },
    {
        "id": "vaultwarden",
        "name": "Vaultwarden",
        "description": "Bitwarden-compatible password manager server.",
        "category": "security",
        "image": "vaultwarden/server:latest",
        "version": "latest",
        "homepage": "https://github.com/dani-garcia/vaultwarden",
        "default_port": 8081,
        "container_port": 80,
        "default_env": {
            "WEBSOCKET_ENABLED": "true",
            "SIGNUPS_ALLOWED": "false",
        },
    },
    {
        "id": "uptime-kuma",
        "name": "Uptime Kuma",
        "description": "Self-hosted monitoring and status page dashboard.",
        "category": "monitoring",
        "image": "louislam/uptime-kuma:1",
        "version": "1",
        "homepage": "https://uptime.kuma.pet",
        "default_port": 3001,
        "container_port": 3001,
        "default_env": {},
    },
    {
        "id": "jellyfin",
        "name": "Jellyfin",
        "description": "Media server for movies, shows, and music.",
        "category": "media",
        "image": "jellyfin/jellyfin:latest",
        "version": "latest",
        "homepage": "https://jellyfin.org",
        "default_port": 8096,
        "container_port": 8096,
        "default_env": {},
    },
]


def list_templates(
    category: str | None = None,
    search: str | None = None,
) -> list[MarketplaceTemplate]:
    """List templates with optional category and text filtering."""
    result = _TEMPLATES

    if category:
        lowered_category = category.strip().lower()
        result = [
            template
            for template in result
            if template["category"].lower() == lowered_category
        ]

    if search:
        needle = search.strip().lower()
        if needle:
            result = [
                template
                for template in result
                if needle in template["name"].lower()
                or needle in template["description"].lower()
                or needle in template["id"].lower()
            ]

    return sorted(result, key=lambda template: template["name"].lower())


def get_template(template_id: str) -> MarketplaceTemplate:
    """Return one template by ID.

    Raises:
        ValueError: If template ID does not exist.
    """
    lowered_id = template_id.strip().lower()
    for template in _TEMPLATES:
        if template["id"].lower() == lowered_id:
            return template
    raise ValueError("Template not found")


def is_port_available(port: int) -> bool:
    """Check whether a host port is available for binding."""
    if port < 1 or port > 65535:
        return False

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("0.0.0.0", port))
        except OSError:
            return False
    return True


def _render_compose(
    template: MarketplaceTemplate,
    app_name: str,
    host_port: int,
    env: dict[str, str],
) -> str:
    lines = [
        "services:",
        f"  {app_name}:",
        f"    image: {template['image']}",
        f"    container_name: {app_name}",
        "    restart: unless-stopped",
        "    ports:",
        f"      - \"{host_port}:{template['container_port']}\"",
    ]
    if env:
        lines.append("    environment:")
        for key, value in sorted(env.items()):
            lines.append(f"      {key}: \"{value}\"")
    return "\n".join(lines) + "\n"


def _validate_deploy_request(request: MarketplaceDeployRequest) -> None:
    app_name = request["app_name"].strip()
    if not APP_NAME_PATTERN.fullmatch(app_name):
        raise ValueError(
            "App name must be 3-41 chars and contain only letters, numbers, _ or -"
        )

    if request["host_port"] < 1 or request["host_port"] > 65535:
        raise ValueError("Host port must be between 1 and 65535")

    for key in request["env"]:
        if not key or "=" in key or " " in key:
            raise ValueError(f"Invalid env key: {key}")


def deploy_template(request: MarketplaceDeployRequest) -> MarketplaceDeployResult:
    """Deploy a marketplace template using docker compose.

    Creates compose and env files in app directory and runs docker compose up.
    """
    _validate_deploy_request(request)

    template = get_template(request["template_id"])
    app_name = request["app_name"].strip()
    host_port = request["host_port"]
    env = {**template["default_env"], **request["env"]}

    apps_dir = Path(settings.MARKETPLACE_APPS_DIR).expanduser().resolve()
    app_dir = apps_dir / app_name
    compose_path = app_dir / "docker-compose.yml"
    env_path = app_dir / ".env"

    if app_dir.exists():
        raise ValueError("Application with this name already exists")

    if not is_port_available(host_port):
        raise ValueError(f"Host port {host_port} is already in use")

    app_dir.mkdir(parents=True, exist_ok=False)
    compose_content = _render_compose(template, app_name, host_port, env)
    compose_path.write_text(compose_content, encoding="utf-8")
    env_path.write_text(
        "\n".join(f"{k}={v}" for k, v in sorted(env.items())) + ("\n" if env else ""),
        encoding="utf-8",
    )

    output = ""
    try:
        proc = subprocess.run(
            ["docker", "compose", "-f", str(compose_path), "up", "-d"],
            cwd=str(app_dir),
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        if proc.returncode != 0:
            stderr = proc.stderr.strip() or proc.stdout.strip() or "Unknown docker compose error"
            raise ValueError(f"Deploy failed: {stderr}")
        output = proc.stdout.strip() or "Deployment completed successfully"
    except OSError as exc:
        # In containerized backend deployments the docker CLI binary may be absent.
        # Fall back to Docker SDK over /var/run/docker.sock.
        if exc.errno != 2:
            raise ValueError(f"Failed to run docker compose: {exc}") from exc
        output = _deploy_with_docker_sdk(template, app_name, host_port, env)
    except subprocess.TimeoutExpired as exc:
        raise ValueError("docker compose deploy timed out") from exc

    return {
        "status": "ok",
        "template_id": template["id"],
        "app_name": app_name,
        "host_port": host_port,
        "app_dir": str(app_dir),
        "compose_path": str(compose_path),
        "output": output,
    }


def _deploy_with_docker_sdk(
    template: MarketplaceTemplate,
    app_name: str,
    host_port: int,
    env: dict[str, str],
) -> str:
    """Deploy container directly with Docker SDK when docker CLI is unavailable."""
    client = docker.from_env()
    try:
        try:
            client.containers.get(app_name)
            raise ValueError("Application with this name already exists")
        except NotFound:
            pass

        port_key = f"{template['container_port']}/tcp"
        container = client.containers.run(
            template["image"],
            name=app_name,
            detach=True,
            ports={port_key: host_port},
            environment=env,
            restart_policy={"Name": "unless-stopped"},
            labels={
                "com.homelab.managed": "true",
                "com.homelab.template": template["id"],
                "com.homelab.compose-project": app_name,
            },
        )
        return f"Container started: {container.short_id}"
    except APIError as exc:
        raise ValueError(f"Deploy failed: {exc.explanation}") from exc
    finally:
        client.close()
