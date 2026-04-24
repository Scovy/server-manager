"""Authentication and authorization helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import uuid4

import bcrypt
import jwt
import pyotp
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.setting import Setting
from app.models.user import User

ALGORITHM = "HS256"
REFRESH_COOKIE_NAME = "refresh_token"
REFRESH_COOKIE_PATH = "/api/auth"

REFRESH_VERSION_PREFIX = "auth_refresh_version_user_"
PENDING_TOTP_PREFIX = "auth_pending_totp_user_"


class AuthError(ValueError):
    """Raised when authentication or token validation fails."""


@dataclass
class AuthTokens:
    access_token: str
    refresh_token: str
    expires_in: int


@dataclass
class LoginResult:
    user: User
    two_factor_required: bool


def hash_password(password: str) -> str:
    """Hash plaintext password with bcrypt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed_password: str) -> bool:
    """Verify plaintext password against bcrypt hash."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed_password.encode("utf-8"))
    except (TypeError, ValueError):
        return False


def issue_tokens(user: User, refresh_version: int) -> AuthTokens:
    """Issue short-lived access token and long-lived refresh token."""
    now = datetime.now(timezone.utc)
    access_exp = now + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    refresh_exp = now + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)

    access_payload: dict[str, Any] = {
        "sub": str(user.id),
        "type": "access",
        "username": user.username,
        "role": user.role,
        "iat": int(now.timestamp()),
        "exp": int(access_exp.timestamp()),
    }
    refresh_payload: dict[str, Any] = {
        "sub": str(user.id),
        "type": "refresh",
        "rv": refresh_version,
        "jti": uuid4().hex,
        "iat": int(now.timestamp()),
        "exp": int(refresh_exp.timestamp()),
    }

    access_token = jwt.encode(access_payload, settings.JWT_SECRET, algorithm=ALGORITHM)
    refresh_token = jwt.encode(refresh_payload, settings.JWT_SECRET, algorithm=ALGORITHM)

    return AuthTokens(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


def decode_access_token(token: str) -> dict[str, Any]:
    payload = _decode_token(token)
    if payload.get("type") != "access":
        raise AuthError("Invalid access token.")
    return payload


def decode_refresh_token(token: str) -> dict[str, Any]:
    payload = _decode_token(token)
    if payload.get("type") != "refresh":
        raise AuthError("Invalid refresh token.")
    return payload


def extract_subject_user_id(payload: dict[str, Any]) -> int:
    sub = payload.get("sub")
    try:
        return int(str(sub))
    except (TypeError, ValueError) as exc:
        raise AuthError("Token subject is invalid.") from exc


def extract_refresh_version(payload: dict[str, Any]) -> int:
    rv = payload.get("rv")
    try:
        return int(str(rv))
    except (TypeError, ValueError) as exc:
        raise AuthError("Token refresh version is invalid.") from exc


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def build_totp_uri(secret: str, username: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name=settings.APP_NAME)


def verify_totp_code(secret: str, code: str) -> bool:
    normalized = _normalize_totp_code(code)
    if not normalized:
        return False
    return bool(pyotp.TOTP(secret).verify(normalized, valid_window=1))


def serialize_auth_user(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "two_factor_enabled": bool(user.totp_secret),
    }


async def get_user_by_username(db: AsyncSession, username: str) -> User | None:
    row = await db.execute(select(User).where(User.username == username))
    return row.scalar_one_or_none()


async def get_user_by_id(db: AsyncSession, user_id: int) -> User | None:
    row = await db.execute(select(User).where(User.id == user_id))
    return row.scalar_one_or_none()


async def authenticate_login(
    db: AsyncSession,
    *,
    username: str,
    password: str,
    totp_code: str | None,
) -> LoginResult:
    """Authenticate login credentials."""
    normalized_username = username.strip()
    if not normalized_username:
        raise AuthError("Username is required.")
    if not password:
        raise AuthError("Password is required.")

    user = await get_user_by_username(db, normalized_username)

    if user is None:
        total_users = await count_users(db)
        if total_users == 0:
            raise AuthError("Initial admin account has not been created yet.")
        raise AuthError("Invalid username or password.")

    if not verify_password(password, user.password):
        raise AuthError("Invalid username or password.")

    if user.totp_secret:
        normalized_code = _normalize_totp_code(totp_code or "")
        if not normalized_code:
            return LoginResult(
                user=user,
                two_factor_required=True,
            )

        if not verify_totp_code(user.totp_secret, normalized_code):
            raise AuthError("Invalid two-factor authentication code.")

    return LoginResult(user=user, two_factor_required=False)


async def create_initial_admin(
    db: AsyncSession,
    *,
    username: str,
    password: str,
) -> User:
    """Create the very first admin account for a freshly initialized instance."""
    normalized_username = username.strip()
    if not normalized_username:
        raise AuthError("Username is required.")
    if not password:
        raise AuthError("Password is required.")

    existing_count = await count_users(db)
    if existing_count > 0:
        raise AuthError("Initial admin account has already been created.")

    user = User(
        username=normalized_username,
        password=hash_password(password),
        role="admin",
    )
    db.add(user)
    await db.flush()
    return user


async def get_refresh_version(db: AsyncSession, user_id: int) -> int:
    key = _refresh_version_key(user_id)
    row = await db.execute(select(Setting).where(Setting.key == key))
    setting = row.scalar_one_or_none()
    if setting is None or setting.value is None:
        return 0
    try:
        return max(int(setting.value), 0)
    except ValueError:
        return 0


async def bump_refresh_version(db: AsyncSession, user_id: int) -> int:
    current = await get_refresh_version(db, user_id)
    next_version = current + 1
    key = _refresh_version_key(user_id)
    row = await db.execute(select(Setting).where(Setting.key == key))
    setting = row.scalar_one_or_none()
    if setting is None:
        db.add(Setting(key=key, value=str(next_version)))
    else:
        setting.value = str(next_version)
    return next_version


async def create_pending_totp(db: AsyncSession, user_id: int) -> str:
    secret = generate_totp_secret()
    key = _pending_totp_key(user_id)
    row = await db.execute(select(Setting).where(Setting.key == key))
    setting = row.scalar_one_or_none()
    if setting is None:
        db.add(Setting(key=key, value=secret))
    else:
        setting.value = secret
    return secret


async def verify_or_enable_two_factor(
    db: AsyncSession,
    user: User,
    code: str,
) -> Literal["verified", "enabled"]:
    """Verify 2FA code against pending setup or existing TOTP secret."""
    normalized_code = _normalize_totp_code(code)
    if not normalized_code:
        raise AuthError("2FA code is required.")

    pending = await _get_pending_totp(db, user.id)
    if pending:
        if not verify_totp_code(pending, normalized_code):
            raise AuthError("Invalid two-factor authentication code.")
        user.totp_secret = pending
        await _clear_pending_totp(db, user.id)
        await bump_refresh_version(db, user.id)
        return "enabled"

    if not user.totp_secret:
        raise AuthError("No pending 2FA setup exists.")

    if not verify_totp_code(user.totp_secret, normalized_code):
        raise AuthError("Invalid two-factor authentication code.")

    return "verified"


def _decode_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("Token has expired.") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthError("Token is invalid.") from exc

    if not isinstance(payload, dict):
        raise AuthError("Token payload is invalid.")
    return payload


def _normalize_totp_code(code: str) -> str:
    return "".join(ch for ch in code.strip() if ch.isdigit())


def _refresh_version_key(user_id: int) -> str:
    return f"{REFRESH_VERSION_PREFIX}{user_id}"


def _pending_totp_key(user_id: int) -> str:
    return f"{PENDING_TOTP_PREFIX}{user_id}"


async def _get_pending_totp(db: AsyncSession, user_id: int) -> str | None:
    key = _pending_totp_key(user_id)
    row = await db.execute(select(Setting).where(Setting.key == key))
    setting = row.scalar_one_or_none()
    if setting is None or setting.value is None:
        return None
    return setting.value


async def _clear_pending_totp(db: AsyncSession, user_id: int) -> None:
    key = _pending_totp_key(user_id)
    row = await db.execute(select(Setting).where(Setting.key == key))
    setting = row.scalar_one_or_none()
    if setting is not None:
        await db.delete(setting)


async def count_users(db: AsyncSession) -> int:
    row = await db.execute(select(func.count(User.id)))
    return int(row.scalar_one())
