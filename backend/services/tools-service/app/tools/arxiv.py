import logging
from typing import Any
from langchain_core.tools import BaseTool
from app.schemas.tool_schema import ToolDefinition

logger = logging.getLogger(__name__)


class ArxivSearchTool(BaseTool):
    """Clean in-process ArXiv search tool wrapper using modern arxiv.Client()."""

    name: str = "arxiv_search"
    description: str = "Search ArXiv for academic papers and preprints."

    def _run(self, query: str) -> str:
        try:
            import arxiv
            client = arxiv.Client()
            search = arxiv.Search(query=query, max_results=3)
            results = list(client.results(search))
            if not results:
                return "No ArXiv papers found for query."
            snippets = []
            for r in results:
                authors = ", ".join(a.name for a in r.authors[:3])
                snippets.append(
                    f"Title: {r.title}\nAuthors: {authors}\nURL: {r.pdf_url}\nSummary: {r.summary[:300]}..."
                )
            return "\n\n".join(snippets)
        except Exception as exc:
            logger.warning("ArXiv search error: %s", exc)
            return f"ArXiv search failed: {exc}"

    async def _arun(self, query: str) -> str:
        return self._run(query)


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
    langchain_tool=ArxivSearchTool(),
    max_output_bytes=1_048_576,
    timeout_seconds=30,
)
