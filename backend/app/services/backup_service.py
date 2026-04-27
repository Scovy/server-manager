"""Backup service for config-only and full (with Docker volumes) backups."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import tarfile
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import docker
from docker.errors import APIError, DockerException, NotFound

from app.config import settings
from app.services.marketplace_service import (
    MarketplaceVolumeSpec,
    _deploy_with_docker_sdk,
    get_template,
)


class BackupService:
    """Create, list, delete, and restore configuration backups."""

    MANIFEST_PATH = "manifest.json"
    FORMAT_VERSION = 1
    BACKUP_TYPE_CONFIG_ONLY = "config-only"
    BACKUP_TYPE_FULL = "full-with-volumes"
    VOLUME_HELPER_MOUNT_PATH = "/backup-volume"

    def __init__(self) -> None:
        self._backend_root = Path(__file__).resolve().parents[2]
        self._project_root = self._backend_root.parent
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

            database_archive_path = str(manifest.get("database_archive_path") or "").strip()
            if database_archive_path:
                db_source = extract_root / database_archive_path
                if db_source.exists() and db_source.is_file():
                    db_target = self._resolve_database_path()
                    db_target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(db_source, db_target)
                    restored["database"] = True

            apps_archive_path = str(manifest.get("apps_archive_path") or "").strip()
            if apps_archive_path:
                apps_source = extract_root / apps_archive_path
                if apps_source.exists() and apps_source.is_dir():
                    apps_target = self._apps_dir()
                    apps_target.parent.mkdir(parents=True, exist_ok=True)
                    if apps_target.exists():
                        if apps_target.is_dir() and not apps_target.is_symlink():
                            shutil.rmtree(apps_target)
                        else:
                            apps_target.unlink()
                    shutil.copytree(apps_source, apps_target)
                    restored["apps_dir"] = True

            restored_config_files: list[str] = []
            for archive_rel, target in self._config_target_map().items():
                source = extract_root / archive_rel
                if not source.exists() or not source.is_file():
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                restored_config_files.append(str(target))
            restored["config_files"] = restored_config_files

            if manifest.get("backup_type") == self.BACKUP_TYPE_FULL:
                restored["volumes"] = self._restore_volumes(extract_root, manifest)

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
        return {
            "config/backend.env": self._backend_root / ".env",
            "config/project.env": self._project_root / ".env",
            "config/caddy.generated_globals.caddy": self._project_root
            / "caddy"
            / "generated_globals.caddy",
            "config/caddy.generated_site.caddy": self._project_root
            / "caddy"
            / "generated_site.caddy",
            "config/caddy.marketplace_apps.caddy": self._project_root
            / "caddy"
            / "marketplace_apps.caddy",
        }

    def _stage_database_snapshot(self, stage_root: Path, checksums: dict[str, str]) -> str | None:
        source_db = self._resolve_database_path()
        if not source_db.exists() or not source_db.is_file():
            return None

        target_rel = Path("db") / source_db.name
        target_file = stage_root / target_rel
        target_file.parent.mkdir(parents=True, exist_ok=True)

        with sqlite3.connect(str(source_db)) as src, sqlite3.connect(str(target_file)) as dst:
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
            for volume in client.volumes.list():
                name = str(getattr(volume, "name", "")).strip()
                if not name or "/" in name:
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

    def _restore_volumes(self, extract_root: Path, manifest: dict[str, Any]) -> list[str]:
        volumes_section = manifest.get("volumes")
        if not isinstance(volumes_section, dict):
            raise ValueError("Backup manifest is missing volume metadata")

        items = volumes_section.get("items")
        if not isinstance(items, list):
            raise ValueError("Backup volume metadata is invalid")
        if not items:
            return []

        try:
            client = docker.from_env()
        except DockerException as exc:
            raise ValueError(f"Docker unavailable for volume restore: {exc}") from exc

        restored_names: list[str] = []
        helper_image: str | None = None
        try:
            for item in items:
                if not isinstance(item, dict):
                    raise ValueError("Backup volume item is invalid")

                name = str(item.get("name", "")).strip()
                if not name or "/" in name:
                    raise ValueError("Backup contains invalid volume name")

                driver = str(item.get("driver", "local") or "local").strip() or "local"
                labels = item.get("labels")
                labels_payload = labels if isinstance(labels, dict) else {}
                archive_rel = str(item.get("archive_path", "")).strip()
                if not archive_rel:
                    raise ValueError(f"Missing volume archive path for {name}")

                source_dir = (extract_root / archive_rel).resolve()
                if not source_dir.is_relative_to(extract_root.resolve()):
                    raise ValueError(f"Unsafe archive path for volume {name}")
                if not source_dir.exists() or not source_dir.is_dir():
                    raise ValueError(f"Missing archived data for volume {name}")

                try:
                    volume = client.volumes.get(name)
                except NotFound:
                    volume = client.volumes.create(name=name, driver=driver, labels=labels_payload)
                volume.reload()

                mountpoint_raw = str(volume.attrs.get("Mountpoint", "")).strip()
                mountpoint = Path(mountpoint_raw)
                if mountpoint_raw and mountpoint.exists() and mountpoint.is_dir():
                    self._replace_directory_contents(source_dir, mountpoint)
                else:
                    if helper_image is None:
                        helper_image = self._resolve_volume_helper_image(client)
                    self._restore_volume_with_helper(client, helper_image, name, source_dir)
                restored_names.append(name)
        except APIError as exc:
            raise ValueError(f"Docker API error during volume restore: {exc.explanation}") from exc
        except OSError as exc:
            raise ValueError(f"Failed to restore Docker volumes: {exc}") from exc
        finally:
            client.close()

        return restored_names

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
        for app_name, template_id, host_port in app_rows:
            app_dir = self._apps_dir() / app_name
            compose_path = app_dir / "docker-compose.yml"
            if not app_dir.exists() or not app_dir.is_dir():
                errors.append(f"Skipped {app_name}: app directory not found")
                continue
            if not compose_path.exists() or not compose_path.is_file():
                errors.append(f"Skipped {app_name}: compose file not found")
                continue

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
    def _read_marketplace_app_rows(database_path: Path) -> list[tuple[str, str, int]]:
        query = """
        SELECT app_name, template_id, host_port
        FROM apps
        WHERE app_name IS NOT NULL AND template_id IS NOT NULL AND host_port IS NOT NULL
        ORDER BY id ASC
        """
        try:
            with sqlite3.connect(str(database_path)) as conn:
                rows = conn.execute(query).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                return []
            raise

        payload: list[tuple[str, str, int]] = []
        for app_name, template_id, host_port in rows:
            name = str(app_name or "").strip()
            template = str(template_id or "").strip()
            if not name or not template:
                continue
            try:
                port = int(host_port)
            except (TypeError, ValueError):
                continue
            payload.append((name, template, port))
        return payload

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

    def _restore_volume_with_helper(
        self,
        client: Any,
        helper_image: str,
        volume_name: str,
        source_dir: Path,
    ) -> None:
        helper = self._create_volume_helper_container(
            client=client,
            helper_image=helper_image,
            volume_name=volume_name,
            mount_mode="rw",
        )
        try:
            result = helper.exec_run(
                [
                    "sh",
                    "-lc",
                    (
                        "rm -rf "
                        f"{self.VOLUME_HELPER_MOUNT_PATH}/* "
                        f"{self.VOLUME_HELPER_MOUNT_PATH}/.[!.]* "
                        f"{self.VOLUME_HELPER_MOUNT_PATH}/..?*"
                    ),
                ]
            )
            if result.exit_code != 0:
                stderr = (result.output or b"").decode("utf-8", errors="ignore").strip()
                raise ValueError(
                    f"Failed to clear data before restoring volume {volume_name}: "
                    f"{stderr or 'unknown error'}"
                )

            archive_payload = self._create_tar_payload(source_dir)
            accepted = helper.put_archive(self.VOLUME_HELPER_MOUNT_PATH, archive_payload)
            if not accepted:
                raise ValueError(f"Failed to restore data into volume {volume_name}")
        except APIError as exc:
            raise ValueError(
                f"Docker API error while restoring volume {volume_name}: {exc.explanation}"
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
                command=["sh", "-lc", "while true; do sleep 3600; done"],
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
    def _create_tar_payload(source_dir: Path) -> bytes:
        with TemporaryDirectory(prefix="backup-volume-pack-") as tmp:
            archive_path = Path(tmp) / "volume.tar"
            with tarfile.open(archive_path, "w") as tar:
                for item in sorted(source_dir.iterdir()):
                    tar.add(item, arcname=item.name, recursive=True)
            return archive_path.read_bytes()

    @staticmethod
    def _replace_directory_contents(source: Path, destination: Path) -> None:
        for child in destination.iterdir():
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink(missing_ok=True)

        for child in source.iterdir():
            target = destination / child.name
            if child.is_dir() and not child.is_symlink():
                shutil.copytree(child, target)
            else:
                shutil.copy2(child, target)

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
        with tarfile.open(archive_path, "r:*") as tar:
            members = tar.getmembers()
            for member in members:
                if member.issym() or member.islnk():
                    raise ValueError("Backup archive contains unsupported symlink entry")
                target = (destination / member.name).resolve()
                if not target.is_relative_to(destination_abs):
                    raise ValueError("Backup archive contains unsafe file paths")
            tar.extractall(path=destination)

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
