"""
llm-service app.services.context_builder — RequestContext → context_block string.

ContextBuilder converts a RequestContext (from the request payload) into a
single formatted string that is prepended to the current user message before
the LLM call. This string is NEVER stored in Redis — it is purely ephemeral.

Output format uses XML-style tags to give the model clear structural cues:

    <user_profile>
      Name: Alice
      Role: analyst
    </user_profile>

    <retrieved_documents>
    [1] (source: report.pdf)
    The quarterly revenue increased by 12%...
    </retrieved_documents>

    <tool_results>
    Tool: web_search
    Result: Latest news about...
    </tool_results>

    <additional_context>
    The user is asking in the context of a board meeting tomorrow.
    </additional_context>

If none of the context fields are populated, build() returns None and no
context block is injected into the LLM call.
"""
from __future__ import annotations

import logging

from app.schemas.chat import RequestContext

logger = logging.getLogger(__name__)


class ContextBuilder:
    """
    Renders a RequestContext into a formatted string for LLM injection.

    All sections are independently optional. Sections are rendered in a
    consistent order: user_metadata → rag_chunks → tool_results → free_text.
    Returns None if the context is completely empty (no injection needed).
    """

    def build(self, ctx: RequestContext) -> str | None:
        """
        Build the context block string from a RequestContext.

        Args:
            ctx: The RequestContext from the current ChatRequest.

        Returns:
            A formatted multi-section string, or None if ctx is empty.
        """
        parts: list[str] = []

        # ── 1. User metadata ──────────────────────────────────────────────────
        if ctx.user_metadata:
            meta = ctx.user_metadata
            has_content = meta.name or meta.role or meta.preferences
            if has_content:
                lines = ["<user_profile>"]
                if meta.name:
                    lines.append(f"  Name: {meta.name}")
                if meta.role:
                    lines.append(f"  Role: {meta.role}")
                for key, val in meta.preferences.items():
                    lines.append(f"  {key}: {val}")
                lines.append("</user_profile>")
                parts.append("\n".join(lines))

        # ── 2. RAG chunks ─────────────────────────────────────────────────────
        if ctx.rag_chunks:
            lines = ["<retrieved_documents>"]
            for i, chunk in enumerate(ctx.rag_chunks, start=1):
                source_tag = f" (source: {chunk.source})" if chunk.source else ""
                score_tag = f" [score: {chunk.score:.3f}]" if chunk.score is not None else ""
                lines.append(f"[{i}]{source_tag}{score_tag}")
                lines.append(chunk.content)
            lines.append("</retrieved_documents>")
            parts.append("\n".join(lines))

        # ── 3. Tool results ───────────────────────────────────────────────────
        if ctx.tool_results:
            lines = ["<tool_results>"]
            for tr in ctx.tool_results:
                lines.append(f"Tool: {tr.tool_name}")
                lines.append(f"Result: {tr.result}")
            lines.append("</tool_results>")
            parts.append("\n".join(lines))

        # ── 4. Free-form text ─────────────────────────────────────────────────
        if ctx.free_text and ctx.free_text.strip():
            parts.append(
                f"<additional_context>\n{ctx.free_text.strip()}\n</additional_context>"
            )

        if not parts:
            return None

        context_block = "\n\n".join(parts)
        logger.debug(
            "ContextBuilder: built context block with %d section(s), %d chars.",
            len(parts),
            len(context_block),
        )
        return context_block
