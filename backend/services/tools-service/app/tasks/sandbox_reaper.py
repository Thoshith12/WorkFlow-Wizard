"""
app.tasks.sandbox_reaper — Celery Beat task to reap idle sandbox containers.

Runs periodically (default: every 60s). Checks all registered containers
and stops any that have been idle longer than idle_timeout_seconds (5 min).

Idle timeout is the ONLY container lifecycle driver for warm containers.
There is NO per-request CPU timeout that kills the container.
"""
import asyncio
import logging

from app.core.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.sandbox_reaper.reap_idle_containers")
def reap_idle_containers() -> dict:
    """
    Reap idle sandbox containers.

    This is a Celery task (synchronous entry point) that runs the
    async reap_idle method on the SandboxPool.
    """
    try:
        from app.sandbox.pool import sandbox_pool
        loop = asyncio.new_event_loop()
        try:
            reaped = loop.run_until_complete(sandbox_pool.reap_idle())
        finally:
            loop.close()

        logger.info("Sandbox reaper completed: %d containers reaped.", reaped)
        return {"reaped": reaped}
    except Exception as exc:
        logger.error("Sandbox reaper failed: %s", exc)
        return {"error": str(exc)}
