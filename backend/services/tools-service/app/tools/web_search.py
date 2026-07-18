"""
app.tools.web_search — DuckDuckGo web search system tool.

Platform-authored, installed at build time, executed in-process.
Uses duckduckgo_search DDGS directly with graceful error handling.
"""
from __future__ import annotations

import logging
from typing import Any, Dict
from langchain_core.tools import BaseTool

from app.schemas.tool_schema import ToolDefinition

logger = logging.getLogger(__name__)


class DuckDuckGoSearchTool(BaseTool):
    """Clean in-process DuckDuckGo search tool wrapper."""

    name: str = "duckduckgo_search"
    description: str = "Search the web using DuckDuckGo."

    def _run(self, query: str) -> str:
        try:
            from duckduckgo_search import DDGS
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=5))
                if not results:
                    return "No results found for query."
                snippets = []
                for r in results:
                    title = r.get("title", "")
                    body = r.get("body", "")
                    href = r.get("href", "")
                    snippets.append(f"Title: {title}\nURL: {href}\nSnippet: {body}")
                return "\n\n".join(snippets)
        except Exception as exc:
            logger.warning("DuckDuckGo search error: %s", exc)
            return f"Search failed: {exc}"

    async def _arun(self, query: str) -> str:
        return self._run(query)


tool = ToolDefinition(
    name="web_search",
    version="1.0.0",
    display_name="Web Search",
    description=(
        "Search the web using DuckDuckGo. Returns text results for the given query. "
        "Useful for current events, factual lookups, and general knowledge questions."
    ),
    capabilities=["web_search", "current_events", "fact_checking"],
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query to look up on the web.",
            }
        },
        "required": ["query"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "result": {
                "type": "string",
                "description": "Search results as concatenated text snippets.",
            }
        },
    },
    usage_examples=[
        {"input": {"query": "latest AI news 2026"}, "description": "Search for recent AI news"},
        {"input": {"query": "Python 3.13 new features"}, "description": "Look up Python release notes"},
    ],
    langchain_tool=DuckDuckGoSearchTool(),
    max_output_bytes=1_048_576,
    timeout_seconds=30,
)
