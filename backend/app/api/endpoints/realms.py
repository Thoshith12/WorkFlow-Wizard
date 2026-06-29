"""
app.api.endpoints.realms — Realm management endpoints.

POST /api/realms — Create a new Keycloak realm with a default client.
"""
from fastapi import APIRouter, Depends, status

from app.services.keycloak import keycloak_service
from app.schemas.realm import RealmCreate, RealmResponse
from shared.auth.dependencies import get_token

router = APIRouter()


@router.post(
    "/realms",
    response_model=RealmResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Realm",
)
async def create_realm(
    payload: RealmCreate,
    token: str = Depends(get_token),
):
    """
    Create a new Keycloak realm and initialise a default `fastapi-client` inside it.

    Requires a valid master realm administrator access token.
    """
    return keycloak_service.create_realm(
        realm_name=payload.realm_name,
        access_token=token,
    )
