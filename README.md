[![CI](https://github.com/julianoczkowski/notebooklm-mcp-2026/actions/workflows/ci.yml/badge.svg)](https://github.com/julianoczkowski/notebooklm-mcp-2026/actions/workflows/ci.yml)
[![MCP Server](https://img.shields.io/badge/MCP-server-7c3aed)](https://modelcontextprotocol.io)
[![Google NotebookLM](https://img.shields.io/badge/Google-NotebookLM-4285F4)](https://notebooklm.google.com)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-3776AB?logo=python&logoColor=white)](https://python.org)
[![FastMCP](https://img.shields.io/badge/built_with-FastMCP-ff6600)](https://github.com/jlowin/fastmcp)
[![PyPI](https://img.shields.io/pypi/v/notebooklm-mcp-faxtom)](https://pypi.org/project/notebooklm-mcp-faxtom/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Buy Me A Coffee](https://img.shields.io/badge/Buy_Me_A_Coffee-FFDD00?logo=buy-me-a-coffee&logoColor=black)](https://buymeacoffee.com/julianoczkowski)
[![Ko-fi](https://img.shields.io/badge/Ko--fi-FF5E5B?logo=ko-fi&logoColor=white)](https://ko-fi.com/julianoczkowski)

<img src="notebooklm_mcp_hero.png" alt="NotebookLM MCP" width="100%">

# notebooklm-mcp-2026

Secure MCP server for querying Google NotebookLM notebooks. Designed for use with Claude Code, Cursor, VS Code Copilot, and any MCP-compatible AI assistant.

> **Fork enhancements** — This fork improves on [julianoczkowski/notebooklm-mcp-2026](https://github.com/julianoczkowski/notebooklm-mcp-2026) with multi-browser auth (including [Helium](https://github.com/imputnet/helium)), automatic session refresh, and a single `login` command that verifies your account and configures MCP clients.

**Watch on YouTube:** [https://youtu.be/xdI3uEA5rew?si=FkD0sdCZSFFWpjhy](https://youtu.be/xdI3uEA5rew?si=FkD0sdCZSFFWpjhy)

<p align="left">
  <a href="https://youtu.be/xdI3uEA5rew?si=FkD0sdCZSFFWpjhy">
    <img src="https://img.youtube.com/vi/xdI3uEA5rew/maxresdefault.jpg" alt="Watch the video" width="100%">
  </a>
</p>

## What it does

notebooklm-mcp-2026 gives AI assistants direct access to your Google NotebookLM notebooks. It runs as a local subprocess (stdio transport) — no HTTP server needed. Your AI assistant can list your notebooks, read source content, and ask the NotebookLM AI questions about your sources.

<p align="center">
  <img src="flow_animation.gif" alt="NotebookLM MCP Flow" width="100%">
</p>

## Quick Start

**One command** to log in, verify your account, and configure Cursor / Claude Code / VS Code. Works on macOS, Linux, and Windows.

### Step 1: Install

**From this fork (recommended):**

```bash
git clone https://github.com/Faxtom/notebooklm-mcp-2026.git
cd notebooklm-mcp-2026
pip install -e .
```

**Or with uv (upstream package):**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv tool install notebooklm-mcp-faxtom
```

**Windows (PowerShell):**

```powershell
cd notebooklm-mcp-2026
python -m pip install -e .
```

### Step 2: Log in (auth + verify + MCP setup)

```bash
notebooklm-mcp-2026 login --browser helium --method browser
```

This single command:

1. Tries to import cookies from your browser (Helium, Chrome, Edge, Brave, Firefox, …)
2. If no valid session is found, **opens the browser** so you can log in to [notebooklm.google.com](https://notebooklm.google.com)
3. **Verifies** your account against the real NotebookLM API
4. **Auto-configures** all detected MCP clients (Cursor, Claude Code, VS Code, …)

> **Using [Helium](https://github.com/imputnet/helium)?** That's the recommended browser in this fork. Your normal Helium window can stay open — the interactive login uses an isolated profile.

> **Don't want auto-setup?** Add `--skip-setup` to only authenticate.

### Step 3: Use it

Restart your MCP client and ask your AI assistant:

> "List my NotebookLM notebooks"

That's it! You do **not** need to run `setup` separately after `login`.

## Requirements

- **A Chromium-based browser** — Chrome, Edge, Brave, [Helium](https://github.com/imputnet/helium), Chromium, Opera, or Vivaldi (for interactive login)
- **Or Firefox / LibreWolf / Safari** — cookie import only (no interactive login window)
- **Python 3.11+**

### Don't have a browser?

- **Helium (recommended):** [helium.computer](https://helium.computer) · [GitHub](https://github.com/imputnet/helium)
- **Chrome:** [google.com/chrome](https://www.google.com/chrome/)
- On Linux, `chromium` or the Helium `.deb` / AppImage also work

### Don't have Python?

If you used `uv` to install (recommended), you don't need to install Python separately — `uv` handles it for you.

If you prefer to install Python manually:

| Platform        | Command                                                                                |
| --------------- | -------------------------------------------------------------------------------------- |
| macOS           | `brew install python`                                                                  |
| Ubuntu / Debian | `sudo apt install python3`                                                             |
| Arch / Manjaro  | `sudo pacman -S python`                                                                |
| Fedora          | `sudo dnf install python3`                                                             |
| Windows         | Download from [python.org](https://python.org) — tick **"Add to PATH"** during install |

## Alternative Install Methods

Other install options:

```bash
# pipx (if you already have it)
pipx install notebooklm-mcp-faxtom

# pip (inside a virtual environment)
python -m venv .venv && source .venv/bin/activate
pip install notebooklm-mcp-faxtom

# From source
git clone https://github.com/Faxtom/notebooklm-mcp-2026.git
cd notebooklm-mcp-2026
pip install -e .
```

## Authentication

notebooklm-mcp-2026 uses Google session cookies. No passwords are stored — only session cookies, a CSRF token, and a session ID.

### Supported browsers

| Browser | Import cookies (`--method browser`) | Interactive login (`--method cdp`) |
| ------- | --------------------------------- | ---------------------------------- |
| **Helium** | ✅ | ✅ |
| Chrome | ✅ | ✅ |
| Edge | ✅ | ✅ |
| Brave | ✅ | ✅ |
| Chromium / Playwright | ✅ | ✅ |
| Opera / Vivaldi | ✅ | ✅ |
| Firefox / LibreWolf | ✅ | ❌ |
| Safari (macOS) | ✅ | ❌ |

### Login methods

| Method | What it does |
| ------ | ------------ |
| `auto` (default) | Try browser import → silent profile refresh → interactive CDP |
| `browser` | Import cookies; **opens the browser automatically** if no valid session |
| `cdp` | Open browser window for manual Google login |
| `profile` | Silent refresh from saved isolated browser profile |
| `import` | Load cookies from a JSON file |

### Examples

```bash
# Recommended — Helium: import or open browser, then verify + configure MCP
notebooklm-mcp-2026 login --browser helium --method browser

# Auto-detect any installed browser
notebooklm-mcp-2026 login

# Interactive login with a specific browser
notebooklm-mcp-2026 login --browser edge --method cdp

# Import cookies from a JSON export
notebooklm-mcp-2026 login --method import --import-file cookies.json

# Login only, skip MCP configuration
notebooklm-mcp-2026 login --skip-setup
```

### Session refresh

When cookies expire, the MCP server tries to refresh them automatically:

1. Re-import from your installed browsers (Helium first)
2. Re-read the isolated browser profile from a previous CDP login
3. Only then ask you to run `login` again

`check_auth` validates credentials with a **real API call** (not just a homepage check).

### Helium paths (Windows)

| Item | Path |
| ---- | ---- |
| Executable | `%LOCALAPPDATA%\imput\Helium\Application\chrome.exe` |
| Profile | `%LOCALAPPDATA%\imput\Helium\User Data` |

Set a default browser with:

```bash
export NOTEBOOKLM_BROWSER=helium   # macOS / Linux
$env:NOTEBOOKLM_BROWSER = "helium" # Windows PowerShell
```

### Where credentials are stored

| Platform | Location                                                      |
| -------- | ------------------------------------------------------------- |
| Linux    | `~/.local/share/notebooklm-mcp-2026/auth.json`                |
| macOS    | `~/Library/Application Support/notebooklm-mcp-2026/auth.json` |
| Windows  | `%LOCALAPPDATA%\notebooklm-mcp-2026\auth.json`                |

Override with: `NOTEBOOKLM_MCP_DATA_DIR=/custom/path`

## CLI Commands

| Command | Description |
| ------- | ----------- |
| `notebooklm-mcp-2026 login` | Log in, verify account, and auto-configure MCP clients |
| `notebooklm-mcp-2026 setup` | Interactive setup wizard (optional — `login` does this automatically) |
| `notebooklm-mcp-2026 logout` | Remove stored credentials and browser profile |
| `notebooklm-mcp-2026 serve` | Start the MCP server over stdio (used by MCP clients) |
| `notebooklm-mcp-2026 status` | Show authentication and MCP client configuration status |
| `notebooklm-mcp-2026 doctor` | Diagnose common issues (browsers, auth, permissions) |
| `notebooklm-mcp-2026 version` | Print version |

### Login flags

| Flag | Description |
| ---- | ----------- |
| `--browser helium` | Use Helium (or `chrome`, `edge`, `firefox`, …) |
| `--method browser` | Import cookies; open browser if session is missing |
| `--method cdp` | Force interactive browser login |
| `--skip-setup` | Skip MCP auto-configuration after login |
| `--chrome-path PATH` | Path to browser executable |
| `--import-file PATH` | JSON cookie file (`--method import`) |

## MCP Client Configuration

The `setup` command auto-configures your MCP client. You should not need to edit these files manually, but if you do:

<details>
<summary>Claude Code — <code>~/.claude.json</code></summary>

```json
{
  "mcpServers": {
    "notebooklm-mcp-2026": {
      "command": "notebooklm-mcp-2026",
      "args": ["serve"]
    }
  }
}
```

</details>

<details>
<summary>Cursor — <code>~/.cursor/mcp.json</code></summary>

```json
{
  "mcpServers": {
    "notebooklm-mcp-2026": {
      "command": "notebooklm-mcp-2026",
      "args": ["serve"]
    }
  }
}
```

</details>

<details>
<summary>VS Code (Copilot) — <code>mcp.json</code></summary>

```json
{
  "servers": {
    "notebooklm-mcp-2026": {
      "command": "notebooklm-mcp-2026",
      "args": ["serve"]
    }
  }
}
```

</details>

<details>
<summary>Claude Desktop</summary>

Claude Desktop does not inherit your terminal's PATH, so you **must use the full path** to the executable.

First, find your executable path:

```bash
# macOS / Linux
which notebooklm-mcp-2026

# Windows (PowerShell)
where notebooklm-mcp-2026
```

Then edit your config file:

- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

**macOS example:**

```json
{
  "mcpServers": {
    "notebooklm-mcp-2026": {
      "command": "/Users/YOUR_USER/.local/bin/notebooklm-mcp-2026",
      "args": ["serve"]
    }
  }
}
```

**Windows example:**

```json
{
  "mcpServers": {
    "notebooklm-mcp-2026": {
      "command": "C:\\Users\\YOUR_USER\\.local\\bin\\notebooklm-mcp-2026.exe",
      "args": ["serve"]
    }
  }
}
```

Replace `YOUR_USER` with your actual username, or paste the exact path from the `which`/`where` command above.

</details>

## Available Tools (9)

| Tool                 | Description                          | Key Parameters                                            |
| -------------------- | ------------------------------------ | --------------------------------------------------------- |
| `login`              | Refresh auth (browser import → CDP fallback) | `timeout` (default: 300s)                                 |
| `check_auth`         | Verify credentials via real API call         | —                                                         |
| `list_notebooks`     | List all notebooks with metadata     | `max_results` (default: 50)                               |
| `get_notebook`       | Get notebook details + source list   | `notebook_id`                                             |
| `list_sources`       | List sources in a notebook           | `notebook_id`                                             |
| `get_source_content` | Get full text of a source            | `source_id`                                               |
| `query_notebook`     | Ask the AI a question                | `notebook_id`, `query`, `source_ids?`, `conversation_id?` |
| `add_source_url`     | Add a URL/YouTube source             | `notebook_id`, `url`                                      |
| `add_source_text`    | Add pasted text source               | `notebook_id`, `text`, `title?`                           |

### Typical workflow

```
1. list_notebooks          → find the notebook ID you want
2. list_sources            → see what sources are in it
3. query_notebook          → ask questions about the sources
4. get_source_content      → read raw source text if needed
```

### Example output

When your AI assistant calls `list_notebooks`, it gets back structured data like this:

```json
{
  "status": "success",
  "count": 2,
  "notebooks": [
    {
      "id": "abc123-def456",
      "title": "Research Notes",
      "source_count": 3,
      "is_owned": true,
      "modified_at": "2026-01-15T10:30:00+00:00"
    },
    {
      "id": "ghi789-jkl012",
      "title": "Project Planning",
      "source_count": 5,
      "is_owned": true,
      "modified_at": "2026-01-14T08:00:00+00:00"
    }
  ]
}
```

And `query_notebook` returns:

```json
{
  "status": "success",
  "answer": "Based on the sources, the main topics covered are...",
  "conversation_id": "conv-uuid-123",
  "turn_number": 1,
  "is_follow_up": false
}
```

### Follow-up conversations

`query_notebook` returns a `conversation_id`. Pass it back to ask follow-up questions in the same conversation context:

```
# First question
result = query_notebook(notebook_id="abc", query="What is the main topic?")
# result.conversation_id = "uuid-123"

# Follow-up
result = query_notebook(notebook_id="abc", query="Tell me more about that", conversation_id="uuid-123")
```

## Troubleshooting

### "Not authenticated" or "Cookies expired"

```bash
notebooklm-mcp-2026 login --browser helium --method browser
```

### Browser import fails on Windows

Close the browser completely before import (the cookie database is locked while the browser runs). If import fails, `--method browser` will open the browser for interactive login automatically.

### "Browser not found" error

Install [Helium](https://helium.computer) or Chrome, or specify the path:

```bash
notebooklm-mcp-2026 login --browser helium --method cdp
notebooklm-mcp-2026 login --chrome-path "C:\Users\YOU\AppData\Local\imput\Helium\Application\chrome.exe"
```

Run `notebooklm-mcp-2026 doctor` to see which browsers are detected.

### Empty notebook list

Make sure you're logged into the correct Google account that has NotebookLM notebooks.

### "Build label" errors

Google occasionally rotates their build label. Set the updated label:

```bash
NOTEBOOKLM_BL="boq_labs-tailwind-frontend_YYYYMMDD.XX_p0" notebooklm-mcp-2026 serve
```

### Rate limit errors

NotebookLM free tier allows ~50 queries per day. Wait until the next day or upgrade.

### Something else?

Run the diagnostic tool:

```bash
notebooklm-mcp-2026 doctor
```

## Environment Variables

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `NOTEBOOKLM_MCP_DATA_DIR` | Platform default | Override data storage location |
| `NOTEBOOKLM_BROWSER` | — | Preferred browser (`helium`, `chrome`, `firefox`, …) |
| `NOTEBOOKLM_AUTH_REFRESH_COOLDOWN` | `300` | Seconds between silent session refresh attempts |
| `NOTEBOOKLM_BL` | `boq_labs-tailwind-frontend_20260108.06_p0` | Google build label |
| `NOTEBOOKLM_QUERY_TIMEOUT` | `120.0` | Query timeout in seconds |

## Security

- **No passwords stored** — only Google session cookies
- **File permissions** — credentials saved with `0o600` (owner read/write only)
- **Directory permissions** — data directory created with `0o700` (owner only)
- **No `eval`/`exec`** — no dynamic code execution anywhere
- **No `shell=True`** — browsers launched with explicit argument lists
- **Cookie filtering** — only essential Google auth cookies are persisted
- **Browser cleanup** — browser process always terminated in `finally` blocks
- **Input validation** — all tool parameters validated before use
- **Timeouts** — all HTTP requests have explicit timeouts
- **CSRF protection** — tokens passed in request body, auto-refreshed on expiry

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Lint
ruff check src/ tests/
```

### Testing with MCP Inspector

The [MCP Inspector](https://modelcontextprotocol.io/docs/tools/inspector) lets you interactively test the server's tools in a web UI:

```bash
npx @modelcontextprotocol/inspector notebooklm-mcp-2026 serve
```

This opens a browser where you can call each of the 9 tools with custom parameters and inspect responses. You must run `notebooklm-mcp-2026 login` first.

## Getting Help

- **Questions?** Open an [Issue](https://github.com/Faxtom/notebooklm-mcp-2026/issues)
- **Found a bug?** Open an [Issue](https://github.com/Faxtom/notebooklm-mcp-2026/issues)
- **Want to contribute?** See [CONTRIBUTING.md](CONTRIBUTING.md)
- **Security issue?** See [SECURITY.md](SECURITY.md) for responsible disclosure

## License

MIT
