"""
app.services.keycloak — Keycloak Admin & OIDC service.

Migrated from the original app/keycloak_service.py.
Updated to import settings from shared.config.settings.
"""
import logging
import time
from typing import Any, Dict

from fastapi import HTTPException, status
from keycloak import KeycloakAdmin, KeycloakOpenID
from keycloak.exceptions import KeycloakError, KeycloakGetError, KeycloakPostError

from shared.config.settings import settings

logger = logging.getLogger(__name__)


class KeycloakService:
    """Keycloak Admin REST API and OIDC token management service."""

    def __init__(self) -> None:
        self.server_url = settings.keycloak_url
        self.admin_user = settings.KEYCLOAK_ADMIN_USER
        self.admin_password = settings.KEYCLOAK_ADMIN_PASSWORD

    def wait_for_keycloak(self, max_retries: int = 20, delay: int = 3) -> bool:
        """Wait for Keycloak server to start and database migrations to complete."""
        logger.info("Connecting to Keycloak at %s...", self.server_url)
        for i in range(max_retries):
            try:
                admin = KeycloakAdmin(
                    server_url=self.server_url,
                    username=self.admin_user,
                    password=self.admin_password,
                    realm_name="master",
                    verify=True,
                )
                admin.get_realm("master")
                logger.info("Successfully connected to Keycloak.")
                return True
            except Exception as e:
                logger.warning(
                    "Keycloak connection attempt %d/%d failed: %s",
                    i + 1, max_retries, e
                )
                time.sleep(delay)
        logger.error("Could not establish connection to Keycloak.")
        return False

    def get_admin_client(
        self,
        realm_name: str = "master",
        access_token: str = None,
    ) -> KeycloakAdmin:
        """Get a KeycloakAdmin instance, optionally using an existing access token."""
        try:
            if access_token:
                return KeycloakAdmin(
                    server_url=self.server_url,
                    access_token=access_token,
                    realm_name=realm_name,
                    verify=True,
                )
            return KeycloakAdmin(
                server_url=self.server_url,
                username=self.admin_user,
                password=self.admin_password,
                realm_name=realm_name,
                verify=True,
            )
        except Exception as e:
            logger.error("Failed to initialise KeycloakAdmin: %s", e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to connect to Keycloak: {str(e)}",
            )

    def get_openid_client(
        self,
        realm_name: str,
        client_id: str = "fastapi-client",
    ) -> KeycloakOpenID:
        """Get a KeycloakOpenID instance for authentication and tokens."""
        return KeycloakOpenID(
            server_url=self.server_url,
            client_id=client_id,
            realm_name=realm_name,
        )

    def create_realm(self, realm_name: str, access_token: str) -> Dict[str, Any]:
        """Create a new realm and initialise a default fastapi-client inside it."""
        admin = self.get_admin_client(realm_name="master", access_token=access_token)
        try:
            admin.create_realm(
                payload={
                    "id": realm_name,
                    "realm": realm_name,
                    "enabled": True,
                    "displayName": f"{realm_name.capitalize()} Realm",
                },
                skip_exists=False,
            )
            logger.info("Realm '%s' created.", realm_name)

            target_admin = self.get_admin_client(realm_name=realm_name, access_token=access_token)
            client_id = "fastapi-client"
            target_admin.create_client(
                payload={
                    "clientId": client_id,
                    "name": "FastAPI client application",
                    "enabled": True,
                    "publicClient": True,
                    "directAccessGrantsEnabled": True,
                    "standardFlowEnabled": True,
                    "redirectUris": ["*"],
                    "webOrigins": ["*"],
                },
                skip_exists=True,
            )
            logger.info("Default client '%s' created in realm '%s'.", client_id, realm_name)
            return {"realm": realm_name, "status": "created", "default_client": client_id}

        except KeycloakPostError as e:
            detail = e.error_message
            if isinstance(detail, bytes):
                detail = detail.decode("utf-8")
            raise HTTPException(status_code=e.response_code, detail=f"Keycloak error: {detail}")
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    def create_user(
        self,
        realm_name: str,
        username: str,
        email: str,
        password: str,
        role: str,
        access_token: str,
    ) -> Dict[str, Any]:
        """Create a user with password and assign the specified role."""
        admin = self.get_admin_client(realm_name=realm_name, access_token=access_token)
        try:
            user_id = admin.create_user(
                payload={
                    "username": username,
                    "email": email,
                    "enabled": True,
                    "emailVerified": True,
                },
                exist_ok=False,
            )
            admin.set_user_password(user_id=user_id, password=password, temporary=False)

            assigned_roles = []
            if role == "realm-admin":
                client_uuid = admin.get_client_id("realm-management")
                if client_uuid:
                    role_repr = admin.get_client_role(client_id=client_uuid, role_name="realm-admin")
                    admin.assign_client_role(user_id=user_id, client_id=client_uuid, roles=[role_repr])
                    assigned_roles.append("realm-management/realm-admin")
            elif role == "admin":
                try:
                    role_repr = admin.get_realm_role(role_name="admin")
                except KeycloakGetError:
                    admin.create_realm_role(payload={"name": "admin"})
                    role_repr = admin.get_realm_role(role_name="admin")
                admin.assign_realm_roles(user_id=user_id, roles=[role_repr])
                assigned_roles.append("realm/admin")
            else:
                try:
                    role_repr = admin.get_realm_role(role_name="user")
                except KeycloakGetError:
                    admin.create_realm_role(payload={"name": "user"})
                    role_repr = admin.get_realm_role(role_name="user")
                admin.assign_realm_roles(user_id=user_id, roles=[role_repr])
                assigned_roles.append("realm/user")

            return {
                "user_id": user_id,
                "username": username,
                "email": email,
                "role": role,
                "assigned_roles": assigned_roles,
                "status": "created",
            }
        except KeycloakPostError as e:
            detail = e.error_message
            if isinstance(detail, bytes):
                detail = detail.decode("utf-8")
            raise HTTPException(status_code=e.response_code, detail=f"Keycloak error: {detail}")
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    def get_tokens(
        self,
        realm_name: str,
        username: str,
        password: str,
        client_id: str,
    ) -> Dict[str, Any]:
        """Authenticate user and return OIDC token payload."""
        client = self.get_openid_client(realm_name=realm_name, client_id=client_id)
        try:
            return client.token(username=username, password=password)
        except KeycloakError as e:
            detail = e.error_message
            if isinstance(detail, bytes):
                detail = detail.decode("utf-8")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Authentication failed: {detail}",
            )

    def refresh_tokens(
        self,
        realm_name: str,
        refresh_token: str,
        client_id: str,
    ) -> Dict[str, Any]:
        """Refresh access token using a valid refresh token."""
        client = self.get_openid_client(realm_name=realm_name, client_id=client_id)
        try:
            return client.refresh_token(refresh_token=refresh_token)
        except KeycloakError as e:
            detail = e.error_message
            if isinstance(detail, bytes):
                detail = detail.decode("utf-8")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Token refresh failed: {detail}",
            )

    def decode_token(self, realm_name: str, token: str) -> Dict[str, Any]:
        """Decode and verify an OIDC access token."""
        client_id = "fastapi-client" if realm_name != "master" else "admin-cli"
        client = self.get_openid_client(realm_name=realm_name, client_id=client_id)
        try:
            public_key = client.public_key()
            pem = f"-----BEGIN PUBLIC KEY-----\n{public_key}\n-----END PUBLIC KEY-----"
            options = {"verify_signature": True, "verify_aud": False, "verify_exp": True}
            if not settings.VERIFY_ISSUER:
                options["verify_iss"] = False
            return client.decode_token(token, key=pem, options=options)
        except KeycloakError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired access token",
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Token validation failed: {str(e)}",
            )

    @staticmethod
    def is_realm_admin(decoded_token: Dict[str, Any]) -> bool:
        resource_access = decoded_token.get("resource_access", {})
        roles = resource_access.get("realm-management", {}).get("roles", [])
        realm_roles = decoded_token.get("realm_access", {}).get("roles", [])
        return "realm-admin" in roles or "admin" in realm_roles

    @staticmethod
    def is_global_admin(decoded_token: Dict[str, Any]) -> bool:
        iss = decoded_token.get("iss", "")
        realm_roles = decoded_token.get("realm_access", {}).get("roles", [])
        return "/realms/master" in iss and "admin" in realm_roles


keycloak_service = KeycloakService()
