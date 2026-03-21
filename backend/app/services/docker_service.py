"""Docker service wrapper for container lifecycle and metadata operations.

This module isolates Docker SDK calls behind a typed service that can be
reused by routers and unit-tested via mocking.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import docker
from docker.errors import APIError, NotFound


class DockerService:
    """Service wrapper around Docker SDK operations used by container APIs."""

    PROTECTED_NETWORKS = {"bridge", "host", "none"}

    def __init__(self) -> None:
        self.client = docker.from_env()

    def close(self) -> None:
        """Close underlying Docker client resources."""
        self.client.close()

    def list_containers(self, all_containers: bool = True) -> list[dict[str, Any]]:
        """Return summarized container list for UI display."""
        containers = self.client.containers.list(all=all_containers)
        return [self._serialize_container(container) for container in containers]

    def get_container(self, container_id: str) -> dict[str, Any]:
        """Return single container details.

        Raises:
            ValueError: If container does not exist.
        """
        try:
            container = self.client.containers.get(container_id)
        except NotFound as exc:
            raise ValueError("Container not found") from exc
        return self._serialize_container(container, include_details=True)

    def start(self, container_id: str) -> None:
        self._with_container(container_id, lambda c: c.start())

    def stop(self, container_id: str) -> None:
        self._with_container(container_id, lambda c: c.stop())

    def restart(self, container_id: str) -> None:
        self._with_container(container_id, lambda c: c.restart())

    def kill(self, container_id: str) -> None:
        self._with_container(container_id, lambda c: c.kill())

    def remove(self, container_id: str, remove_volumes: bool = False) -> None:
        self._with_container(container_id, lambda c: c.remove(v=remove_volumes, force=False))

    def get_stats(self, container_id: str) -> dict[str, Any]:
        """Return lightweight stats for a single container."""
        container = self._get_container_or_raise(container_id)
        stats = container.stats(stream=False)
        return {
            "id": container.short_id,
            "name": container.name,
            "status": container.status,
            "cpu_percent": self._calc_container_cpu(stats),
            "memory_usage_mb": round(
                stats.get("memory_stats", {}).get("usage", 0) / (1024 * 1024),
                2,
            ),
            "memory_limit_mb": round(
                stats.get("memory_stats", {}).get("limit", 0) / (1024 * 1024),
                2,
            ),
        }

    def tail_logs(self, container_id: str, tail: int = 200) -> str:
        """Return UTF-8 decoded tail logs for a container."""
        container = self._get_container_or_raise(container_id)
        raw = container.logs(tail=tail, timestamps=True)
        if isinstance(raw, bytes):
            return raw.decode("utf-8", errors="replace")
        return str(raw)

    def get_compose(self, container_id: str) -> tuple[str, str]:
        """Read docker-compose file for a compose-managed container.

        Returns:
            Tuple[path, content]

        Raises:
            ValueError: if compose file cannot be resolved or read.
        """
        container = self._get_container_or_raise(container_id)
        path = self._resolve_compose_file(container)
        try:
            return str(path), path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ValueError(f"Failed to read compose file: {exc}") from exc

    def update_compose(self, container_id: str, content: str) -> str:
        """Write docker-compose file for a compose-managed container.

        Returns:
            Updated file path.
        """
        container = self._get_container_or_raise(container_id)
        path = self._resolve_compose_file(container)
        try:
            path.write_text(content, encoding="utf-8")
            return str(path)
        except OSError as exc:
            raise ValueError(f"Failed to write compose file: {exc}") from exc

    def get_env(self, container_id: str) -> dict[str, str]:
        """Return env vars inferred from running container configuration."""
        container = self._get_container_or_raise(container_id)
        raw_env = container.attrs.get("Config", {}).get("Env", [])
        env: dict[str, str] = {}
        for item in raw_env:
            if "=" in item:
                key, value = item.split("=", 1)
                env[key] = value
        return env

    def update_env(self, container_id: str, env: dict[str, str]) -> dict[str, str]:
        """Persist env vars into Compose .env file if resolvable.

        If no compose env file label is available, raises ValueError.
        """
        container = self._get_container_or_raise(container_id)
        path = self._resolve_env_file(container)
        lines = [f"{key}={value}" for key, value in sorted(env.items())]
        text = "\n".join(lines) + "\n"
        try:
            path.write_text(text, encoding="utf-8")
            return env
        except OSError as exc:
            raise ValueError(f"Failed to write env file: {exc}") from exc

    def apply_compose(self, container_id: str) -> dict[str, str]:
        """Apply compose/env changes by recreating the compose project.

        Runs:
            docker compose -f <compose_file> up -d --force-recreate
        """
        container = self._get_container_or_raise(container_id)
        compose_path = self._resolve_compose_file(container)
        working_dir = compose_path.parent

        try:
            proc = subprocess.run(
                [
                    "docker",
                    "compose",
                    "-f",
                    str(compose_path),
                    "up",
                    "-d",
                    "--force-recreate",
                ],
                cwd=str(working_dir),
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
        except OSError as exc:
            raise ValueError(f"Failed to run docker compose: {exc}") from exc
        except subprocess.TimeoutExpired as exc:
            raise ValueError("docker compose apply timed out") from exc

        if proc.returncode != 0:
            stderr = proc.stderr.strip() or proc.stdout.strip() or "Unknown docker compose error"
            raise ValueError(f"Apply failed: {stderr}")

        return {
            "status": "ok",
            "output": proc.stdout.strip() or "Compose project recreated successfully",
        }

    def open_exec_socket(self, container_id: str, command: str = "/bin/sh") -> Any:
        """Create an interactive exec session socket (tty, stdin enabled)."""
        container = self._get_container_or_raise(container_id)
        if container.status != "running":
            raise ValueError("Container must be running to open exec terminal")

        low_level = self.client.api
        candidates = [command, "/bin/bash", "/bin/sh", "sh", "ash"]
        unique_candidates = [c for i, c in enumerate(candidates) if c and c not in candidates[:i]]

        last_error: APIError | None = None
        for cmd_candidate in unique_candidates:
            try:
                exec_config = low_level.exec_create(
                    container=container.id,
                    cmd=cmd_candidate,
                    stdin=True,
                    tty=True,
                )
                return low_level.exec_start(
                    exec_config["Id"],
                    tty=True,
                    stream=False,
                    socket=True,
                )
            except APIError as exc:
                last_error = exc

        if last_error:
            raise ValueError(
                f"Failed to start exec shell: {last_error.explanation}"
            ) from last_error
        raise ValueError("Failed to start exec shell")

    def list_volumes(self) -> list[dict[str, Any]]:
        """List docker volumes with useful metadata for the UI."""
        volumes = self.client.volumes.list()
        return [
            {
                "name": volume.name,
                "driver": volume.attrs.get("Driver", ""),
                "mountpoint": volume.attrs.get("Mountpoint", ""),
                "scope": volume.attrs.get("Scope", ""),
                "labels": volume.attrs.get("Labels") or {},
                "ref_count": int((volume.attrs.get("UsageData") or {}).get("RefCount", 0)),
                "in_use": int((volume.attrs.get("UsageData") or {}).get("RefCount", 0)) > 0,
            }
            for volume in volumes
        ]

    def remove_volume(self, volume_name: str) -> None:
        """Remove a docker volume by name."""
        try:
            volume = self.client.volumes.get(volume_name)
            ref_count = int((volume.attrs.get("UsageData") or {}).get("RefCount", 0))
            if ref_count > 0:
                raise ValueError("Volume is in use and cannot be removed")
            volume.remove(force=False)
        except NotFound as exc:
            raise ValueError("Volume not found") from exc
        except APIError as exc:
            raise ValueError(f"Docker API error: {exc.explanation}") from exc

    def list_networks(self) -> list[dict[str, Any]]:
        """List docker networks with useful metadata for the UI."""
        networks = self.client.networks.list()
        payload: list[dict[str, Any]] = []
        for network in networks:
            name = network.name
            attached = len((network.attrs.get("Containers") or {}).keys())
            is_protected = name in self.PROTECTED_NETWORKS
            payload.append(
                {
                    "id": network.id[:12],
                    "name": name,
                    "driver": network.attrs.get("Driver", ""),
                    "scope": network.attrs.get("Scope", ""),
                    "containers": attached,
                    "labels": network.attrs.get("Labels") or {},
                    "protected": is_protected,
                }
            )
        return payload

    def remove_network(self, network_id: str) -> None:
        """Remove a docker network by id or name."""
        try:
            network = self.client.networks.get(network_id)
            if network.name in self.PROTECTED_NETWORKS:
                raise ValueError("Protected docker network cannot be removed")
            attached = len((network.attrs.get("Containers") or {}).keys())
            if attached > 0:
                raise ValueError("Network has attached containers and cannot be removed")
            network.remove()
        except NotFound as exc:
            raise ValueError("Network not found") from exc
        except APIError as exc:
            raise ValueError(f"Docker API error: {exc.explanation}") from exc

    def _get_container_or_raise(self, container_id: str):
        try:
            return self.client.containers.get(container_id)
        except NotFound as exc:
            raise ValueError("Container not found") from exc
        except APIError as exc:
            raise ValueError(f"Docker API error: {exc.explanation}") from exc

    def _with_container(self, container_id: str, callback: Any) -> None:
        container = self._get_container_or_raise(container_id)
        try:
            callback(container)
        except APIError as exc:
            raise ValueError(f"Docker API error: {exc.explanation}") from exc

    def _serialize_container(self, container: Any, include_details: bool = False) -> dict[str, Any]:
        labels = container.attrs.get("Config", {}).get("Labels", {}) or {}
        payload: dict[str, Any] = {
            "id": container.short_id,
            "name": container.name,
            "status": container.status,
            "image": container.image.tags[0] if container.image.tags else container.image.short_id,
            "created": container.attrs.get("Created"),
            "labels": labels,
            "ports": container.attrs.get("NetworkSettings", {}).get("Ports", {}),
        }
        if include_details:
            payload["raw"] = {
                "command": container.attrs.get("Config", {}).get("Cmd"),
                "entrypoint": container.attrs.get("Config", {}).get("Entrypoint"),
                "mounts": container.attrs.get("Mounts", []),
                "env_count": len(container.attrs.get("Config", {}).get("Env", [])),
            }
        return payload

    def _resolve_compose_file(self, container: Any) -> Path:
        labels = container.attrs.get("Config", {}).get("Labels", {}) or {}
        config_files = labels.get("com.docker.compose.project.config_files")
        working_dir = labels.get("com.docker.compose.project.working_dir")

        if config_files:
            first = str(config_files).split(",")[0].strip()
            candidate = Path(first)
            if candidate.exists():
                return candidate
            if working_dir:
                candidate = Path(working_dir) / first
                if candidate.exists():
                    return candidate

        if working_dir:
            default_candidates = [
                "docker-compose.yml",
                "docker-compose.yaml",
                "docker-compose.prod.yml",
                "compose.yml",
                "compose.yaml",
            ]
            for name in default_candidates:
                candidate = Path(working_dir) / name
                if candidate.exists():
                    return candidate

        raise ValueError("Compose file not found for container. Ensure it is compose-managed.")

    def _resolve_env_file(self, container: Any) -> Path:
        labels = container.attrs.get("Config", {}).get("Labels", {}) or {}
        working_dir = labels.get("com.docker.compose.project.working_dir")
        if not working_dir:
            raise ValueError("Cannot resolve .env file path for this container")

        env_path = Path(working_dir) / ".env"
        if env_path.exists():
            return env_path
        raise ValueError(".env file not found for compose project")

    @staticmethod
    def _calc_container_cpu(stats: dict[str, Any]) -> float:
        """Calculate CPU percentage using Docker stats delta values."""
        try:
            cpu_delta = float(
                stats["cpu_stats"]["cpu_usage"]["total_usage"]
                - stats["precpu_stats"]["cpu_usage"]["total_usage"]
            )
            system_delta = float(
                stats["cpu_stats"]["system_cpu_usage"]
                - stats["precpu_stats"]["system_cpu_usage"]
            )
            cpus_raw = stats["cpu_stats"].get("online_cpus") or len(
                stats["cpu_stats"]["cpu_usage"].get("percpu_usage", [1])
            )
            cpus = float(cpus_raw)
            if system_delta > 0 and cpu_delta >= 0:
                return float(round((cpu_delta / system_delta) * cpus * 100.0, 2))
        except (KeyError, ZeroDivisionError, TypeError):
            return 0.0
        return 0.0


def parse_env_payload(payload: str) -> dict[str, str]:
    """Parse newline-delimited KEY=VALUE content into a dictionary."""
    data: dict[str, str] = {}
    for line in payload.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        data[key.strip()] = value.strip()
    return data


def env_to_text(data: dict[str, str]) -> str:
    """Serialize env dictionary into deterministic KEY=VALUE text."""
    return "\n".join(f"{k}={v}" for k, v in sorted(data.items())) + "\n"


def safe_json(data: Any) -> str:
    """Serialize payload into formatted JSON for editor responses."""
    return json.dumps(data, indent=2, sort_keys=True)
