"""Prepare recovery copies before applying a restore. Keep them if compensation fails."""

import json
import os
import shutil
import sqlite3
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile, mkdtemp


@dataclass
class Change:
    name: str
    recovery: str | None
    apply: Callable[[], None]
    revert: Callable[[], None]


def copy_database(source: Path, target: Path) -> None:
    with (
        closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as src,
        closing(sqlite3.connect(target)) as dst,
    ):
        src.backup(dst)


def copy_file(source: Path, target: Path) -> None:
    with NamedTemporaryFile(dir=target.parent, delete=False) as temp:
        path = Path(temp.name)
    try:
        shutil.copy2(source, path)
        os.replace(path, target)
    finally:
        path.unlink(missing_ok=True)


def copy_tree(source: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for item in target.iterdir():
        if item.is_dir() and not item.is_symlink():
            shutil.rmtree(item)
        else:
            item.unlink()
    shutil.copytree(source, target, symlinks=True, dirs_exist_ok=True)


class RestoreTransaction:
    def __init__(self, backup_dir: Path):
        self.directory = Path(mkdtemp(prefix=".restore-", dir=backup_dir))
        self.changes: list[Change] = []
        self.keep_recovery = False

    def prepare_path(self, source: Path, target: Path, kind: str) -> None:
        if self.directory.is_relative_to(target):
            raise ValueError("Backup storage overlaps the restore target")
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_symlink() or target.is_symlink():
            raise ValueError(f"Restore target or source is a symbolic link: {target}")
        if kind == "db":
            with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as db:
                if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                    raise ValueError("Invalid SQLite backup")
        copier = {"db": copy_database, "dir": copy_tree, "file": copy_file}[kind]
        size = sum(p.stat().st_size for p in source.rglob("*") if p.is_file()) if (
            kind == "dir"
        ) else source.stat().st_size
        if shutil.disk_usage(target.parent).free < size:
            raise ValueError(f"Insufficient disk space for restore at {target}")
        previous = self.directory / f"previous-{len(self.changes)}"
        existed = target.exists()
        if existed:
            copier(target, previous)

        def undo() -> None:
            if existed:
                copier(previous, target)
            elif kind == "dir" and target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink(missing_ok=True)

        self.changes.append(Change(str(target), previous.name if existed else None,
                                   lambda: copier(source, target), undo))

    def apply(self) -> None:
        records = [{"target": c.name, "previous": c.recovery} for c in self.changes]
        (self.directory / "recovery.json").write_text(json.dumps(records, indent=2))
        attempted: list[Change] = []
        try:
            for change in self.changes:
                attempted.append(change)
                change.apply()
        except Exception as original:
            errors = []
            for change in reversed(attempted):
                try:
                    change.revert()
                except Exception as exc:
                    errors.append(f"{change.name}: {exc}")
            if errors:
                self.keep_recovery = True
                detail = ", ".join(errors)
                raise RuntimeError(f"Rollback incomplete. Recovery copies: {self.directory}. "
                                   f"{detail}") from original
            raise ValueError(f"Restore failed. Previous data restored: {original}") from original

    def close(self) -> None:
        if not self.keep_recovery:
            shutil.rmtree(self.directory)
