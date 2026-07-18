"""
app.api.deps — FastAPI dependency injection for JWT auth.

Provides `get_current_user` which extracts and validates the JWT token
from the Authorization header, returning the decoded token payload
(including `sub` for owner_id).

All tools-service endpoints require JWT authentication.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from shared.config.settings import settings

logger = logging.getLogger(__name__)

_bearer = HTTPBearer()

# Cache for Keycloak public keys (JWKS)
_jwks_cache: Dict[str, Any] = {}


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> Dict[str, Any]:
    """
    Extract and validate the JWT Bearer token.

    Returns the decoded token payload. Raises 401 if the token is
    invalid, expired, or missing.

    The `sub` field is the Keycloak user ID (used as owner_id).
    """
    token = credentials.credentials

    try:
        # Attempt to decode the JWT
        import jwt as pyjwt

        # For development: if using HS256 with shared secret
        if settings.JWT_ALGORITHM == "HS256":
            payload = pyjwt.decode(
                token,
                settings.JWT_SECRET_KEY,
                algorithms=[settings.JWT_ALGORITHM],
            )
            return payload

        # For production: RS256 with Keycloak JWKS
        if not _jwks_cache:
            await _fetch_jwks()

        from jwt import PyJWKClient
        jwks_client = PyJWKClient(
            f"{settings.KEYCLOAK_SERVER_URL}realms/master/protocol/openid-connect/certs"
        )
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        payload = pyjwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            options={"verify_iss": settings.VERIFY_ISSUER},
        )
        return payload

    except Exception as exc:
        logger.warning("JWT validation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def _fetch_jwks() -> None:
    """Fetch Keycloak JWKS and cache it."""
    try:
        url = f"{settings.KEYCLOAK_SERVER_URL}realms/master/protocol/openid-connect/certs"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url)
            resp.raise_for_status()
            _jwks_cache.update(resp.json())
    except Exception as exc:
        logger.error("Failed to fetch JWKS from Keycloak: %s", exc)
