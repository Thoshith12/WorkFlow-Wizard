"""app.schemas.realm — Realm request/response Pydantic schemas."""
from pydantic import BaseModel, Field


class RealmCreate(BaseModel):
    realm_name: str = Field(
        ...,
        description="Realm name — alphanumeric characters and dashes only.",
        examples=["my-new-realm"],
    )


class RealmResponse(BaseModel):
    realm: str
    status: str
    default_client: str
