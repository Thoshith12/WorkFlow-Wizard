"""app.models.enums.roles — User role enum definitions."""
import enum


class UserRole(str, enum.Enum):
    """User role types — mirrors Keycloak role assignments."""
    USER = "user"
    REALM_ADMIN = "realm-admin"
    ADMIN = "admin"
