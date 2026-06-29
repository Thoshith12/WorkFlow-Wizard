"""
shared.auth.dependencies — FastAPI auth dependency injections.

Provides reusable Depends() wrappers for token extraction from
HTTP Authorization Bearer headers.

Usage:
    from shared.auth.dependencies import get_token

    @router.get("/protected")
    async def endpoint(token: str = Depends(get_token)):
        ...
"""
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer = HTTPBearer()


def get_token(credentials: HTTPAuthorizationCredentials = Depends(_bearer)) -> str:
    """Extract and return the Bearer token string from Authorization header."""
    return credentials.credentials
