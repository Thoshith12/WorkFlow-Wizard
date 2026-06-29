"""app.schemas.token — Token request/response Pydantic schemas."""
from typing import Optional
from pydantic import BaseModel, Field


class TokenRequest(BaseModel):
    username: str = Field(..., examples=["admin"])
    password: str = Field(..., examples=["admin"])
    client_id: Optional[str] = Field(
        default=None,
        description="Defaults to 'admin-cli' for master realm, 'fastapi-client' otherwise.",
    )


class TokenRefreshRequest(BaseModel):
    refresh_token: str = Field(..., description="OIDC refresh token from login.")
    client_id: Optional[str] = Field(default=None)


class TokenResponse(BaseModel):
    access_token: str
    expires_in: int
    refresh_expires_in: int
    refresh_token: str
    token_type: str
    not_before_policy: Optional[int] = Field(default=None, alias="not-before-policy")
    session_state: Optional[str] = None
    scope: Optional[str] = None

    model_config = {"populate_by_name": True}


class AdminLoginRequest(BaseModel):
    username: str = Field(..., examples=["admin"], description="Keycloak admin username")
    password: str = Field(..., examples=["admin"], description="Keycloak admin password")


class AuthTokenJWTResponse(BaseModel):
    access_token: str = Field(..., description="Custom signed JWT auth token.")
    token_type: str = Field(default="bearer")
    user_id: str = Field(..., description="Keycloak user ID (sub UUID).")
    expires_in: int = Field(..., description="Token expiration duration in seconds.")
