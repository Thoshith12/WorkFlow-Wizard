"""
shared.database.adapters.vault — HashiCorp Vault adapter (hvac).

Manages hvac.Client authentication and token renewal, providing
a consistent lifecycle interface for the ServerManager.

Usage:
    from shared.database.adapters.vault import VaultAdapter
    server_manager.register("vault", VaultAdapter())
"""
import logging

from shared.database.base import DatabaseAdapter

logger = logging.getLogger(__name__)


class VaultAdapter(DatabaseAdapter):
    """HashiCorp Vault adapter using hvac synchronous client (wrapped async)."""

    def __init__(self) -> None:
        self._client = None

    async def connect(self) -> None:
        """Initialise hvac client, authenticate, and verify Vault is unsealed."""
        # TODO: Implement using hvac.Client(url=settings.VAULT_ADDR, token=settings.VAULT_TOKEN)
        logger.info("VaultAdapter: connecting...")

    async def disconnect(self) -> None:
        """Revoke the Vault token and close the client session."""
        if self._client:
            # TODO: self._client.auth.token.revoke_self()
            logger.info("VaultAdapter: disconnected.")

    async def health_check(self) -> bool:
        """Check Vault seal status and reachability."""
        # TODO: Implement using self._client.sys.read_health_status()
        return True

    @property
    def client(self):
        """Expose the raw hvac.Client for secret read/write operations."""
        if not self._client:
            raise RuntimeError("VaultAdapter not connected — call connect() first.")
        return self._client
