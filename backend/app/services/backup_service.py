"""Backup service for config-only and full (with Docker volumes) backups."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tarfile
from collections.abc import Iterable
from contextlib import ExitStack, closing
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import docker
from docker.errors import APIError, DockerException, NotFound

from app.config import settings
from app.services.docker_mounts import panel_data_volume
from app.services.marketplace_service import (
    MarketplaceVolumeSpec,
    _deploy_with_docker_sdk,
    get_template,
)
from app.services.restore_transaction import Change, RestoreTransaction
from app.services.setup_service import resolve_env_paths


class BackupService:
    """Create, list, delete, and restore configuration backups."""

    MANIFEST_PATH = "manifest.json"
    FORMAT_VERSION = 1
    BACKUP_TYPE_CONFIG_ONLY = "config-only"
    BACKUP_TYPE_FULL = "full-with-volumes"
    VOLUME_HELPER_MOUNT_PATH = "/backup-volume"

    def __init__(self) -> None:
        self._backend_root = Path(__file__).resolve().parents[2]
        self._backup_dir = Path(settings.BACKUP_DIR).expanduser().resolve()
        self._backup_dir.mkdir(parents=True, exist_ok=True)

    def create_backup(self, include_volumes: bool = False) -> Path:
        """Create one backup archive and return its path."""
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        backup_kind = "full" if include_volumes else "config"
        archive_path = self._unique_archive_path(f"{backup_kind}-backup-{timestamp}.tar.gz")

        with TemporaryDirectory(prefix=f"{backup_kind}-backup-stage-") as tmp:
            stage_root = Path(tmp)
            checksums: dict[str, str] = {}

            database_archive_path = self._stage_database_snapshot(stage_root, checksums)
            apps_archive_path = self._stage_apps(stage_root, checksums)
            config_archive_paths = self._stage_config_files(stage_root, checksums)
            backup_type = self.BACKUP_TYPE_CONFIG_ONLY
            volumes: dict[str, Any] | None = None

            if include_volumes:
                volumes = self._stage_volumes(stage_root, checksums)
                backup_type = self.BACKUP_TYPE_FULL

            manifest: dict[str, Any] = {
                "format_version": self.FORMAT_VERSION,
                "backup_type": backup_type,
                "created_at": datetime.now(UTC).isoformat(),
                "database_archive_path": database_archive_path,
                "apps_archive_path": apps_archive_path,
                "config_archive_paths": config_archive_paths,
                "checksums": checksums,
            }
            if volumes is not None:
                manifest["volumes"] = volumes

            (stage_root / self.MANIFEST_PATH).write_text(
                json.dumps(manifest, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            self._pack_tar_gz(stage_root, archive_path)

        return archive_path

    def list_backups(self) -> list[dict[str, Any]]:
        """Return known backup archives in descending mtime order."""
        payload: list[dict[str, Any]] = []
        for item in self._backup_dir.glob("*.tar.gz"):
            if not item.is_file():
                continue
            stat = item.stat()
            payload.append(
                {
                    "filename": item.name,
                    "size_bytes": int(stat.st_size),
                    "updated_at": datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
                }
            )

        payload.sort(key=lambda row: row["updated_at"], reverse=True)
        return payload

    def delete_backup(self, filename: str) -> None:
        """Delete one archive by filename."""
        safe_name = self._validate_archive_name(filename)
        target = self._backup_dir / safe_name
        if not target.exists() or not target.is_file():
            raise ValueError("Backup not found")
        target.unlink()

    def restore_backup(self, archive_path: Path) -> dict[str, Any]:
        """Restore config files and optional Docker volumes from one backup archive."""
        if not archive_path.exists() or not archive_path.is_file():
            raise ValueError("Backup archive not found")

        with TemporaryDirectory(prefix="config-backup-restore-") as tmp:
            extract_root = Path(tmp) / "payload"
            extract_root.mkdir(parents=True, exist_ok=True)

            self._extract_tar_safely(archive_path, extract_root)
            manifest = self._load_and_validate_manifest(extract_root)
            self._verify_checksums(extract_root, manifest["checksums"])

            restored: dict[str, Any] = {
                "database": False,
                "apps_dir": False,
                "config_files": [],
                "volumes": [],
            }

            with ExitStack() as resources:
                txn = RestoreTransaction(self.backup_dir())
                resources.callback(txn.close)
                database = manifest.get("database_archive_path")
                apps = manifest.get("apps_archive_path")
                if database:
                    source = self._archive_member(extract_root, database, directory=False)
                    txn.prepare_path(source, self._resolve_database_path(), "db")
                    restored["database"] = True
                if apps:
                    source = self._archive_member(extract_root, apps, directory=True)
                    txn.prepare_path(source, self._apps_dir(), "dir")
                    restored["apps_dir"] = True
                config_paths = manifest.get("config_archive_paths")
                targets = self._config_target_map()
                if not isinstance(config_paths, list) or not all(
                    isinstance(rel, str) and rel in targets for rel in config_paths
                ):
                    raise ValueError("Invalid backup configuration file list")
                for rel in dict.fromkeys(config_paths):
                    source = self._archive_member(extract_root, rel, directory=False)
                    txn.prepare_path(source, targets[rel], "file")
                    restored["config_files"].append(str(targets[rel]))
                if manifest.get("backup_type") == self.BACKUP_TYPE_FULL:
                    restored["volumes"] = self._prepare_volumes(extract_root, manifest,
                                                               txn, resources)
                txn.apply()

            marketplace_restore: dict[str, list[str]] = {"restored": [], "errors": []}
            if restored["database"] and restored["apps_dir"]:
                db_target = self._resolve_database_path()
                marketplace_restore = self._restore_marketplace_apps_from_backup_database(db_target)
            restored["marketplace_apps"] = marketplace_restore["restored"]
            if marketplace_restore["errors"]:
                restored["marketplace_app_errors"] = marketplace_restore["errors"]

            message = "Backup restored successfully"
            if marketplace_restore["errors"]:
                message = "Backup restored with warnings"

            return {
                "status": "ok",
                "message": message,
                "restored": restored,
            }

    def backup_dir(self) -> Path:
        """Return backup directory path."""
        return self._backup_dir

    def _resolve_database_path(self) -> Path:
        url = settings.DATABASE_URL.strip()
        sqlite_prefixes = ("sqlite+aiosqlite:///", "sqlite:///")

        db_fragment = ""
        for prefix in sqlite_prefixes:
            if url.startswith(prefix):
                db_fragment = url[len(prefix) :]
                break

        if not db_fragment:
            raise ValueError("Only sqlite DATABASE_URL is supported by backup")

        candidate = Path(db_fragment).expanduser()
        if candidate.is_absolute():
            return candidate.resolve()
        return (self._backend_root / candidate).resolve()

    def _apps_dir(self) -> Path:
        return Path(settings.MARKETPLACE_APPS_DIR).expanduser().resolve()

    def _config_target_map(self) -> dict[str, Path]:
        project_env, backend_env = resolve_env_paths()
        caddy = project_env.parent / "caddy"
        return {
            "config/backend.env": backend_env,
            "config/project.env": project_env,
            "config/caddy.generated_globals.caddy": caddy / "generated_globals.caddy",
            "config/caddy.generated_site.caddy": caddy / "generated_site.caddy",
            "config/caddy.marketplace_apps.caddy": caddy / "marketplace_apps.caddy",
        }

    def _stage_database_snapshot(self, stage_root: Path, checksums: dict[str, str]) -> str | None:
        source_db = self._resolve_database_path()
        if not source_db.exists() or not source_db.is_file():
            return None

        target_rel = Path("db") / source_db.name
        target_file = stage_root / target_rel
        target_file.parent.mkdir(parents=True, exist_ok=True)

        with (
            closing(sqlite3.connect(source_db)) as src,
            closing(sqlite3.connect(target_file)) as dst,
        ):
            src.backup(dst)

        checksums[target_rel.as_posix()] = self._sha256(target_file)
        return target_rel.as_posix()

    def _stage_apps(self, stage_root: Path, checksums: dict[str, str]) -> str | None:
        source_apps = self._apps_dir()
        if not source_apps.exists() or not source_apps.is_dir():
            return None

        target_rel = Path("apps")
        target_dir = stage_root / target_rel
        if target_dir.exists():
            shutil.rmtree(target_dir)
        shutil.copytree(source_apps, target_dir)

        for file in target_dir.rglob("*"):
            if file.is_file():
                rel = file.relative_to(stage_root).as_posix()
                checksums[rel] = self._sha256(file)

        return target_rel.as_posix()

    def _stage_config_files(self, stage_root: Path, checksums: dict[str, str]) -> list[str]:
        archived: list[str] = []
        for rel_path, source_path in self._config_target_map().items():
            if not source_path.exists() or not source_path.is_file():
                continue
            target = stage_root / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target)
            checksums[rel_path] = self._sha256(target)
            archived.append(rel_path)
        return archived

    def _stage_volumes(self, stage_root: Path, checksums: dict[str, str]) -> dict[str, Any]:
        try:
            client = docker.from_env()
        except DockerException as exc:
            raise ValueError(f"Docker unavailable for volume backup: {exc}") from exc

        volumes_payload: list[dict[str, Any]] = []
        helper_image: str | None = None
        try:
            own_volume = panel_data_volume(client)
            for volume in client.volumes.list():
                name = str(getattr(volume, "name", "")).strip()
                if not name or "/" in name or name == own_volume:
                    continue

                mountpoint_raw = str(volume.attrs.get("Mountpoint", "")).strip()
                mountpoint = Path(mountpoint_raw)
                target_rel = Path("volumes") / name
                target_dir = stage_root / target_rel
                if target_dir.exists():
                    shutil.rmtree(target_dir)

                copied = False
                if mountpoint_raw and mountpoint.exists() and mountpoint.is_dir():
                    try:
                        shutil.copytree(mountpoint, target_dir)
                        copied = True
                    except OSError:
                        if target_dir.exists():
                            shutil.rmtree(target_dir)

                if not copied:
                    if helper_image is None:
                        helper_image = self._resolve_volume_helper_image(client)
                    self._copy_volume_with_helper(client, helper_image, name, target_dir)

                for file in target_dir.rglob("*"):
                    if file.is_file():
                        rel = file.relative_to(stage_root).as_posix()
                        checksums[rel] = self._sha256(file)

                volumes_payload.append(
                    {
                        "name": name,
                        "driver": str(volume.attrs.get("Driver", "local") or "local"),
                        "labels": volume.attrs.get("Labels") or {},
                        "archive_path": target_rel.as_posix(),
                    }
                )
        except APIError as exc:
            raise ValueError(f"Docker API error during volume backup: {exc.explanation}") from exc
        except OSError as exc:
            raise ValueError(f"Failed to backup Docker volumes: {exc}") from exc
        finally:
            client.close()

        return {
            "items": volumes_payload,
        }

    @staticmethod
    def _archive_member(root: Path, name: Any, *, directory: bool) -> Path:
        if not isinstance(name, str) or not name or Path(name).is_absolute():
            raise ValueError("Invalid archive member")
        path = (root / name).resolve()
        if path == root.resolve() or not path.is_relative_to(root.resolve()):
            raise ValueError("Archive member outside backup")
        exists = path.is_dir() if directory else path.is_file()
        if not exists:
            raise ValueError(f"Missing archive member: {name}")
        return path

    def _prepare_volumes(
        self, root: Path, manifest: dict[str, Any], txn: RestoreTransaction, resources: ExitStack
    ) -> list[str]:
        section = manifest.get("volumes")
        if not isinstance(section, dict) or not isinstance(section.get("items"), list):
            raise ValueError("Invalid volume metadata")
        if not section["items"]:
            return []
        client = docker.from_env()
        resources.callback(client.close)
        own = panel_data_volume(client)
        entries: dict[str, tuple[dict[str, Any], Path]] = {}
        for item in section["items"]:
            if not isinstance(item, dict):
                raise ValueError("Invalid volume entry")
            name = item.get("name")
            if not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", name):
                raise ValueError("Invalid volume name")
            if name == own:
                continue
            if name in entries:
                raise ValueError(f"Duplicate volume: {name}")
            entries[name] = (item, self._archive_member(root, item.get("archive_path"),
                                                        directory=True))
        if not entries:
            return []
        image = self._resolve_volume_helper_image(client)
        paused = set()
        for name in entries:
            for container in client.containers.list(filters={"volume": name}):
                if container.id in paused or container.status != "running":
                    continue
                if container.id.startswith(os.environ.get("HOSTNAME", "") or "!"):
                    raise ValueError("Cannot pause the backend during restore")
                container.pause()
                resources.callback(container.unpause)
                paused.add(container.id)
        for name, (item, directory) in entries.items():
            incoming = txn.directory / f"new-volume-{name}.tar"
            with tarfile.open(incoming, "w") as tar:
                for child in sorted(directory.iterdir()):
                    tar.add(child, arcname=child.name)
            self._prepare_volume(client, image, name, item, incoming, txn, resources)
        return list(entries)

    def _prepare_volume(
        self, client: Any, image: str, name: str, item: dict[str, Any], incoming: Path,
        txn: RestoreTransaction, resources: ExitStack,
    ) -> None:
        try:
            client.volumes.get(name)
            existed = True
        except NotFound:
            existed = False
        previous = txn.directory / f"previous-volume-{name}.tar"
        # For a missing volume the helper is prepared before any live contents change.
        # Remove this newly created resource if this or any later preparation fails.
        keep = [existed]
        if not existed:
            volume = client.volumes.create(name=name, driver=item.get("driver") or "local",
                                           labels=item.get("labels") or {})

            def remove_unused() -> None:
                if not keep[0]:
                    volume.remove()

            resources.callback(remove_unused)
        helper = self._create_volume_helper_container(client, image, name, "rw")
        resources.callback(self._remove_helper_container, helper)
        mount = self.VOLUME_HELPER_MOUNT_PATH
        if existed:
            stream, _ = helper.get_archive(f"{mount}/.")
            with previous.open("wb") as handle:
                for chunk in stream:
                    handle.write(chunk)
        capacity = helper.exec_run(["sh", "-ec", 'df -Pk "$1" | tail -1; du -sk "$1"',
                                    "capacity", mount])
        if capacity.exit_code:
            raise ValueError(f"Cannot check disk space for volume {name}")
        disk, used = capacity.output.decode().splitlines()
        available = (int(disk.split()[-3]) + int(used.split()[0])) * 1024
        if available < incoming.stat().st_size:
            raise ValueError(f"Insufficient disk space for volume {name}")

        def replace(tar_path: Path) -> None:
            clear = helper.exec_run(["sh", "-ec", 'find "$1" -mindepth 1 -maxdepth 1 '
                                     '-exec rm -rf -- {} +', "restore", mount])
            if clear.exit_code:
                raise ValueError(f"Cannot clear volume {name}")
            with tar_path.open("rb") as handle:
                if not helper.put_archive(mount, handle):
                    raise ValueError(f"Cannot restore volume {name}")

        def apply() -> None:
            replace(incoming)
            keep[0] = True

        def undo() -> None:
            if existed:
                replace(previous)
            else:
                keep[0] = False

        txn.changes.append(
            Change(f"volume:{name}", previous.name if existed else None, apply, undo)
        )

    def _restore_marketplace_apps_from_backup_database(
        self, database_path: Path
    ) -> dict[str, list[str]]:
        if not database_path.exists() or not database_path.is_file():
            return {"restored": [], "errors": ["Marketplace restore skipped: database not found"]}

        app_rows = self._read_marketplace_app_rows(database_path)
        if not app_rows:
            return {"restored": [], "errors": []}

        restored: list[str] = []
        errors: list[str] = []
        for row in app_rows:
            app_name = row["app_name"]
            template_id = row["template_id"]
            host_port = row["host_port"]
            compose_path = self._resolve_marketplace_compose_path(row)
            if compose_path is None:
                errors.append(f"Skipped {app_name}: compose file not found")
                continue
            app_dir = compose_path.parent

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
                    stderr = (
                        proc.stderr.strip()
                        or proc.stdout.strip()
                        or "Unknown docker compose error"
                    )
                    errors.append(f"Failed to restore app {app_name}: {stderr}")
                    continue
                restored.append(app_name)
                continue
            except OSError as exc:
                if exc.errno != 2:
                    errors.append(f"Failed to restore app {app_name}: {exc}")
                    continue
            except subprocess.TimeoutExpired:
                errors.append(f"Failed to restore app {app_name}: docker compose restore timed out")
                continue

            try:
                template = get_template(template_id)
            except ValueError as exc:
                errors.append(f"Failed to restore app {app_name}: {exc}")
                continue

            env = self._read_env_file(app_dir / ".env")
            volumes = self._parse_named_volume_specs(compose_path)
            try:
                _deploy_with_docker_sdk(
                    template=template,
                    app_name=app_name,
                    host_port=host_port,
                    env=env,
                    volumes=volumes,
                )
                restored.append(app_name)
            except ValueError as exc:
                errors.append(f"Failed to restore app {app_name}: {exc}")

        return {"restored": restored, "errors": errors}

    @staticmethod
    def _read_marketplace_app_rows(database_path: Path) -> list[dict[str, Any]]:
        try:
            with sqlite3.connect(str(database_path)) as conn:
                table_columns = {
                    str(row[1]).strip().lower()
                    for row in conn.execute("PRAGMA table_info(apps)").fetchall()
                }
                if not table_columns:
                    return []

                select_columns = ["app_name", "template_id", "host_port"]
                has_app_dir = "app_dir" in table_columns
                has_compose_path = "compose_path" in table_columns
                if has_app_dir:
                    select_columns.append("app_dir")
                if has_compose_path:
                    select_columns.append("compose_path")

                query = f"""
                SELECT {", ".join(select_columns)}
                FROM apps
                WHERE app_name IS NOT NULL AND template_id IS NOT NULL AND host_port IS NOT NULL
                ORDER BY id ASC
                """
                rows = conn.execute(query).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                return []
            raise

        payload: list[dict[str, Any]] = []
        for row in rows:
            app_name = row[0]
            template_id = row[1]
            host_port = row[2]
            app_dir = row[3] if has_app_dir else None
            compose_path = row[4] if has_compose_path else None

            name = str(app_name).strip()
            template = str(template_id).strip()
            if not name or not template:
                continue
            try:
                port = int(host_port)
            except (TypeError, ValueError):
                continue
            payload.append(
                {
                    "app_name": name,
                    "template_id": template,
                    "host_port": port,
                    "app_dir": str(app_dir or "").strip() or None,
                    "compose_path": str(compose_path or "").strip() or None,
                }
            )
        return payload

    def _resolve_marketplace_compose_path(self, row: dict[str, Any]) -> Path | None:
        app_name = str(row.get("app_name", "")).strip()
        app_dir_raw = str(row.get("app_dir", "")).strip()
        compose_path_raw = str(row.get("compose_path", "")).strip()

        candidates: list[Path] = []
        if compose_path_raw:
            candidates.append(Path(compose_path_raw).expanduser())

        if app_dir_raw:
            candidates.append(Path(app_dir_raw).expanduser() / "docker-compose.yml")

        if app_name:
            candidates.append(self._apps_dir() / app_name / "docker-compose.yml")

        seen: set[str] = set()
        for candidate in candidates:
            key = str(candidate)
            if key in seen:
                continue
            seen.add(key)
            if candidate.exists() and candidate.is_file():
                return candidate
        return None

    @staticmethod
    def _read_env_file(path: Path) -> dict[str, str]:
        if not path.exists() or not path.is_file():
            return {}
        env: dict[str, str] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            key = key.strip()
            if not key:
                continue
            env[key] = value.strip()
        return env

    @staticmethod
    def _parse_named_volume_specs(compose_path: Path) -> list[MarketplaceVolumeSpec]:
        if not compose_path.exists() or not compose_path.is_file():
            return []

        specs: list[MarketplaceVolumeSpec] = []
        seen: set[tuple[str, str]] = set()
        for raw_line in compose_path.read_text(encoding="utf-8").splitlines():
            stripped = raw_line.strip()
            if not stripped.startswith("-"):
                continue

            entry = stripped[1:].strip().strip("'").strip('"')
            if ":" not in entry:
                continue
            source, target = entry.split(":", 1)
            source = source.strip()
            target = target.strip()
            if not source or not target.startswith("/"):
                continue
            if "/" in source or "\\" in source:
                continue

            key = (source, target)
            if key in seen:
                continue
            seen.add(key)
            volume_spec: MarketplaceVolumeSpec = {"name": source, "mount_path": target}
            specs.append(volume_spec)
        return specs

    def _resolve_volume_helper_image(self, client: Any) -> str:
        current_container_id = os.environ.get("HOSTNAME", "").strip()
        if current_container_id:
            try:
                current_container = client.containers.get(current_container_id)
                image_id = str(getattr(current_container.image, "id", "")).strip()
                if image_id:
                    return image_id
            except (APIError, NotFound):
                pass

        try:
            for container in client.containers.list():
                image_id = str(getattr(container.image, "id", "")).strip()
                if image_id:
                    return image_id
        except APIError:
            pass

        try:
            for image in client.images.list():
                image_id = str(getattr(image, "id", "")).strip()
                if image_id:
                    return image_id
        except APIError:
            pass

        raise ValueError("Could not determine a helper Docker image for volume transfer")

    def _copy_volume_with_helper(
        self,
        client: Any,
        helper_image: str,
        volume_name: str,
        destination: Path,
    ) -> None:
        helper = self._create_volume_helper_container(
            client=client,
            helper_image=helper_image,
            volume_name=volume_name,
            mount_mode="ro",
        )
        try:
            archive_stream, _ = helper.get_archive(self.VOLUME_HELPER_MOUNT_PATH)
            self._extract_archive_stream_to_directory(archive_stream, destination)
        except APIError as exc:
            raise ValueError(
                f"Docker API error while reading volume {volume_name}: {exc.explanation}"
            ) from exc
        finally:
            self._remove_helper_container(helper)

    def _create_volume_helper_container(
        self,
        client: Any,
        helper_image: str,
        volume_name: str,
        mount_mode: str,
    ) -> Any:
        try:
            helper = client.containers.create(
                image=helper_image,
                entrypoint=["sh", "-c"],
                command=["exec sleep 86400"],
                network_disabled=True,
                volumes={
                    volume_name: {
                        "bind": self.VOLUME_HELPER_MOUNT_PATH,
                        "mode": mount_mode,
                    }
                },
                detach=True,
            )
            helper.start()
            return helper
        except APIError as exc:
            raise ValueError(
                f"Docker API error while preparing helper container for {volume_name}: "
                f"{exc.explanation}"
            ) from exc

    @staticmethod
    def _remove_helper_container(container: Any) -> None:
        try:
            container.remove(force=True)
        except (APIError, DockerException):
            pass

    def _extract_archive_stream_to_directory(
        self, archive_stream: Iterable[bytes], destination: Path
    ) -> None:
        with TemporaryDirectory(prefix="backup-volume-extract-") as tmp:
            tmp_root = Path(tmp)
            archive_path = tmp_root / "volume.tar"
            with archive_path.open("wb") as handle:
                for chunk in archive_stream:
                    handle.write(chunk)

            extract_root = tmp_root / "extracted"
            extract_root.mkdir(parents=True, exist_ok=True)
            self._extract_tar_safely(archive_path, extract_root)

            source_root = self._resolve_extracted_root(extract_root)
            if destination.exists():
                shutil.rmtree(destination)
            shutil.copytree(source_root, destination)

    @staticmethod
    def _resolve_extracted_root(extract_root: Path) -> Path:
        children = list(extract_root.iterdir())
        if len(children) == 1 and children[0].is_dir():
            return children[0]
        return extract_root

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _pack_tar_gz(source_dir: Path, destination: Path) -> None:
        with tarfile.open(destination, "w:gz") as tar:
            for item in sorted(source_dir.rglob("*")):
                arcname = item.relative_to(source_dir)
                tar.add(item, arcname=arcname, recursive=False)

    @staticmethod
    def _extract_tar_safely(archive_path: Path, destination: Path) -> None:
        destination_abs = destination.resolve()
        try:
            with tarfile.open(archive_path, "r:*") as tar:
                members = tar.getmembers()
                if sum(member.size for member in members) > shutil.disk_usage(destination).free:
                    raise ValueError("Insufficient disk space to extract backup")
                for member in members:
                    target = (destination / member.name).resolve()
                    if not target.is_relative_to(destination_abs):
                        raise ValueError("Backup archive contains unsafe file paths")
                tar.extractall(path=destination, filter="data")
                if any(m.issym() and not (destination / m.name).is_symlink() for m in members):
                    raise ValueError("The destination filesystem could not preserve symbolic links")
        except tarfile.TarError as exc:
            raise ValueError("Backup archive contains unsafe file paths") from exc

    def _load_and_validate_manifest(self, extract_root: Path) -> dict[str, Any]:
        manifest_path = extract_root / self.MANIFEST_PATH
        if not manifest_path.exists() or not manifest_path.is_file():
            raise ValueError("Backup manifest not found")

        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("Backup manifest is invalid JSON") from exc

        if not isinstance(payload, dict):
            raise ValueError("Backup manifest has invalid structure")
        if payload.get("format_version") != self.FORMAT_VERSION:
            raise ValueError("Backup format version is not supported")

        backup_type = payload.get("backup_type")
        if backup_type not in {self.BACKUP_TYPE_CONFIG_ONLY, self.BACKUP_TYPE_FULL}:
            raise ValueError("Backup type is not supported")

        checksums = payload.get("checksums")
        if not isinstance(checksums, dict):
            raise ValueError("Backup manifest is missing checksums")

        return payload

    def _verify_checksums(self, extract_root: Path, checksums: dict[str, Any]) -> None:
        files = {p.relative_to(extract_root).as_posix() for p in extract_root.rglob("*")
                 if p.is_file() and p != extract_root / self.MANIFEST_PATH}
        if files != set(checksums):
            raise ValueError("Backup file list does not match manifest checksums")
        for rel_path, expected in checksums.items():
            if not isinstance(rel_path, str) or not isinstance(expected, str):
                raise ValueError("Backup checksums section is invalid")
            candidate = (extract_root / rel_path).resolve()
            if not candidate.is_relative_to(extract_root.resolve()):
                raise ValueError("Backup checksum entry points outside archive")
            if not candidate.exists() or not candidate.is_file():
                raise ValueError(f"Missing file declared in checksums: {rel_path}")
            actual = self._sha256(candidate)
            if actual.lower() != expected.lower():
                raise ValueError(f"Checksum mismatch for {rel_path}")

    def _unique_archive_path(self, filename: str) -> Path:
        candidate = self._backup_dir / filename
        if not candidate.exists():
            return candidate

        stem = filename[:-7] if filename.endswith(".tar.gz") else filename
        suffix = ".tar.gz"
        index = 1
        while True:
            trial = self._backup_dir / f"{stem}-{index}{suffix}"
            if not trial.exists():
                return trial
            index += 1

    @staticmethod
    def _validate_archive_name(filename: str) -> str:
        candidate = filename.strip()
        if not candidate or candidate != Path(candidate).name:
            raise ValueError("Invalid backup filename")
        if not candidate.endswith(".tar.gz"):
            raise ValueError("Only .tar.gz backup archives are supported")
        return candidate
