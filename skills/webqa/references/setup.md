# Setup

Use this reference when WebQA MCP tools are unavailable, authentication fails because the server is not configured, or the user asks how to configure WebQA.

## Install

Install WebQA so the `webqa-mcp-server` command is available:

```bash
git clone https://github.com/MigoXLab/webqa-agent.git
cd webqa-agent
pip install -e .
which webqa-mcp-server
```

Use the absolute path from `which webqa-mcp-server` in IDE configuration.

## API Key

Create an API key in the WebQA platform, then configure it as `WEBQA_API_KEY`.

Required environment variables:

- `WEBQA_API_URL`: WebQA platform URL.
- `WEBQA_API_KEY`: WebQA API key.

Optional:

- `WEBQA_DEFAULT_MODEL`: default model override.

## Claude Code

Configure `.claude/settings.json`:

```json
{
  "mcpServers": {
    "webqa": {
      "command": "/absolute/path/to/webqa-mcp-server",
      "env": {
        "WEBQA_API_URL": "https://your-webqa-platform.com",
        "WEBQA_API_KEY": "wqa_xxxxxxxx..."
      }
    }
  }
}
```

## Cursor

In Cursor settings, add an MCP server:

```json
{
  "mcpServers": {
    "webqa": {
      "command": "/absolute/path/to/webqa-mcp-server",
      "env": {
        "WEBQA_API_URL": "https://your-webqa-platform.com",
        "WEBQA_API_KEY": "wqa_xxxxxxxx..."
      }
    }
  }
}
```

## Streamable HTTP

For remote-agent setups, WebQA also supports Streamable HTTP:

```bash
webqa-mcp-server --transport streamable-http --port 8080
```

Use STDIO for normal IDE integration unless the user explicitly needs HTTP transport.
