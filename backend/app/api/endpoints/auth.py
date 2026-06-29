from datetime import datetime, timedelta, timezone
import jwt
from fastapi import APIRouter

from shared.config.settings import settings
from app.services.keycloak import keycloak_service
from app.schemas.token import (
    TokenRequest,
    TokenRefreshRequest,
    TokenResponse,
    AdminLoginRequest,
    AuthTokenJWTResponse,
)

router = APIRouter()


@router.post(
    "/auth/admin-login",
    response_model=AuthTokenJWTResponse,
    tags=["Admin Login"],
    summary="Admin Login",
)
async def admin_login(payload: AdminLoginRequest):
    """
    Authenticate Keycloak admin credentials (username and password) against the master realm,
    extract the Keycloak User ID (sub), and generate a signed custom auth JWT token.
    """
    realm_name = "master"
    client_id = "admin-cli"

    # 1. Authenticate with Keycloak and retrieve OIDC tokens
    keycloak_tokens = keycloak_service.get_tokens(
        realm_name=realm_name,
        username=payload.username,
        password=payload.password,
        client_id=client_id,
    )

    # 2. Extract Keycloak User ID (sub) from Keycloak access token
    kc_access_token = keycloak_tokens.get("access_token")
    decoded_kc = jwt.decode(kc_access_token, options={"verify_signature": False})
    user_id = decoded_kc.get("sub", "")

    # 3. Generate custom signed JWT token
    now = datetime.now(timezone.utc)
    expires_delta = timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    expire = now + expires_delta

    jwt_payload = {
        "user_id": user_id,
        "sub": user_id,
        "username": payload.username,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "iss": "keycloak-fastapi-backend",
    }

    token_str = jwt.encode(
        jwt_payload,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    if isinstance(token_str, bytes):
        token_str = token_str.decode("utf-8")

    return AuthTokenJWTResponse(
        access_token=token_str,
        token_type="bearer",
        user_id=user_id,
        expires_in=int(expires_delta.total_seconds()),
    )


@router.post(
    "/realms/{realm_name}/tokens",
    response_model=TokenResponse,
    tags=["Auth"],
    summary="Get Tokens",
)
async def get_tokens(realm_name: str, payload: TokenRequest):
    """Exchange username/password credentials for OIDC access + refresh tokens."""
    client_id = payload.client_id or (
        "admin-cli" if realm_name == "master" else "fastapi-client"
    )
    return keycloak_service.get_tokens(
        realm_name=realm_name,
        username=payload.username,
        password=payload.password,
        client_id=client_id,
    )


@router.post(
    "/realms/{realm_name}/tokens/refresh",
    response_model=TokenResponse,
    tags=["Auth"],
    summary="Refresh Tokens",
)
async def refresh_tokens(realm_name: str, payload: TokenRefreshRequest):
    """Obtain a new access token using a valid refresh token."""
    client_id = payload.client_id or (
        "admin-cli" if realm_name == "master" else "fastapi-client"
    )
    return keycloak_service.refresh_tokens(
        realm_name=realm_name,
        refresh_token=payload.refresh_token,
        client_id=client_id,
    )
