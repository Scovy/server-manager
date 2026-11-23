"""Installation invariants for the signing key and one-time setup."""

import asyncio
import runpy
from pathlib import Path
from unittest.mock import Mock

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.models import Base
from app.models.setting import Setting
from app.services import setup_service
from app.services.auth_service import AuthError, count_users, create_initial_admin


def test_backend_requires_a_non_placeholder_signing_key(monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
    with pytest.raises(ValidationError):
        Settings(JWT_SECRET="CHANGE-ME-IN-PRODUCTION", _env_file=None)


def test_installer_generates_distinct_stable_keys(tmp_path):
    script = Path(__file__).resolve().parents[2] / "scripts" / "init-backend-env.py"
    initialize = runpy.run_path(str(script))["initialize"]
    configs = []
    for name in ("fresh", "existing"):
        directory = tmp_path / name
        directory.mkdir()
        filename = ".env.example" if name == "fresh" else ".env"
        (directory / filename).write_text("DOMAIN=example\nJWT_SECRET=CHANGE-ME-IN-PRODUCTION\n")
        initialize(directory)
        result = (directory / ".env").read_text()
        assert "DOMAIN=example" in result
        key = result.split("JWT_SECRET=", 1)[1].strip()
        assert len(bytes.fromhex(key)) == 32
        initialize(directory)
        assert (directory / ".env").read_text() == result
        configs.append(result)
    assert configs[0] != configs[1]


async def test_concurrent_setup_and_admin_claims(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/setup.db")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setenv("SETUP_CONFIG_ROOT", str(tmp_path))
    (tmp_path / "backend").mkdir()
    validate = Mock(return_value=setup_service.SetupPreflightResult(True, [], [], []))
    monkeypatch.setattr(setup_service, "run_preflight", validate)
    payload = setup_service.SetupPayload("localhost", "admin@example.com", False, False, [])

    async def initialize():
        async with factory.begin() as db:
            return (await setup_service.initialize_setup(db, payload))["status"]

    async def claim(name):
        async with factory.begin() as db:
            try:
                await create_initial_admin(db, username=name, password="local-test-only")
            except AuthError:
                return False
            return True

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with factory.begin() as db:
            db.add(Setting(key="setup_initialized", value="false"))
        outcomes = await asyncio.gather(initialize(), initialize())
        assert sorted(outcomes) == ["already_initialized", "ok"]
        assert sorted(await asyncio.gather(claim("first"), claim("second"))) == [False, True]
        async with factory() as db:
            assert await count_users(db) == 1
    finally:
        await engine.dispose()
