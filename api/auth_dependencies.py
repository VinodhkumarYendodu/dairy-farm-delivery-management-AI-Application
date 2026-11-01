"""Role-based dependencies shared by the versioned API routes."""
from __future__ import annotations

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from database.repositories.auth import AuthRepository
from services.auth_service import AuthService

bearer = HTTPBearer(auto_error=False)


def get_current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Sign in is required", headers={"WWW-Authenticate": "Bearer"})
    try:
        user = AuthRepository().resolve_session(AuthService.token_hash(credentials.credentials))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Authentication service is unavailable") from exc
    if not user:
        raise HTTPException(status_code=401, detail="Session is invalid or expired", headers={"WWW-Authenticate": "Bearer"})
    return user


def require_roles(*roles: str):
    allowed = {role.upper() for role in roles}

    def dependency(user: dict = Depends(get_current_user)) -> dict:
        if user["role"] not in allowed:
            raise HTTPException(status_code=403, detail="This account does not have permission for this operation")
        return user

    return dependency


require_staff = require_roles("ADMIN", "AGENT")
require_admin = require_roles("ADMIN")
require_customer = require_roles("CUSTOMER")
