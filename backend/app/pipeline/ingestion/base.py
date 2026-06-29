"""
app.pipeline.ingestion.base — Abstract PipelineStep base class.

All ingestion pipeline steps must implement this interface.
Steps are chained by the pipeline runner (ingest.py).

Usage:
    class MyStep(PipelineStep):
        async def run(self, context: dict) -> dict:
            # transform context and return updated dict
            return context
"""
from abc import ABC, abstractmethod
from typing import Any, Dict


class PipelineStep(ABC):
    """Abstract base class for a single pipeline processing step."""

    @property
    def name(self) -> str:
        """Human-readable step name for logging."""
        return self.__class__.__name__

    @abstractmethod
    async def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute this pipeline step.

        Args:
            context: Shared pipeline state dict passed between steps.

        Returns:
            Updated context dict for the next step.
        """
        ...
