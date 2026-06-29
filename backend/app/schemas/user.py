"""app.schemas.user — User request/response Pydantic schemas."""
from typing import List, Literal, Optional
from pydantic import BaseModel, EmailStr, Field


class UserCreate(BaseModel):
    username: str = Field(..., examples=["john_doe"])
    email: EmailStr = Field(..., examples=["john@example.com"])
    password: str = Field(..., min_length=6, examples=["SecurePassword123"])
    role: Literal["user", "realm-admin", "admin"] = Field(default="user")


class UserResponse(BaseModel):
    user_id: str
    username: str
    email: str
    role: str
    assigned_roles: List[str]
    status: str


class UserProfileResponse(BaseModel):
    username: str
    email: Optional[str] = None
    sub: str
    roles: List[str]
    is_admin: bool
    is_global_admin: bool
