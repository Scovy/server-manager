"""Authentication dependencies for protected endpoints."""

from fastapi import Depends, HTTPException, WebSocket, WebSocketException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.services.auth_service import (
    AuthError,
    decode_access_token,
    extract_subject_user_id,
    get_user_by_id,
)

bearer_scheme = HTTPBearer(auto_error=False)
WS_PROTOCOL = "homelab.v1"


async def require_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Require a valid Bearer access token and return the authenticated user."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated.",
        )

    return await _get_access_user(credentials.credentials, db)


async def _get_access_user(token: str, db: AsyncSession) -> User:
    try:
        payload = decode_access_token(token)
        user_id = extract_subject_user_id(payload)
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    user = await get_user_by_id(db, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user no longer exists.",
        )
    return user


async def require_websocket_admin(websocket: WebSocket, db: AsyncSession = Depends(get_db)) -> None:
    """Validate the browser's offered credentials before accepting the upgrade."""
    protocols = websocket.scope.get("subprotocols", [])
    if len(protocols) != 2 or protocols[0] != WS_PROTOCOL:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)
    try:
        user = await _get_access_user(protocols[1], db)
        await require_admin_user(user)
    except HTTPException as exc:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION) from exc
    # A terminal may stay open for hours. Release the authentication read transaction.
    await db.commit()


async def require_admin_user(user: User = Depends(require_current_user)) -> User:
    """Require authenticated user with admin role."""
    if user.role.lower() != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges are required.",
        )
    return user

