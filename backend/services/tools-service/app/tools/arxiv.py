"""
app.tools.arxiv — ArXiv academic paper search system tool.

Platform-authored, installed at build time, executed in-process.
"""
from langchain_community.tools import ArxivQueryRun
from langchain_community.utilities import ArxivAPIWrapper

from app.schemas.tool_schema import ToolDefinition

tool = ToolDefinition(
    name="arxiv",
    version="1.0.0",
    display_name="ArXiv Search",
    description=(
        "Search ArXiv for academic papers and preprints. Returns paper titles, "
        "authors, and summaries. Best for scientific research, ML papers, and "
        "technical publications."
    ),
    capabilities=["academic_search", "research_papers", "scientific_literature"],
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query for ArXiv papers.",
            }
        },
        "required": ["query"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "result": {
                "type": "string",
                "description": "Matching paper titles, authors, and abstracts.",
            }
        },
    },
    usage_examples=[
        {"input": {"query": "attention is all you need"}, "description": "Find the original Transformer paper"},
        {"input": {"query": "graph neural networks survey"}, "description": "Search for GNN survey papers"},
    ],
    langchain_tool=ArxivQueryRun(api_wrapper=ArxivAPIWrapper()),
    max_output_bytes=1_048_576,
    timeout_seconds=30,
)
