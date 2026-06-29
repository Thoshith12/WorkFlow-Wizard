"""
app.pipeline.ingestion.steps — Concrete pipeline step implementations.

Add new ingestion steps here as concrete PipelineStep subclasses.
Each step receives a context dict, transforms it, and returns it.
"""
from typing import Any, Dict

from app.pipeline.ingestion.base import PipelineStep


class ValidateInputStep(PipelineStep):
    """Validates that required fields are present in the ingestion context."""

    async def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        # TODO: Implement input validation logic
        return context


class PreprocessStep(PipelineStep):
    """Preprocesses raw input data (cleaning, normalisation)."""

    async def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        # TODO: Implement preprocessing logic
        return context


class EmbedStep(PipelineStep):
    """Generates vector embeddings for preprocessed content."""

    async def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        # TODO: Implement embedding via embedding model
        return context


class StoreStep(PipelineStep):
    """Stores embedded vectors into the vector store (Qdrant)."""

    async def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        # TODO: Implement Qdrant upsert logic
        return context
