"""app.pipeline — RAG processing and ingestion pipelines."""
from app.pipeline.ingestion import run_ingestion_pipeline
from app.pipeline.extraction import run_extraction_pipeline
from app.pipeline.preprocessing import run_preprocessing_pipeline

__all__ = ["run_ingestion_pipeline", "run_extraction_pipeline", "run_preprocessing_pipeline"]

