"""Docker service wrapper for container lifecycle and metadata operations.

This module isolates Docker SDK calls behind a typed service that can be
reused by routers and unit-tested via mocking.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from collections.abc import Iterator
from functools import cached_property
from pathlib import Path, PurePosixPath
from typing import Any, cast

import docker
import psutil
from docker.errors import APIError, NotFound

from app.config import settings
from app.services.docker_mounts import backend_container
from app.services.marketplace_service import ENV_FILE_REFERENCE


class DockerService:
    """Service wrapper around Docker SDK operations used by container APIs."""

    PROTECTED_NETWORKS = {"bridge", "host", "none"}
    _COMPOSE_FILENAMES = (
        "docker-compose.yml",
        "docker-compose.yaml",
        "docker-compose.prod.yml",
        "compose.yml",
        "compose.yaml",
    )
    _VOLUME_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{1,127}$")
    _ANONYMOUS_VOLUME_PATTERN = re.compile(r"^[a-f0-9]{32,64}$")
    # Byte-exact grammar of Compose files the marketplace renderers generate,
    # current (name + labels) and legacy (bare services block) shape alike.
    _GENERATED_COMPOSE_PATTERN = re.compile(
        r"(?:name: homelab-[0-9a-f]{32}\n)?"
        r"services:\n"
        r"  (?P<service>[a-zA-Z0-9][a-zA-Z0-9_-]{2,40}):\n"
        r"    image: \S+\n"
        r"    container_name: (?P=service)\n"
        r"    restart: unless-stopped\n"
        r"(?:    labels:\n"
        r'      com.homelab.managed: "true"\n'
        r'      com.homelab.compose-project: "(?P=service)"\n'
        r'      com.homelab.template: "[^"\n]+"\n'
        r'      com.homelab.installation: "[0-9a-f]{32}"\n)?'
        r"    ports:\n"
        r'      - "[0-9]{1,5}:[0-9]{1,5}"\n'
        r'(?P<env_block>    environment:\n(?:      [^\s:]+: "[^"\n]*"\n)*)?'
        r'(?:    volumes:\n(?:      - "[^"\n]+:[^"\n]+"\n)+\n'
        r"volumes:\n(?:  [^\n]+\n    name: [^\n]+\n)+)?"
    )
    _IGNORED_DISK_FSTYPES = {
        "autofs",
        "cgroup",
        "cgroup2",
        "configfs",
        "debugfs",
        "devtmpfs",
        "fusectl",
        "mqueue",
        "nsfs",
        "overlay",
        "proc",
        "pstore",
        "securityfs",
        "squashfs",
        "sysfs",
        "tmpfs",
        "tracefs",
    }
    _IGNORED_DISK_PREFIXES = (
        "/proc",
        "/run",
        "/snap",
        "/sys",
        "/var/lib/docker/overlay2",
    )

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

    def stream_logs_follow(self, container_id: str, tail: int = 200) -> Iterator[bytes]:
        """Yield live container logs as raw bytes from Docker follow stream."""
        container = self._get_container_or_raise(container_id)
        raw = container.logs(
            stream=True,
            follow=True,
            tail=tail,
            timestamps=True,
        )
        return cast(Iterator[bytes], raw)

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
        # Before the new values land, turn an untouched generated app into an
        # env_file consumer so this save (and later Apply) actually takes effect.
        self._migrate_generated_compose_env(container, path)
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
        directory = self._project_directory(container)
        files = self._compose_files(container)
        labels = container.attrs["Config"]["Labels"]
        command = ["docker", "compose"]
        if os.getenv("HOMELAB_DATA_MOUNT"):
            # Compose resolves relative bind paths on its client, while Docker
            # creates those mounts on the daemon host. Use the host's path names.
            runner, paths = self._compose_runner([directory, *files])
            command = [*runner, "docker", "compose"]
            directory, *files = paths

        project = labels.get("com.docker.compose.project")
        if project:
            command.extend(["--project-name", str(project)])
        for path in files:
            command.extend(["-f", str(path)])
        command.extend(["--project-directory", str(directory)])
        legacy = labels.get("com.homelab.managed") == "true" and not project
        if legacy:
            # The container predates Compose; _apply_legacy_compose resolves and
            # pins the project identity `docker compose config` reports.
            return self._apply_legacy_compose(container, command)
        return self._run_compose([*command, "up", "-d", "--force-recreate"])

    def _compose_runner(self, paths: list[Path]) -> tuple[list[str], list[Path]]:
        mounts = sorted(
            self._backend.attrs["Mounts"], key=lambda item: len(item["Destination"]), reverse=True
        )
        bindings = {}
        host_paths = []
        for local in paths:
            for mount in mounts:
                destination = Path(mount["Destination"]).resolve()
                if not local.resolve().is_relative_to(destination):
                    continue
                source = mount["Source"]
                host_paths.append(Path(source) / local.resolve().relative_to(destination))
                kind = mount["Type"]
                if kind not in {"bind", "volume"}:
                    raise ValueError("Unsupported mount type for the Compose project")
                resource = mount["Name"] if kind == "volume" else source
                bindings[source] = f"type={kind},src={resource},dst={source},readonly"
                break
            else:
                raise ValueError("Compose project has no verified host mount")
        sock = next((m for m in mounts if m["Destination"] == "/var/run/docker.sock"), None)
        if not sock:
            raise ValueError("The backend Docker socket mount is unavailable")
        runner = [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--workdir",
            str(host_paths[0]),
            "--mount",
            f"type=bind,src={sock['Source']},dst=/var/run/docker.sock",
        ]
        for binding in bindings.values():
            runner.extend(["--mount", binding])
        # Override the HTTP server entrypoint. The selected image already has the CLI.
        runner.extend(["--entrypoint", "/usr/bin/env", self._backend.image.id])
        return runner, host_paths

    def _apply_legacy_compose(self, container: Any, command: list[str]) -> dict[str, str]:
        """Adopt an existing SDK-installed app while keeping a recoverable old container."""
        # Actual project identity as Compose itself resolves it (handles quoted
        # names, trailing comments and env overrides); pinned so `up` cannot drift.
        project, services = self._compose_identity(command)
        command.extend(["--project-name", project])
        name = str(container.name)
        running = container.status == "running"
        previous = f"{name}-before-compose-{container.short_id}"
        container.rename(previous)
        try:
            if running:
                container.stop()
            result = self._run_compose([*command, "up", "-d"])
        except Exception as exc:
            # Remove only a replacement demonstrably created by this Compose run:
            # both the project and the service identity have to match.
            try:
                replacement = self.client.containers.get(name)
            except NotFound:
                replacement = None
            if replacement is not None:
                labels = replacement.attrs["Config"].get("Labels") or {}
                if (
                    labels.get("com.docker.compose.project") == project
                    and labels.get("com.docker.compose.service") in services
                ):
                    replacement.remove(force=True)
            recovered = name
            try:
                container.rename(name)
            except APIError:
                # A foreign container keeps the name; never remove it. Keep the
                # old container available under its backup name instead.
                recovered = previous
            if running:
                container.start()
            raise ValueError(
                f"{exc} The original container is available as '{recovered}'."
            ) from exc
        container.remove()
        return result

    def _compose_identity(self, command: list[str]) -> tuple[str, set[str]]:
        """Validate the project and return the identity this Compose run will use."""
        rendered = self._run_compose([*command, "config", "--format", "json"])
        try:
            config = json.loads(rendered["output"])
            project = str(config["name"])
            services = {str(name) for name in config["services"]}
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("docker compose returned an unreadable project identity") from exc
        if not project or not services:
            raise ValueError("docker compose returned an empty project identity")
        return project, services

    def _migrate_generated_compose_env(self, container: Any, env_path: Path) -> None:
        """At env-save time, switch an untouched generated Compose file to .env.

        Compose lets `environment` win over `env_file`, so the inline block must
        go before saved values can take effect. Origin can only be proven for a
        pristine pair: the file byte-matches the generated grammar and its inline
        keys AND values equal the current .env, exactly as deployment wrote
        them. Anything else may carry hand edits that cannot be told apart from
        .env edits, so such files are never rewritten here: a diverging
        generated pair is refused with the manual merge recipe, and custom or
        already-switched layouts are left alone silently. Apply never touches
        the compose file.
        """
        try:
            compose_path = self._resolve_compose_file(container)
            text = compose_path.read_text(encoding="utf-8")
        except (OSError, ValueError):
            return  # No usable compose file; a plain .env write stays valid.
        match = self._GENERATED_COMPOSE_PATTERN.fullmatch(text)
        env_block = match.group("env_block") if match else None
        if not env_block:
            return
        try:
            existing = parse_env_payload(env_path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise ValueError(f"Failed to read {env_path}: {exc}") from exc
        inline = dict(re.findall(r'(?m)^      ([^:\s]+): "(.*)"$', env_block))
        if inline != existing:
            diffs = sorted(
                key for key in set(inline) | set(existing) if inline.get(key) != existing.get(key)
            )
            raise ValueError(
                f"The compose file and .env of this app disagree for {diffs}, so this "
                "editor cannot switch the app to .env without possibly dropping your "
                "manual edits. Finish by hand: replace the `environment:` block in "
                f"{compose_path} with 'env_file: [{{path: .env, format: raw}}]' "
                "(or align the file with .env), then save again."
            )
        # Unique temp file in the same directory: never clobbers an existing
        # name or symlink, safe under parallel operations; os.replace is atomic.
        handle, tmp_name = tempfile.mkstemp(
            prefix=compose_path.name + ".", suffix=".tmp", dir=compose_path.parent
        )
        tmp = Path(tmp_name)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                stream.write(text.replace(env_block, ENV_FILE_REFERENCE + "\n"))
            if os.name == "posix":
                os.chmod(tmp, os.stat(compose_path).st_mode & 0o777)
            os.replace(tmp, compose_path)
        except OSError as exc:
            tmp.unlink(missing_ok=True)
            raise ValueError(f"Failed to write compose file: {exc}") from exc

    @staticmethod
    def _run_compose(command: list[str]) -> dict[str, str]:
        try:
            proc = subprocess.run(
                command,
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
        candidates: list[str | list[str]] = [
            command,
            ["/bin/bash", "-i"],
            ["/bin/sh", "-i"],
            ["bash", "-i"],
            ["sh", "-i"],
            ["ash", "-i"],
            "/bin/bash",
            "/bin/sh",
            "bash",
            "sh",
            "ash",
        ]

        unique_candidates: list[str | list[str]] = []
        seen: set[str] = set()
        for candidate in candidates:
            key = str(candidate)
            if key in seen:
                continue
            seen.add(key)
            unique_candidates.append(candidate)

        last_error: APIError | None = None
        for cmd_candidate in unique_candidates:
            try:
                exec_config = low_level.exec_create(
                    container=container.id,
                    cmd=cmd_candidate,
                    stdin=True,
                    tty=True,
                    workdir="/",
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

    def open_exec_socket_with_command(self, container_id: str, command: list[str]) -> Any:
        """Open an exec socket using a pre-resolved command list."""
        container = self._get_container_or_raise(container_id)
        if container.status != "running":
            raise ValueError("Container must be running to open exec terminal")

        low_level = self.client.api
        try:
            exec_config = low_level.exec_create(
                container=container.id,
                cmd=command,
                stdin=True,
                tty=True,
                workdir="/",
            )
            return low_level.exec_start(
                exec_config["Id"],
                tty=True,
                stream=False,
                socket=True,
            )
        except APIError as exc:
            raise ValueError(f"Failed to open exec socket: {exc.explanation}") from exc

    def resolve_exec_command(self, container_id: str, command: str = "/bin/sh") -> list[str]:
        """Resolve a working interactive shell command for docker exec."""
        container = self._get_container_or_raise(container_id)
        if container.status != "running":
            raise ValueError("Container must be running to open exec terminal")

        candidates = [
            command,
            "/bin/bash",
            "/bin/sh",
            "bash",
            "sh",
            "ash",
        ]
        unique_candidates = [c for i, c in enumerate(candidates) if c and c not in candidates[:i]]

        for shell in unique_candidates:
            try:
                probe = container.exec_run(
                    cmd=[shell, "-c", "printf __ok__"],
                    stdout=True,
                    stderr=True,
                )
                if isinstance(probe, tuple):
                    exit_code = int(probe[0])
                else:
                    exit_code = int(getattr(probe, "exit_code", 1))
                if exit_code == 0:
                    return [shell, "-i"]
            except APIError:
                continue

        raise ValueError("No supported shell found in container image")

    def list_volumes(self) -> list[dict[str, Any]]:
        """List docker volumes with useful metadata for the UI."""
        volumes = self.client.volumes.list()
        rows = [self._serialize_volume(volume) for volume in volumes]
        by_name = {str(row.get("name", "")): row for row in rows}

        for container in self.client.containers.list(all=True):
            owner = self._volume_owner_label(container)
            mounts = container.attrs.get("Mounts", []) if hasattr(container, "attrs") else []
            for mount in mounts:
                if mount.get("Type") != "volume":
                    continue
                volume_name = str(mount.get("Name", ""))
                if not volume_name or volume_name not in by_name:
                    continue

                used_by = by_name[volume_name].setdefault("used_by", [])
                if isinstance(used_by, list) and owner not in used_by:
                    used_by.append(owner)

        return [row for row in rows if not self._is_hidden_volume(row)]

    def create_volume(
        self,
        volume_name: str,
        labels: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Create a named docker volume.

        Raises:
            ValueError: If name is invalid or volume already exists.
        """
        candidate = volume_name.strip()
        if not self._VOLUME_NAME_PATTERN.fullmatch(candidate):
            raise ValueError(
                "Volume name must be 2-128 chars and contain only letters, numbers, ., _, -"
            )

        try:
            self.client.volumes.get(candidate)
            raise ValueError("Volume already exists")
        except NotFound:
            pass

        try:
            volume = self.client.volumes.create(name=candidate, labels=labels or {})
        except APIError as exc:
            raise ValueError(f"Docker API error: {exc.explanation}") from exc

        return self._serialize_volume(volume)

    def list_disks(self) -> list[dict[str, Any]]:
        """List host disk partitions and usage statistics."""
        partitions = psutil.disk_partitions(all=False)
        deduped: dict[tuple[str, str, int, int, int], dict[str, Any]] = {}
        for part in partitions:
            if self._should_skip_partition(part):
                continue

            mountpoint = part.mountpoint
            try:
                usage = psutil.disk_usage(mountpoint)
            except OSError:
                continue

            row = {
                "device": part.device,
                "mountpoint": mountpoint,
                "fstype": part.fstype,
                "opts": part.opts,
                "total_bytes": int(usage.total),
                "used_bytes": int(usage.used),
                "free_bytes": int(usage.free),
                "percent": float(usage.percent),
            }

            key = (
                str(part.device),
                str(part.fstype),
                int(usage.total),
                int(usage.used),
                int(usage.free),
            )
            existing = deduped.get(key)
            if existing is None or len(mountpoint) < len(str(existing["mountpoint"])):
                deduped[key] = row

        rows = list(deduped.values())
        rows.sort(key=lambda row: str(row.get("mountpoint", "")))
        return rows

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

    @staticmethod
    def _serialize_volume(volume: Any) -> dict[str, Any]:
        usage = volume.attrs.get("UsageData") or {}
        labels = volume.attrs.get("Labels") or {}
        ref_count = int(usage.get("RefCount", 0))
        compose_project = str(labels.get("com.docker.compose.project", "") or "")
        compose_volume = str(labels.get("com.docker.compose.volume", "") or "")
        app_hint = (
            f"{compose_project}/{compose_volume}"
            if compose_project and compose_volume
            else compose_project
        )
        return {
            "name": volume.name,
            "driver": volume.attrs.get("Driver", ""),
            "mountpoint": volume.attrs.get("Mountpoint", ""),
            "scope": volume.attrs.get("Scope", ""),
            "labels": labels,
            "created_at": volume.attrs.get("CreatedAt", ""),
            "size_bytes": int(usage.get("Size", 0) or 0),
            "ref_count": ref_count,
            "in_use": ref_count > 0,
            "app_hint": app_hint,
            "used_by": [],
        }

    @staticmethod
    def _volume_owner_label(container: Any) -> str:
        labels = container.attrs.get("Config", {}).get("Labels", {}) or {}
        project = str(labels.get("com.docker.compose.project", "") or "")
        service = str(labels.get("com.docker.compose.service", "") or "")
        if project and service:
            return f"{project}/{service}"
        if service:
            return service
        return str(getattr(container, "name", "") or "unknown")

    @classmethod
    def _is_hidden_volume(cls, volume: dict[str, Any]) -> bool:
        name = str(volume.get("name", ""))
        labels = volume.get("labels") or {}
        ref_count = int(volume.get("ref_count", 0) or 0)
        return bool(cls._ANONYMOUS_VOLUME_PATTERN.fullmatch(name) and ref_count == 0 and not labels)

    @classmethod
    def _should_skip_partition(cls, part: Any) -> bool:
        mountpoint = str(getattr(part, "mountpoint", ""))
        fstype = str(getattr(part, "fstype", ""))

        if not mountpoint or not Path(mountpoint).is_dir():
            return True
        if fstype in cls._IGNORED_DISK_FSTYPES:
            return True
        return any(
            mountpoint == prefix or mountpoint.startswith(f"{prefix}/")
            for prefix in cls._IGNORED_DISK_PREFIXES
        )

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

    def _map_host_path(self, raw: str) -> Path:
        if not os.getenv("HOMELAB_DATA_MOUNT"):
            native = Path(raw)
            if native.is_absolute():
                return native
            raise ValueError("Expected an absolute Compose project path")

        host = PurePosixPath(raw)
        if not host.is_absolute() or ".." in host.parts:
            raise ValueError("Invalid host project path")
        mounts = self._backend.attrs["Mounts"]
        # Match the most specific host directory. Never guess from a filename.
        for mount in sorted(mounts, key=lambda item: len(item["Source"]), reverse=True):
            source = PurePosixPath(mount["Source"])
            destination = Path(mount["Destination"])
            if host.is_relative_to(source) and destination.is_dir():
                mapped = (destination / host.relative_to(source)).resolve()
                if mapped.is_relative_to(destination.resolve()):
                    return mapped
        raise ValueError("The selected Compose project is not mounted in the backend")

    @cached_property
    def _backend(self) -> Any:
        return backend_container(self.client)

    def _project_directory(self, container: Any) -> Path:
        labels = container.attrs.get("Config", {}).get("Labels") or {}
        if labels.get("com.homelab.managed") == "true":
            name = str(labels.get("com.homelab.compose-project") or container.name)
            root = Path(settings.MARKETPLACE_APPS_DIR).resolve()
            candidate = (root / name).resolve()
            if candidate.parent == root and candidate.name == name and candidate.is_dir():
                return candidate
            raise ValueError("Marketplace project directory not found")

        working_dir = str(labels.get("com.docker.compose.project.working_dir") or "")
        if working_dir:
            directory = self._map_host_path(working_dir)
            if directory.is_dir():
                return directory
        raise ValueError("Compose project directory not found")

    def _compose_files(self, container: Any) -> list[Path]:
        directory = self._project_directory(container)
        labels = container.attrs["Config"]["Labels"]
        configured = str(labels.get("com.docker.compose.project.config_files") or "")
        if configured and labels.get("com.homelab.managed") != "true":
            files = []
            for raw in configured.split(","):
                name = raw.strip()
                if PurePosixPath(name).is_absolute() or Path(name).is_absolute():
                    path = self._map_host_path(name)
                else:
                    path = (directory / name).resolve()
                    if not path.is_relative_to(directory.resolve()):
                        raise ValueError("Compose path is outside the project")
                if not path.is_file():
                    raise ValueError("Configured Compose file not found")
                files.append(path)
            return files

        candidates = [directory / name for name in self._COMPOSE_FILENAMES]
        matches = [path for path in candidates if path.is_file()]
        if len(matches) != 1:
            raise ValueError("Cannot uniquely identify the Compose file for this project")
        return matches

    def _resolve_compose_file(self, container: Any) -> Path:
        return self._compose_files(container)[0]

    def _resolve_env_file(self, container: Any) -> Path:
        path = self._project_directory(container) / ".env"
        if not path.is_file():
            raise ValueError(".env file not found for compose project")
        return path

    def get_env_file(self, container_id: str) -> str:
        path = self._resolve_env_file(self._get_container_or_raise(container_id))
        return path.read_text(encoding="utf-8")

    @staticmethod
    def _calc_container_cpu(stats: dict[str, Any]) -> float:
        """Calculate CPU percentage using Docker stats delta values."""
        try:
            cpu_delta = float(
                stats["cpu_stats"]["cpu_usage"]["total_usage"]
                - stats["precpu_stats"]["cpu_usage"]["total_usage"]
            )
            system_delta = float(
                stats["cpu_stats"]["system_cpu_usage"] - stats["precpu_stats"]["system_cpu_usage"]
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
