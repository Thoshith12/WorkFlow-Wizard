"""
app.api.endpoints.users — User management endpoints.

POST /api/realms/{realm_name}/users         — Create a new user in a realm
GET  /api/realms/{realm_name}/me            — Get current user profile from token
GET  /api/realms/{realm_name}/admin-only    — Admin-protected test endpoint
"""
from fastapi import APIRouter, Depends, HTTPException, status

from app.services.keycloak import keycloak_service
from app.schemas.user import UserCreate, UserResponse, UserProfileResponse
from shared.auth.dependencies import get_token

router = APIRouter()


@router.post(
    "/realms/{realm_name}/users",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create User",
)
async def create_user(
    realm_name: str,
    payload: UserCreate,
    token: str = Depends(get_token),
):
    """Create a user with a specified role inside a target realm."""
    return keycloak_service.create_user(
        realm_name=realm_name,
        username=payload.username,
        email=payload.email,
        password=payload.password,
        role=payload.role,
        access_token=token,
    )


@router.get(
    "/realms/{realm_name}/me",
    response_model=UserProfileResponse,
    summary="Get Profile",
)
async def get_profile(
    realm_name: str,
    token: str = Depends(get_token),
):
    """Decode and return the user profile embedded in their access token."""
    decoded = keycloak_service.decode_token(realm_name=realm_name, token=token)

    realm_roles = decoded.get("realm_access", {}).get("roles", [])
    client_roles = [
        f"{client}/{role}"
        for client, config in decoded.get("resource_access", {}).items()
        for role in config.get("roles", [])
    ]

    return UserProfileResponse(
        username=decoded.get("preferred_username", ""),
        email=decoded.get("email"),
        sub=decoded.get("sub", ""),
        roles=realm_roles + client_roles,
        is_admin=keycloak_service.is_realm_admin(decoded) or keycloak_service.is_global_admin(decoded),
        is_global_admin=keycloak_service.is_global_admin(decoded),
    )


@router.get(
    "/realms/{realm_name}/admin-only",
    summary="Admin Guard",
)
async def admin_only(
    realm_name: str,
    token: str = Depends(get_token),
):
    """Protected endpoint — accessible only to realm or global admins."""
    decoded = keycloak_service.decode_token(realm_name=realm_name, token=token)

    if not (keycloak_service.is_realm_admin(decoded) or keycloak_service.is_global_admin(decoded)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: administrator privileges required.",
        )

    return {
        "status": "success",
        "message": f"Admin access granted for realm '{realm_name}'.",
        "user": decoded.get("preferred_username"),
        "is_global_admin": keycloak_service.is_global_admin(decoded),
    }
