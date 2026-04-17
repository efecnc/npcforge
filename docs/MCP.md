# Using npcforge from an MCP client

The [Model Context Protocol](https://modelcontextprotocol.io) lets an
AI agent call external tools. npcforge ships an MCP server that
exposes [all five tools](TOOLS.md) over stdio. Once registered, your
agent can infer a world, propose a cast, review it with you, and run
the dialogue pipeline — all without leaving the chat.

## Install

```bash
pip install 'npcforge[mcp]'
```

This installs the MCP SDK alongside npcforge and registers the
`npcforge-mcp` console script. You can start it manually to verify the
install:

```bash
npcforge-mcp < /dev/null
# (stdio server waits for an MCP client; Ctrl-C to exit)
```

## Registering the server

### Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json`
(macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```jsonc
{
  "mcpServers": {
    "npcforge": {
      "command": "npcforge-mcp",
      "env": {
        "GEMINI_API_KEY": "your-key-here"
      }
    }
  }
}
```

Restart Claude Desktop. The npcforge tools appear in the tool picker
next to any MCP tool you already use.

### Cursor

Add to `~/.cursor/mcp.json` (or the per-project equivalent):

```jsonc
{
  "mcpServers": {
    "npcforge": {
      "command": "npcforge-mcp",
      "env": {
        "GEMINI_API_KEY": "your-key-here"
      }
    }
  }
}
```

### Cline / other MCP-capable clients

Same shape. Point the client at the `npcforge-mcp` binary and pass any
environment variables the relevant LLM provider needs.

### Using a specific Python interpreter

If `npcforge-mcp` is not on the agent's `PATH`, pin the interpreter:

```jsonc
{
  "mcpServers": {
    "npcforge": {
      "command": "/usr/local/bin/python3",
      "args": ["-m", "npcforge.mcp_server"],
      "env": { "GEMINI_API_KEY": "..." }
    }
  }
}
```

## API-key handling

The server reads provider API keys from the environment it was
launched in. When an agent omits `api_key` from a tool call, the
server fills it from the canonical env var for the chosen provider
(`GEMINI_API_KEY`, `OPENAI_API_KEY`, `DEEPSEEK_API_KEY`,
`OPENROUTER_API_KEY`, `LOCAL_API_KEY`). Agents therefore never have
to ship keys through prompts.

If an agent does pass `api_key` explicitly, that value wins.

## Example agent prompts

Once registered, talk to the agent the way you'd talk to a
collaborator:

> **"Read my lore in `/Users/me/Desktop/neon_harbor` and tell me what
> setting you think I'm writing. I'll confirm before we continue."**
>
> Agent calls `infer_world_profile` → shows the structured profile →
> waits for confirmation.

> **"Generate a cast of five NPCs for my tavern, one of whom is a
> retired navigator. Append them to characters.yaml."**
>
> Agent calls `gen_npcs` with `roles=[..., "retired navigator, ..."]`
> and append=True.

> **"Run the full dialogue and bark pipeline for Mira and Kess only."**
>
> Agent calls `build_pipeline` with
> `mode="all", only_npcs=["mira_vesser", "kess_the_knife"]`.

## Troubleshooting

**"Unknown command: npcforge-mcp"**
→ You installed the base package without the mcp extra. Run
`pip install 'npcforge[mcp]'`.

**"Missing API key"**
→ Agent omitted `api_key` and the env var for the chosen provider is
unset. Either set the env var in the MCP client config or have the
agent pass `api_key` explicitly.

**"additionalProperties is not supported in the Gemini API"**
→ Should not happen on 0.3.0+. If you see it, you are on an older
schema — upgrade.

**"Tool call timed out"**
→ The Gemini free tier is slow under load. Either wait a minute
between calls, switch to `--provider openai`, or use `--provider
local` pointing at a local vLLM / Ollama endpoint.

## Full tool list

See [`docs/TOOLS.md`](TOOLS.md). Every tool registered in
`TOOL_REGISTRY` is automatically exposed — adding new ones requires
no changes to the MCP server.
