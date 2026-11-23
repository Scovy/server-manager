"""Copy verified legacy panel data into its existing volume before container replacement."""

import hashlib
import os
import sqlite3
import sys
import tarfile
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import BinaryIO


def verify_database(path: Path) -> None:
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("SQLite integrity check failed")
        db.execute("SELECT id FROM users LIMIT 1").fetchall()


def inventory(path: Path) -> dict[str, tuple[str, str]]:
    result = {}
    for item in [path, *path.rglob("*")]:
        name = item.relative_to(path).as_posix()
        if item.is_symlink():
            if not item.resolve().is_relative_to(path.resolve()):
                raise ValueError(f"Link outside the data directory: {name}")
            result[name] = ("link", os.readlink(item))
        elif item.is_file():
            with item.open("rb") as handle:
                result[name] = ("file", hashlib.file_digest(handle, "sha256").hexdigest())
        elif item.is_dir():
            result[name] = ("directory", "")
        else:
            raise ValueError(f"Unsupported file in legacy data: {name}")
    return result


def migrate(stream: BinaryIO, volume: Path, database_location: str) -> None:
    with TemporaryDirectory(dir=volume, prefix=".migration-") as tmp:
        stage = Path(tmp)
        with tarfile.open(fileobj=stream, mode="r|*") as archive:
            for member in archive:
                parts = Path(member.name).parts
                if len(parts) < 2 or parts[0] != "app":
                    continue
                if parts[1] in ("apps", "backups") or parts[1:] in (
                    ("homelab.db",), ("homelab.db-wal",), ("homelab.db-journal",)
                ):
                    archive.extract(member, stage, filter="data")

        legacy = stage / "app"
        sources = [legacy / name for name in ("apps", "backups") if (legacy / name).exists()]
        if database_location == "layer":
            source = legacy / "homelab.db"
            verify_database(source)
            target = stage / "homelab.db"
            with closing(sqlite3.connect(source)) as db, closing(sqlite3.connect(target)) as snapshot:
                db.backup(snapshot)
            verify_database(target)
            sources.append(target)
        else:
            verify_database(volume / "homelab.db")

        pending = []
        for source in sources:
            target = volume / source.name
            if source.is_symlink() or target.is_symlink():
                raise ValueError(f"Unexpected link at the data root: {source.name}")
            contents = inventory(source)
            if target.exists():
                if contents == inventory(target):
                    continue
                if not target.is_dir() or any(target.iterdir()):
                    raise ValueError(f"Existing volume data differs: {target.name}")
            pending.append((source, target))
        for source, target in pending:
            if target.is_dir():
                target.rmdir()  # previously checked empty
            source.rename(target)
    print("Verified legacy data on the persistent volume.")


if __name__ == "__main__":
    migrate(sys.stdin.buffer, Path("/persist"), sys.argv[1])
