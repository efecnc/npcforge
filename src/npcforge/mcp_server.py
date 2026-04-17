"""MCP server for npcforge.

Thin wrapper around :mod:`npcforge.tools` that exposes every registered
tool over the Model Context Protocol (stdio transport). A client agent
(Claude Desktop, Cursor, Cline, etc.) can mount this server and invoke
npcforge tools directly inside its agent loop.

The server does not define any features itself: it loads ``TOOL_REGISTRY``,
converts each entry into an MCP ``Tool`` declaration, and dispatches
``tools/call`` into the matching async function.

Install the dep and register with your agent config:

    pip install 'npcforge[mcp]'

    # Claude Desktop / Cursor example (mcp_config.json)
    {
      "mcpServers": {
        "npcforge": {
          "command": "npcforge-mcp",
          "env": {"GEMINI_API_KEY": "..."}
        }
      }
    }

The server reads API keys from the environment each time a tool is called;
callers may also pass ``api_key`` as a tool argument.
"""

from __future__ import annotations

import json
import os
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool
from pydantic import BaseModel, ValidationError

from .tools import TOOL_REGISTRY


_DEFAULT_ENV = {
    "gemini": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "local": "LOCAL_API_KEY",
}


def _resolve_env_api_key(provider: str) -> str | None:
    """Look up the provider's canonical env var. Returns ``None`` if unset."""
    env_name = _DEFAULT_ENV.get(provider, "GEMINI_API_KEY")
    return os.environ.get(env_name)


def _inject_api_key(arguments: dict[str, Any], input_schema: dict[str, Any]) -> dict[str, Any]:
    """When a tool expects ``api_key`` but the caller omitted it, fill from env.

    Lets MCP clients avoid shipping secrets through prompts: the server reads
    the environment the agent launched it in. If the env var is missing, we
    leave the argument absent and let Pydantic raise the validation error.
    """
    props = input_schema.get("properties", {})
    if "api_key" not in props or "api_key" in arguments:
        return arguments
    provider = arguments.get("provider", "gemini")
    key = _resolve_env_api_key(provider)
    if key is None:
        return arguments
    return {**arguments, "api_key": key}


def build_server() -> Server:
    """Construct an MCP ``Server`` with every registered tool wired up."""
    server = Server("npcforge")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        tools: list[Tool] = []
        for name, (_, input_model, _output_model, description) in TOOL_REGISTRY.items():
            tools.append(
                Tool(
                    name=name,
                    description=description.strip(),
                    inputSchema=input_model.model_json_schema(),
                )
            )
        return tools

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        entry = TOOL_REGISTRY.get(name)
        if entry is None:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]
        tool_fn, input_model, _output_model, _description = entry

        enriched = _inject_api_key(arguments, input_model.model_json_schema())

        try:
            input_instance = input_model(**enriched)
        except ValidationError as exc:
            return [
                TextContent(
                    type="text",
                    text=f"Invalid arguments for {name}:\n{exc.json(indent=2)}",
                )
            ]

        try:
            result: BaseModel = await tool_fn(input_instance)
        except Exception as exc:  # surface at the protocol boundary
            return [
                TextContent(
                    type="text",
                    text=f"Tool {name} raised: {type(exc).__name__}: {exc}",
                )
            ]

        # Pydantic models are JSON-serialisable via model_dump_json. Path
        # fields become strings, which MCP clients can read directly.
        payload = result.model_dump_json(indent=2)
        return [TextContent(type="text", text=payload)]

    return server


async def run_stdio() -> None:
    """Run the MCP server over stdio until the client disconnects."""
    server = build_server()
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main() -> None:
    """Entry point for the ``npcforge-mcp`` console script."""
    import asyncio

    asyncio.run(run_stdio())


def describe_tools() -> str:
    """Return a human-readable summary — useful for debugging mount issues."""
    lines = ["npcforge MCP tools:"]
    for name, (_, _input_model, _output_model, description) in TOOL_REGISTRY.items():
        first_line = description.strip().split("\n")[0]
        lines.append(f"  - {name}: {first_line}")
    return "\n".join(lines)


if __name__ == "__main__":
    main()


# Exported for ``json.dumps`` debugging / MCP Inspector UIs.
def tools_json() -> str:
    """Dump the tool list as pretty JSON for inspection."""
    specs = []
    for name, (_, input_model, output_model, description) in TOOL_REGISTRY.items():
        specs.append(
            {
                "name": name,
                "description": description.strip(),
                "inputSchema": input_model.model_json_schema(),
                "outputSchema": output_model.model_json_schema(),
            }
        )
    return json.dumps(specs, indent=2)
