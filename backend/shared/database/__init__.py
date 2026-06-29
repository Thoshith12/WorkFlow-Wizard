"""
shared.database — Database adapter pattern & ServerManager.

Exports:
    DatabaseAdapter  — Abstract base class for all DB adapters
    ServerManager    — Central registry that manages adapter lifecycles
    server_manager   — Singleton ServerManager instance
"""
from shared.database.base import DatabaseAdapter
from shared.database.server_manager import ServerManager, server_manager

__all__ = ["DatabaseAdapter", "ServerManager", "server_manager"]
