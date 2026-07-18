"""
app.tools.wikipedia — Wikipedia lookup system tool.

Platform-authored, installed at build time, executed in-process.
"""
from langchain_community.tools import WikipediaQueryRun
from langchain_community.utilities import WikipediaAPIWrapper

from app.schemas.tool_schema import ToolDefinition

tool = ToolDefinition(
    name="wikipedia",
    version="1.0.0",
    display_name="Wikipedia",
    description=(
        "Query Wikipedia for encyclopedic information. Returns article summaries "
        "for the given search term. Best for well-established topics, historical "
        "facts, and general knowledge."
    ),
    capabilities=["knowledge_lookup", "encyclopedia", "research"],
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The topic to search for on Wikipedia.",
            }
        },
        "required": ["query"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "result": {
                "type": "string",
                "description": "Wikipedia article summary text.",
            }
        },
    },
    usage_examples=[
        {"input": {"query": "Transformer neural network"}, "description": "Look up transformer architecture"},
        {"input": {"query": "Python programming language"}, "description": "Get Wikipedia summary of Python"},
    ],
    langchain_tool=WikipediaQueryRun(api_wrapper=WikipediaAPIWrapper()),
    max_output_bytes=1_048_576,
    timeout_seconds=30,
)
