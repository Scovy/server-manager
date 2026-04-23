"""Authentication router: login, refresh, logout, and 2FA setup/verify."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.dependencies.auth import require_current_user
from app.models.user import User
from app.services.auth_service import (
    REFRESH_COOKIE_NAME,
    REFRESH_COOKIE_PATH,
    AuthError,
    authenticate_login,
    build_totp_uri,
    bump_refresh_version,
    create_pending_totp,
    decode_refresh_token,
    extract_refresh_version,
    extract_subject_user_id,
    get_refresh_version,
    get_user_by_id,
    issue_tokens,
    serialize_auth_user,
    verify_or_enable_two_factor,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class AuthUserResponse(BaseModel):
    id: int
    username: str
    role: str
    two_factor_enabled: bool


class AuthSuccessResponse(BaseModel):
    status: Literal["ok"] = "ok"
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    user: AuthUserResponse
    bootstrap_created: bool = False


class TwoFactorRequiredResponse(BaseModel):
    status: Literal["2fa_required"] = "2fa_required"
    message: str


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)
    totp_code: str | None = Field(default=None, max_length=12)


class StatusResponse(BaseModel):
    status: Literal["ok"] = "ok"
    message: str


class TwoFactorSetupResponse(BaseModel):
    secret: str
    otpauth_uri: str


class TwoFactorVerifyRequest(BaseModel):
    code: str = Field(min_length=6, max_length=12)


class TwoFactorVerifyResponse(BaseModel):
    status: Literal["verified", "enabled"]
    two_factor_enabled: bool


@router.post("/login", response_model=AuthSuccessResponse | TwoFactorRequiredResponse)
async def login(
    payload: LoginRequest,
    response: Response,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> AuthSuccessResponse | TwoFactorRequiredResponse:
    """Authenticate credentials and issue JWT access + refresh tokens."""
    try:
        result = await authenticate_login(
            db,
            username=payload.username,
            password=payload.password,
            totp_code=payload.totp_code,
        )
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    if result.two_factor_required:
        return TwoFactorRequiredResponse(
            message="Two-factor authentication code is required to complete login.",
        )

    refresh_version = await get_refresh_version(db, result.user.id)
    tokens = issue_tokens(result.user, refresh_version)
    _set_refresh_cookie(response, tokens.refresh_token, secure=_is_secure_request(request))

    return AuthSuccessResponse(
        access_token=tokens.access_token,
        expires_in=tokens.expires_in,
        user=AuthUserResponse(**serialize_auth_user(result.user)),
        bootstrap_created=result.bootstrap_created,
    )


@router.post("/refresh", response_model=AuthSuccessResponse)
async def refresh(
    response: Response,
    request: Request,
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db),
) -> AuthSuccessResponse:
    """Rotate refresh cookie and issue a fresh access token."""
    secure = _is_secure_request(request)
    if not refresh_token:
        _clear_refresh_cookie(response, secure=secure)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing refresh token.",
        )

    try:
        payload = decode_refresh_token(refresh_token)
        user_id = extract_subject_user_id(payload)
        token_version = extract_refresh_version(payload)
    except AuthError as exc:
        _clear_refresh_cookie(response, secure=secure)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    user = await get_user_by_id(db, user_id)
    if user is None:
        _clear_refresh_cookie(response, secure=secure)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user no longer exists.",
        )

    current_version = await get_refresh_version(db, user.id)
    if token_version != current_version:
        _clear_refresh_cookie(response, secure=secure)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session was revoked. Please sign in again.",
        )

    tokens = issue_tokens(user, current_version)
    _set_refresh_cookie(response, tokens.refresh_token, secure=secure)

    return AuthSuccessResponse(
        access_token=tokens.access_token,
        expires_in=tokens.expires_in,
        user=AuthUserResponse(**serialize_auth_user(user)),
    )


@router.post("/logout", response_model=StatusResponse)
async def logout(
    response: Response,
    request: Request,
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db),
) -> StatusResponse:
    """Invalidate refresh session for current token and clear auth cookie."""
    secure = _is_secure_request(request)

    if refresh_token:
        try:
            payload = decode_refresh_token(refresh_token)
            user_id = extract_subject_user_id(payload)
        except AuthError:
            user_id = None

        if user_id is not None:
            user = await get_user_by_id(db, user_id)
            if user is not None:
                await bump_refresh_version(db, user.id)

    _clear_refresh_cookie(response, secure=secure)
    return StatusResponse(message="Logged out.")


@router.get("/me", response_model=AuthUserResponse)
async def me(current_user: User = Depends(require_current_user)) -> AuthUserResponse:
    """Return current authenticated user profile."""
    return AuthUserResponse(**serialize_auth_user(current_user))


@router.post("/2fa/setup", response_model=TwoFactorSetupResponse)
async def setup_two_factor(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> TwoFactorSetupResponse:
    """Generate and return pending TOTP secret + otpauth URI for authenticator apps."""
    secret = await create_pending_totp(db, current_user.id)
    return TwoFactorSetupResponse(
        secret=secret,
        otpauth_uri=build_totp_uri(secret, current_user.username),
    )


@router.post("/2fa/verify", response_model=TwoFactorVerifyResponse)
async def verify_two_factor(
    payload: TwoFactorVerifyRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> TwoFactorVerifyResponse:
    """Verify TOTP code and enable 2FA if a pending setup exists."""
    try:
        outcome = await verify_or_enable_two_factor(db, current_user, payload.code)
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return TwoFactorVerifyResponse(
        status=outcome,
        two_factor_enabled=bool(current_user.totp_secret),
    )


def _is_secure_request(request: Request) -> bool:
    return request.url.scheme == "https"


def _set_refresh_cookie(response: Response, token: str, *, secure: bool) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=secure,
        samesite="lax",
        path=REFRESH_COOKIE_PATH,
        max_age=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
    )


def _clear_refresh_cookie(response: Response, *, secure: bool) -> None:
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=secure,
        samesite="lax",
    )
