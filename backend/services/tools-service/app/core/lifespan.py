import asyncio
import logging
from typing import Optional

from shared.database import server_manager
from shared.database.adapters import (
    PostgresAdapter,
    RedisAdapter,
)
from app.config.tool_settings import tool_settings

logger = logging.getLogger(__name__)


class LifespanHandler:
    """Wires up adapters, loads tool registry, and manages background tasks."""

    def __init__(self) -> None:
        self._registered = False
        self._reaper_task: Optional[asyncio.Task] = None

    def _register_adapters(self) -> None:
        """Register infrastructure adapters required by the Tools service."""
        if self._registered:
            return

        server_manager.register("postgres", PostgresAdapter())
        server_manager.register("redis", RedisAdapter())

        self._registered = True
        logger.info("Tools service: all adapters registered with ServerManager.")

    async def _run_reaper_loop(self) -> None:
        """Periodic background task to reap idle gVisor containers."""
        interval = tool_settings.sandbox.reaper_interval_seconds
        idle_timeout = tool_settings.sandbox.idle_timeout_seconds
        logger.info(
            "Sandbox reaper background task started (interval: %ds, idle_timeout: %ds).",
            interval, idle_timeout,
        )
        from app.sandbox.pool import sandbox_pool
        try:
            while True:
                await asyncio.sleep(interval)
                try:
                    await sandbox_pool.reap_idle()
                except asyncio.CancelledError:
                    raise  # let outer handler cancel cleanly
                except Exception:
                    # Log and continue — a transient Redis blip or runsc failure
                    # must not silently kill the reaper loop, which would cause
                    # idle containers to accumulate forever.
                    logger.exception("reap_idle failed — will retry next interval")
        except asyncio.CancelledError:
            logger.info("Sandbox reaper task cancelled.")

    async def startup(self) -> None:
        """Called on FastAPI startup — connect all adapters, load tools, start reaper."""
        logger.info("Tools service starting up...")
        self._register_adapters()
        await server_manager.startup()

        # Load system tools and custom tools from DB into in-memory registry
        try:
            from app.services.registry import tool_registry
            await tool_registry.load_all()
        except Exception as exc:
            logger.error("Failed to load tool registry on startup: %s", exc)
            raise

        # Start in-process background reaper loop
        self._reaper_task = asyncio.create_task(self._run_reaper_loop())

        logger.info("Tools service startup complete.")

    async def shutdown(self) -> None:
        """Called on FastAPI shutdown — cancel reaper and disconnect adapters."""
        logger.info("Tools service shutting down...")
        if self._reaper_task:
            self._reaper_task.cancel()
            try:
                await self._reaper_task
            except asyncio.CancelledError:
                pass

        try:
            from app.sandbox.pool import sandbox_pool
            await sandbox_pool.shutdown()
        except Exception as exc:
            logger.warning("Failed to shutdown sandbox pool: %s", exc)

        await server_manager.shutdown()
        logger.info("Tools service shutdown complete.")


lifespan_handler = LifespanHandler()

