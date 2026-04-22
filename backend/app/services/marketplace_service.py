"""Marketplace service for application template catalog operations."""

from __future__ import annotations

import re
import shutil
import socket
import subprocess
import tarfile
from io import BytesIO
from pathlib import Path
from typing import TypedDict

import docker
from docker.errors import APIError, DockerException, NotFound

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
    app_url: str
    output: str


class MarketplacePreflightRequest(TypedDict):
    """Validation payload used before deploy submit."""

    template_id: str
    app_name: str
    host_port: int


class MarketplacePreflightResult(TypedDict):
    """Validation result returned to API callers."""

    valid: bool
    errors: list[str]


APP_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{2,40}$")
IPV4_PATTERN = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")


_TEMPLATES: list[MarketplaceTemplate] = [
    {
        "id": "adguard-home",
        "name": "Adguard Home",
        "description": "Network-wide ad and tracker blocking DNS server.",
        "category": "security",
        "image": "adguard/adguardhome:latest",
        "version": "latest",
        "homepage": "https://adguard.com/adguard-home/overview.html",
        "default_port": 3002,
        "container_port": 3000,
        "default_env": {
            "TZ": "UTC",
        },
    },
    {
        "id": "crafty",
        "name": "Crafty",
        "description": "Game server control panel for home labs.",
        "category": "dev",
        "image": "registry.gitlab.com/crafty-controller/crafty-4:latest",
        "version": "latest",
        "homepage": "https://craftycontrol.com",
        "default_port": 8443,
        "container_port": 8443,
        "default_env": {
            "TZ": "UTC",
        },
    },
    {
        "id": "dozzle",
        "name": "Dozzle",
        "description": "Real-time Docker log viewer with a lightweight web UI.",
        "category": "monitoring",
        "image": "amir20/dozzle:latest",
        "version": "latest",
        "homepage": "https://dozzle.dev",
        "default_port": 8082,
        "container_port": 8080,
        "default_env": {
            "DOZZLE_LEVEL": "info",
        },
    },
    {
        "id": "filebrowser",
        "name": "Filebrowser",
        "description": "Web-based file management for local and mounted folders.",
        "category": "productivity",
        "image": "filebrowser/filebrowser:latest",
        "version": "latest",
        "homepage": "https://filebrowser.org",
        "default_port": 8084,
        "container_port": 80,
        "default_env": {},
    },
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
        "id": "home-assistant",
        "name": "Home Assistant",
        "description": "Open-source home automation platform and dashboard.",
        "category": "productivity",
        "image": "ghcr.io/home-assistant/home-assistant:stable",
        "version": "stable",
        "homepage": "https://www.home-assistant.io",
        "default_port": 8123,
        "container_port": 8123,
        "default_env": {
            "TZ": "UTC",
        },
    },
    {
        "id": "immich",
        "name": "Immich",
        "description": (
            "Self-hosted photo platform. "
            "Production deployments should include external Redis/PostgreSQL."
        ),
        "category": "media",
        "image": "ghcr.io/immich-app/immich-server:release",
        "version": "release",
        "homepage": "https://immich.app",
        "default_port": 2283,
        "container_port": 2283,
        "default_env": {
            "TZ": "UTC",
        },
    },
    {
        "id": "jenkins",
        "name": "Jenkins",
        "description": "Automation server for CI/CD pipelines and jobs.",
        "category": "dev",
        "image": "jenkins/jenkins:lts",
        "version": "lts",
        "homepage": "https://www.jenkins.io",
        "default_port": 8085,
        "container_port": 8080,
        "default_env": {},
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
        "id": "n8n",
        "name": "n8n",
        "description": "Workflow automation platform for integrations and jobs.",
        "category": "productivity",
        "image": "n8nio/n8n:latest",
        "version": "latest",
        "homepage": "https://n8n.io",
        "default_port": 5678,
        "container_port": 5678,
        "default_env": {
            "TZ": "UTC",
        },
    },
    {
        "id": "openvpn",
        "name": "OpenVPN",
        "description": "OpenVPN Access Server web admin endpoint.",
        "category": "security",
        "image": "lscr.io/linuxserver/openvpn-as:latest",
        "version": "latest",
        "homepage": "https://openvpn.net/access-server/",
        "default_port": 943,
        "container_port": 943,
        "default_env": {
            "PUID": "1000",
            "PGID": "1000",
            "TZ": "UTC",
        },
    },
    {
        "id": "pihole",
        "name": "Pi-hole",
        "description": "DNS sinkhole with a web admin interface.",
        "category": "security",
        "image": "pihole/pihole:latest",
        "version": "latest",
        "homepage": "https://pi-hole.net",
        "default_port": 8086,
        "container_port": 80,
        "default_env": {
            "TZ": "UTC",
            "WEBPASSWORD": "change-me",
        },
    },
    {
        "id": "plex",
        "name": "Plex",
        "description": "Media server for streaming your personal content library.",
        "category": "media",
        "image": "lscr.io/linuxserver/plex:latest",
        "version": "latest",
        "homepage": "https://www.plex.tv",
        "default_port": 32400,
        "container_port": 32400,
        "default_env": {
            "PUID": "1000",
            "PGID": "1000",
            "TZ": "UTC",
        },
    },
    {
        "id": "prowlarr",
        "name": "Prowlarr",
        "description": "Indexer manager for Sonarr/Radarr ecosystems.",
        "category": "media",
        "image": "lscr.io/linuxserver/prowlarr:latest",
        "version": "latest",
        "homepage": "https://wiki.servarr.com/prowlarr",
        "default_port": 9696,
        "container_port": 9696,
        "default_env": {
            "PUID": "1000",
            "PGID": "1000",
            "TZ": "UTC",
        },
    },
    {
        "id": "qbittorrent",
        "name": "qBitTorrent",
        "description": "BitTorrent client with a web user interface.",
        "category": "media",
        "image": "lscr.io/linuxserver/qbittorrent:latest",
        "version": "latest",
        "homepage": "https://www.qbittorrent.org",
        "default_port": 8090,
        "container_port": 8080,
        "default_env": {
            "PUID": "1000",
            "PGID": "1000",
            "TZ": "UTC",
            "WEBUI_PORT": "8080",
        },
    },
    {
        "id": "radarr",
        "name": "Radarr",
        "description": "Movie collection manager and downloader automation.",
        "category": "media",
        "image": "lscr.io/linuxserver/radarr:latest",
        "version": "latest",
        "homepage": "https://radarr.video",
        "default_port": 7878,
        "container_port": 7878,
        "default_env": {
            "PUID": "1000",
            "PGID": "1000",
            "TZ": "UTC",
        },
    },
    {
        "id": "sonarr",
        "name": "Sonarr",
        "description": "TV show collection manager and downloader automation.",
        "category": "media",
        "image": "lscr.io/linuxserver/sonarr:latest",
        "version": "latest",
        "homepage": "https://sonarr.tv",
        "default_port": 8989,
        "container_port": 8989,
        "default_env": {
            "PUID": "1000",
            "PGID": "1000",
            "TZ": "UTC",
        },
    },
    {
        "id": "stremio",
        "name": "Stremio",
        "description": "Streaming add-on server for Stremio clients.",
        "category": "media",
        "image": "stremio/server:latest",
        "version": "latest",
        "homepage": "https://www.stremio.com",
        "default_port": 11470,
        "container_port": 11470,
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
    {
        "id": "jellyseer",
        "name": "Jellyseer",
        "description": "Request management UI for Jellyfin and Plex users.",
        "category": "media",
        "image": "fallenbagel/jellyseerr:latest",
        "version": "latest",
        "homepage": "https://github.com/Fallenbagel/jellyseerr",
        "default_port": 5055,
        "container_port": 5055,
        "default_env": {
            "LOG_LEVEL": "info",
        },
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


def preflight_deploy(
    request: MarketplacePreflightRequest,
    existing_app_names: set[str],
) -> MarketplacePreflightResult:
    """Validate deploy payload before running deployment actions."""
    errors: list[str] = []

    try:
        get_template(request["template_id"])
    except ValueError:
        errors.append("Template not found")

    app_name = request["app_name"].strip()
    if not APP_NAME_PATTERN.fullmatch(app_name):
        errors.append("App name must be 3-41 chars and contain only letters, numbers, _ or -")

    if app_name in existing_app_names:
        errors.append("Application with this name already exists")

    app_dir = Path(settings.MARKETPLACE_APPS_DIR).expanduser().resolve() / app_name
    if app_name and app_dir.exists():
        errors.append("App directory already exists on disk")

    host_port = request["host_port"]
    if host_port < 1 or host_port > 65535:
        errors.append("Host port must be between 1 and 65535")
    elif not is_port_available(host_port):
        errors.append(f"Host port {host_port} is already in use")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
    }


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
        "app_url": f"http://127.0.0.1:{host_port}",
        "output": output,
    }


def normalize_base_domain(value: str | None) -> str | None:
    """Normalize configured domain by removing protocol and path segments."""
    if not value:
        return None
    domain = value.strip().lower()
    domain = domain.replace("http://", "").replace("https://", "")
    domain = domain.split("/", 1)[0]
    if not domain or domain in {"localhost", "127.0.0.1"}:
        return None
    if IPV4_PATTERN.fullmatch(domain):
        return None
    return domain


def build_marketplace_app_url(app_name: str, host_port: int, base_domain: str | None) -> str:
    """Build preferred app URL: subdomain when domain is configured, else host port URL."""
    normalized = normalize_base_domain(base_domain)
    if normalized:
        return f"https://{app_name}.{normalized}"
    return f"http://127.0.0.1:{host_port}"


def sync_caddy_marketplace_routes(apps: list[tuple[str, int]], base_domain: str | None) -> str:
    """Sync marketplace app routes into Caddy include file and reload Caddy.

    Returns a status message and never raises, to avoid blocking deploy/remove flows.
    """
    normalized = normalize_base_domain(base_domain)
    if not normalized:
        return "Skipped Caddy route sync (no base domain configured)"

    lines = [
        "# Auto-generated marketplace routes",
        "# Do not edit manually; managed by backend.",
    ]
    for app_name, host_port in sorted(apps, key=lambda item: item[0]):
        lines.extend(
            [
                f"{app_name}.{normalized} {{",
                f"    reverse_proxy host.docker.internal:{host_port}",
                "    encode gzip zstd",
                "}",
                "",
            ]
        )

    payload = "\n".join(lines).rstrip() + "\n"

    try:
        client = docker.from_env()
    except DockerException as exc:
        return f"Skipped Caddy route sync: {exc}"

    try:
        container_name = settings.CADDY_CONTAINER_NAME
        target_path = settings.CADDY_MARKETPLACE_CONFIG_PATH

        caddy = client.containers.get(container_name)
        _put_text_file_in_container(caddy, target_path, payload)

        cmd = "caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile"
        result = caddy.exec_run(["sh", "-lc", cmd])
        exit_code = result.exit_code
        if exit_code != 0:
            stderr = (result.output or b"").decode("utf-8", errors="ignore").strip()
            return f"Caddy reload failed: {stderr or 'unknown error'}"
        return "Caddy marketplace routes synced"
    except Exception as exc:
        return f"Skipped Caddy route sync: {exc}"
    finally:
        client.close()


def _put_text_file_in_container(
    container: docker.models.containers.Container,
    path: str,
    content: str,
) -> None:
    """Write a UTF-8 text file into a running container using tar archive upload."""
    target = Path(path)
    parent = str(target.parent)
    tar_stream = BytesIO()

    data = content.encode("utf-8")
    info = tarfile.TarInfo(name=target.name)
    info.size = len(data)
    info.mode = 0o644

    with tarfile.open(fileobj=tar_stream, mode="w") as tar:
        tar.addfile(info, BytesIO(data))

    tar_stream.seek(0)
    container.put_archive(parent, tar_stream.read())


def _deploy_with_docker_sdk(
    template: MarketplaceTemplate,
    app_name: str,
    host_port: int,
    env: dict[str, str],
) -> str:
    """Deploy container directly with Docker SDK when docker CLI is unavailable."""
    try:
        client = docker.from_env()
    except DockerException as exc:
        raise ValueError(f"Deploy failed: {exc}") from exc

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


def get_container_status(container_name: str) -> str:
    """Return live container status by name, or 'not-found'/'unknown'."""
    try:
        client = docker.from_env()
    except DockerException:
        return "unknown"

    try:
        container = client.containers.get(container_name)
        return str(container.status)
    except NotFound:
        return "not-found"
    except APIError:
        return "unknown"
    except Exception:
        return "unknown"
    finally:
        client.close()


def remove_deployed_app(container_name: str, app_dir: str, purge_files: bool = False) -> str:
    """Remove deployed marketplace container and optionally app files."""
    try:
        client = docker.from_env()
    except DockerException as exc:
        raise ValueError(f"Failed to connect to docker: {exc}") from exc

    try:
        try:
            container = client.containers.get(container_name)
        except NotFound:
            container = None

        if container is not None:
            try:
                container.stop(timeout=10)
            except APIError:
                pass
            container.remove(v=False, force=True)
    except APIError as exc:
        raise ValueError(f"Failed to remove app container: {exc.explanation}") from exc
    finally:
        client.close()

    if purge_files:
        app_path = Path(app_dir)
        if app_path.exists() and app_path.is_dir():
            shutil.rmtree(app_path)

    return "Application removed"
