"""Tests for auth router: login, refresh/logout, and 2FA endpoints."""

import pyotp
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services.auth_service import hash_password


@pytest.mark.asyncio
async def test_login_bootstraps_first_admin_account(client: AsyncClient, async_db: AsyncSession):
    res = await client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "supersecret"},
    )

    assert res.status_code == 200
    payload = res.json()
    assert payload["status"] == "ok"
    assert payload["bootstrap_created"] is True
    assert payload["user"]["username"] == "admin"
    assert payload["user"]["role"] == "admin"
    assert "refresh_token=" in res.headers.get("set-cookie", "")

    row = await async_db.execute(select(User).where(User.username == "admin"))
    user = row.scalar_one_or_none()
    assert user is not None
    assert user.password != "supersecret"


@pytest.mark.asyncio
async def test_login_requires_totp_when_enabled(client: AsyncClient, async_db: AsyncSession):
    secret = pyotp.random_base32()
    async_db.add(
        User(
            username="alice",
            password=hash_password("pass1234"),
            totp_secret=secret,
            role="admin",
        )
    )
    await async_db.flush()

    challenge_res = await client.post(
        "/api/auth/login",
        json={"username": "alice", "password": "pass1234"},
    )
    assert challenge_res.status_code == 200
    assert challenge_res.json()["status"] == "2fa_required"

    invalid_res = await client.post(
        "/api/auth/login",
        json={"username": "alice", "password": "pass1234", "totp_code": "000000"},
    )
    assert invalid_res.status_code == 401

    valid_res = await client.post(
        "/api/auth/login",
        json={
            "username": "alice",
            "password": "pass1234",
            "totp_code": pyotp.TOTP(secret).now(),
        },
    )
    assert valid_res.status_code == 200
    assert valid_res.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_refresh_and_logout_flow(client: AsyncClient):
    login_res = await client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "secret123"},
    )
    assert login_res.status_code == 200
    assert login_res.json()["status"] == "ok"

    refresh_res = await client.post("/api/auth/refresh")
    assert refresh_res.status_code == 200
    assert refresh_res.json()["status"] == "ok"

    logout_res = await client.post("/api/auth/logout")
    assert logout_res.status_code == 200
    assert logout_res.json()["status"] == "ok"

    refresh_after_logout = await client.post("/api/auth/refresh")
    assert refresh_after_logout.status_code == 401


@pytest.mark.asyncio
async def test_me_and_two_factor_setup_verify(client: AsyncClient, async_db: AsyncSession):
    login_res = await client.post(
        "/api/auth/login",
        json={"username": "bob", "password": "pass1234"},
    )
    assert login_res.status_code == 200
    payload = login_res.json()
    access_token = payload["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}

    me_res = await client.get("/api/auth/me", headers=headers)
    assert me_res.status_code == 200
    assert me_res.json()["username"] == "bob"
    assert me_res.json()["two_factor_enabled"] is False

    setup_res = await client.post("/api/auth/2fa/setup", headers=headers)
    assert setup_res.status_code == 200
    setup_payload = setup_res.json()
    assert "secret" in setup_payload
    assert "otpauth://" in setup_payload["otpauth_uri"]

    code = pyotp.TOTP(setup_payload["secret"]).now()
    verify_res = await client.post("/api/auth/2fa/verify", json={"code": code}, headers=headers)
    assert verify_res.status_code == 200
    assert verify_res.json()["status"] == "enabled"
    assert verify_res.json()["two_factor_enabled"] is True
    assert verify_res.json()["access_token"]
    assert verify_res.json()["user"]["two_factor_enabled"] is True
    assert "refresh_token=" in verify_res.headers.get("set-cookie", "")

    refresh_res = await client.post("/api/auth/refresh")
    assert refresh_res.status_code == 200
    assert refresh_res.json()["status"] == "ok"

    row = await async_db.execute(select(User).where(User.username == "bob"))
    user = row.scalar_one_or_none()
    assert user is not None
    assert user.totp_secret is not None
