"""
shared.database.adapters.vault — HashiCorp Vault adapter (hvac).

Manages hvac.Client authentication and token renewal, providing
a consistent lifecycle interface for the ServerManager.

Token resolution order:
  1. VAULT_TOKEN environment variable (explicit override)
  2. /vault/keys/root-token file written by the vault-init sidecar on startup

NOTE: Vault is treated as optional infrastructure. Connection failures are
logged as warnings and do NOT prevent the application from starting. Services
that require Vault should check `adapter.client` and handle None gracefully.

Usage:
    from shared.database.adapters.vault import VaultAdapter
    server_manager.register("vault", VaultAdapter())
"""
import logging

import hvac

from shared.config.settings import settings
from shared.database.base import DatabaseAdapter

logger = logging.getLogger(__name__)

# Path written by the vault-init sidecar (mounted via vault_keys volume)
_TOKEN_FILE = "/vault/keys/root-token"


def _resolve_token() -> str | None:
    """Return the Vault token from env var or the shared token file, or None."""
    token = settings.VAULT_TOKEN
    if token:
        return token
    try:
        with open(_TOKEN_FILE) as fh:
            token = fh.read().strip()
        if token:
            logger.debug("VaultAdapter: loaded token from %s", _TOKEN_FILE)
            return token
    except FileNotFoundError:
        pass
    return None


class VaultAdapter(DatabaseAdapter):
    """HashiCorp Vault adapter using hvac synchronous client (wrapped async).

    Connection failures are non-fatal — the adapter logs a warning and marks
    itself as unavailable. Individual features that need Vault should check
    `adapter.available` before using `adapter.client`.
    """

    def __init__(self) -> None:
        self._client: hvac.Client | None = None
        self.available: bool = False

    async def connect(self) -> None:
        """Attempt to connect to Vault. Logs a warning on failure — never raises."""
        token = _resolve_token()
        if not token:
            logger.warning(
                "VaultAdapter: no token found (VAULT_TOKEN env or %s). "
                "Vault will be unavailable — this is fine if Vault is not yet in use.",
                _TOKEN_FILE,
            )
            return

        try:
            client = hvac.Client(url=settings.VAULT_ADDR, token=token)

            if not client.is_authenticated():
                logger.warning(
                    "VaultAdapter: token rejected by %s. "
                    "Vault will be unavailable.",
                    settings.VAULT_ADDR,
                )
                return

            seal_status = client.sys.read_seal_status()
            if seal_status.get("sealed"):
                logger.warning(
                    "VaultAdapter: Vault at %s is sealed. "
                    "vault-init may still be running.",
                    settings.VAULT_ADDR,
                )
                return

            self._client = client
            self.available = True
            logger.info(
                "VaultAdapter: connected to %s (authenticated, unsealed).",
                settings.VAULT_ADDR,
            )

        except Exception as exc:
            logger.warning(
                "VaultAdapter: could not connect to %s — %s. "
                "Vault will be unavailable. This is expected if vault-init is still starting.",
                settings.VAULT_ADDR,
                exc,
            )

    async def disconnect(self) -> None:
        """Close the client session."""
        if self._client:
            self._client = None
            self.available = False
            logger.info("VaultAdapter: disconnected.")

    async def health_check(self) -> bool:
        """Returns True if Vault is reachable and unsealed; False otherwise (non-fatal)."""
        if not self._client:
            return False
        try:
            status = self._client.sys.read_seal_status()
            return not status.get("sealed", True)
        except Exception as exc:
            logger.debug("VaultAdapter: health check failed — %s", exc)
            return False

    @property
    def client(self) -> hvac.Client:
        """Expose the raw hvac.Client. Raises if not connected."""
        if not self._client:
            raise RuntimeError(
                "VaultAdapter not connected — Vault may be unavailable. "
                "Check `adapter.available` before calling `adapter.client`."
            )
        return self._client
