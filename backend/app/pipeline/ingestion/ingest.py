"""
app.pipeline.ingestion.ingest — Pipeline runner.

Chains pipeline steps sequentially and executes them with a shared context.
Logs each step's execution and elapsed time for observability.

Usage:
    from app.pipeline.ingestion.ingest import IngestionPipeline
    from app.pipeline.ingestion.steps import ValidateInputStep, PreprocessStep

    pipeline = IngestionPipeline(steps=[ValidateInputStep(), PreprocessStep()])
    result = await pipeline.run({"raw_data": "..."})
"""
import logging
import time
from typing import Any, Dict, List

from app.pipeline.ingestion.base import PipelineStep

logger = logging.getLogger(__name__)


class IngestionPipeline:
    """
    Executes a list of PipelineSteps sequentially, passing context between them.

    Args:
        steps: Ordered list of PipelineStep instances to run.
    """

    def __init__(self, steps: List[PipelineStep]) -> None:
        self.steps = steps

    async def run(self, initial_context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Run all steps in order.

        Args:
            initial_context: Starting context dict for the pipeline.

        Returns:
            Final context dict after all steps have run.
        """
        context = initial_context.copy()
        logger.info("Pipeline starting with %d step(s).", len(self.steps))

        for step in self.steps:
            step_start = time.monotonic()
            logger.info("Running step: %s", step.name)
            context = await step.run(context)
            elapsed = (time.monotonic() - step_start) * 1000
            logger.info("Step '%s' completed in %.1fms.", step.name, elapsed)

        logger.info("Pipeline completed successfully.")
        return context
