"""Backup service for config-only and full (with Docker volumes) backups."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import docker
from docker.errors import APIError, DockerException, NotFound

from app.config import settings


class BackupService:
    """Create, list, delete, and restore configuration backups."""

    MANIFEST_PATH = "manifest.json"
    FORMAT_VERSION = 1
    BACKUP_TYPE_CONFIG_ONLY = "config-only"
    BACKUP_TYPE_FULL = "full-with-volumes"

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

            return {
                "status": "ok",
                "message": "Backup restored successfully",
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
        try:
            for volume in client.volumes.list():
                name = str(getattr(volume, "name", "")).strip()
                if not name or "/" in name:
                    continue

                mountpoint_raw = str(volume.attrs.get("Mountpoint", "")).strip()
                mountpoint = Path(mountpoint_raw)
                if not mountpoint_raw or not mountpoint.exists() or not mountpoint.is_dir():
                    raise ValueError(f"Volume mountpoint not accessible: {name}")

                target_rel = Path("volumes") / name
                target_dir = stage_root / target_rel
                if target_dir.exists():
                    shutil.rmtree(target_dir)
                shutil.copytree(mountpoint, target_dir)

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

                mountpoint_raw = str(volume.attrs.get("Mountpoint", "")).strip()
                mountpoint = Path(mountpoint_raw)
                if not mountpoint_raw or not mountpoint.exists() or not mountpoint.is_dir():
                    raise ValueError(f"Cannot access mountpoint for volume {name}")

                self._replace_directory_contents(source_dir, mountpoint)
                restored_names.append(name)
        except APIError as exc:
            raise ValueError(f"Docker API error during volume restore: {exc.explanation}") from exc
        except OSError as exc:
            raise ValueError(f"Failed to restore Docker volumes: {exc}") from exc
        finally:
            client.close()

        return restored_names

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
