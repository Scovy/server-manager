import json
import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.config import settings
from app.services import marketplace_service as market
from app.services.alerts import DEFAULT_ALERT_CONFIG, ThresholdAlerts
from app.services.backup_service import BackupService
from app.services.maintenance import MaintenanceBusy, gate
from app.services.metrics_service import MetricsSnapshot
from app.services.restore_transaction import Change


def test_marketplace_retry_keeps_foreign_files_and_resumes_its_own(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MARKETPLACE_APPS_DIR", str(tmp_path))
    monkeypatch.setattr(market, "is_port_available", lambda port: True)
    request = dict(template_id="dozzle", app_name="example", host_port=10311, env={}, volumes=[])
    responses = [SimpleNamespace(returncode=1, stderr="offline", stdout=""),
                 SimpleNamespace(returncode=0, stderr="", stdout="running")]
    with patch.object(market.subprocess, "run", side_effect=responses):
        with pytest.raises(ValueError, match="offline"):
            market.deploy_template(request)
        directory = tmp_path / "example"
        old = (directory / "docker-compose.yml").read_bytes()
        monkeypatch.setattr(market, "is_port_available", lambda port: False)
        assert market.preflight_deploy(request, set())["valid"]
        with pytest.raises(ValueError, match="original settings"):
            market.deploy_template(dict(request, host_port=10312))
        assert market.deploy_template(request)["status"] == "ok"
        assert (directory / "docker-compose.yml").read_bytes() == old
        (directory / ".deployment-pending").unlink()
        with pytest.raises(ValueError, match="already exists"):
            market.deploy_template(request)


async def test_threshold_crossing_recovery_failed_delivery_and_config_change():
    sample = MetricsSnapshot(cpu_percent=81, ram_percent=1, ram_used_mb=1, ram_total_mb=1,
                             disk_percent=1, disk_used_gb=1, disk_total_gb=1,
                             net_bytes_sent=0, net_bytes_recv=0)
    config = {**DEFAULT_ALERT_CONFIG, "webhook_url": "https://example.invalid/alerts"}
    evaluate = ThresholdAlerts().evaluate
    post = AsyncMock(side_effect=[
        httpx.ConnectError("offline"), MagicMock(), MagicMock(), MagicMock(),
    ])
    with patch("httpx.AsyncClient.post", post):
        await evaluate(sample, config)
        await evaluate(sample, config)
        await evaluate(sample, config)
        assert post.await_count == 2
        await evaluate(sample.model_copy(update={"cpu_percent": 1}), config)
        await evaluate(sample, config)
        await evaluate(sample, {**config, "cpu_threshold": 75})
        assert post.await_count == 4


def test_restore_rolls_back_database_config_and_app_files_after_volume_error(tmp_path, monkeypatch):
    dbfile = tmp_path / "state.db"
    apps = tmp_path / "apps"
    apps.mkdir()
    config = tmp_path / ".env"
    backups = tmp_path / "backups"
    monkeypatch.setattr(settings, "DATABASE_URL", "sqlite:///" + dbfile.as_posix())
    monkeypatch.setattr(settings, "MARKETPLACE_APPS_DIR", str(apps))
    monkeypatch.setattr(settings, "BACKUP_DIR", str(backups))
    service = BackupService()
    monkeypatch.setattr(service, "_config_target_map", lambda: {"config/project.env": config})
    monkeypatch.setattr(service, "_stage_volumes", lambda *_: {"items": []})
    with closing(sqlite3.connect(dbfile)) as db, db:
        db.execute("CREATE TABLE markers(value TEXT)")
        db.execute("INSERT INTO markers VALUES ('archived')")
    (apps / "compose.yml").write_text("old")
    config.write_text("old")
    archive = service.create_backup(include_volumes=True)
    with closing(sqlite3.connect(dbfile)) as db, db:
        db.execute("UPDATE markers SET value='live'")
    (apps / "compose.yml").write_text("live")
    config.write_text("live")
    volume = ["live"]

    def fail():
        volume[0] = "partially restored"
        raise OSError("volume write failed")

    def prepare(root, manifest, txn, resources):
        txn.changes.append(Change("volume:test", None, fail, lambda: volume.__setitem__(0, "live")))
        return ["test"]

    monkeypatch.setattr(service, "_prepare_volumes", prepare)
    with pytest.raises(ValueError, match="Previous data restored"):
        service.restore_backup(archive)
    with closing(sqlite3.connect(dbfile)) as db:
        assert db.execute("SELECT value FROM markers").fetchone() == ("live",)
    assert volume == ["live"]
    assert config.read_text() == (apps / "compose.yml").read_text() == "live"
    assert not list(backups.glob(".restore-*"))


def test_restore_gate_excludes_active_operations_and_releases_after_failure():
    with gate.operation(), pytest.raises(MaintenanceBusy), gate.restore():
        pytest.fail("Restore began during an active write")
    with gate.restore(), pytest.raises(MaintenanceBusy), gate.operation():
        pytest.fail("Write began during restore")
    assert gate.active == 0 and not gate.restoring
