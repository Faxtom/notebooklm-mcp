"""Branded CLI with interactive setup wizard, status, and diagnostics.

Subcommands:
    setup   - Interactive setup wizard
    login   - Authenticate via Chrome
    logout  - Remove stored credentials
    status  - Check auth and configuration status
    doctor  - Diagnose common issues
    serve   - Start MCP server over stdio
    version - Print version
    help    - Show help message (default when no command given)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import platform
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from . import __version__

# CLI output goes to stderr so stdout stays clean for MCP stdio transport.
console = Console(stderr=True)

# ---------------------------------------------------------------------------
# Branding
# ---------------------------------------------------------------------------

BRAND_COLOR = "bright_blue"
SUCCESS_COLOR = "green"
ERROR_COLOR = "red"
WARNING_COLOR = "yellow"
DIM_COLOR = "dim"

LOGO_LINES = [
    "  NotebookLM  MCP",
    "  ~~~~~~~~~~~~~~~",
]

LOGO_SHORT = "NotebookLM MCP"


def show_banner() -> None:
    """Display branded welcome banner."""
    title_line = Text.assemble(
        ("NotebookLM MCP Server", f"bold {BRAND_COLOR}"),
        ("  v", DIM_COLOR),
        (__version__, DIM_COLOR),
    )
    byline = Text("by Julian Oczkowski", style=DIM_COLOR)
    content = Text()
    content.append_text(title_line)
    content.append("\n")
    content.append_text(byline)

    console.print(Panel(
        content,
        box=box.DOUBLE,
        border_style=BRAND_COLOR,
        padding=(1, 2),
    ))


# ---------------------------------------------------------------------------
# MCP client detection and configuration
# ---------------------------------------------------------------------------


@dataclass
class MCPClientConfig:
    """How to detect and configure an MCP client."""

    name: str
    slug: str
    server_key: str  # "mcpServers" or "servers"

    def detect(self) -> bool:
        """Return True if this client appears to be installed."""
        path = self.config_path()
        return path is not None and path.parent.is_dir()

    def config_path(self) -> Path | None:
        """Return the config file path for this client."""
        raise NotImplementedError


class ClaudeCodeConfig(MCPClientConfig):
    def __init__(self) -> None:
        super().__init__(name="Claude Code", slug="claude-code", server_key="mcpServers")

    def detect(self) -> bool:
        # Claude Code creates ~/.claude/ on first use
        return (Path.home() / ".claude").is_dir()

    def config_path(self) -> Path:
        return Path.home() / ".claude.json"


class CursorConfig(MCPClientConfig):
    def __init__(self) -> None:
        super().__init__(name="Cursor", slug="cursor", server_key="mcpServers")

    def config_path(self) -> Path:
        return Path.home() / ".cursor" / "mcp.json"


class VSCodeConfig(MCPClientConfig):
    def __init__(self) -> None:
        super().__init__(name="VS Code (Copilot)", slug="vscode", server_key="servers")

    def detect(self) -> bool:
        path = self._user_dir()
        return path is not None and path.is_dir()

    def config_path(self) -> Path | None:
        user_dir = self._user_dir()
        return user_dir / "mcp.json" if user_dir else None

    def _user_dir(self) -> Path | None:
        system = platform.system()
        if system == "Linux":
            return Path.home() / ".config" / "Code" / "User"
        if system == "Darwin":
            return Path.home() / "Library" / "Application Support" / "Code" / "User"
        if system == "Windows":
            appdata = os.environ.get("APPDATA", "")
            return Path(appdata) / "Code" / "User" if appdata else None
        return None


class ClaudeDesktopConfig(MCPClientConfig):
    def __init__(self) -> None:
        super().__init__(name="Claude Desktop", slug="claude-desktop", server_key="mcpServers")

    def config_path(self) -> Path | None:
        system = platform.system()
        if system == "Linux":
            return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"
        if system == "Darwin":
            return (
                Path.home()
                / "Library"
                / "Application Support"
                / "Claude"
                / "claude_desktop_config.json"
            )
        if system == "Windows":
            appdata = os.environ.get("APPDATA", "")
            return Path(appdata) / "Claude" / "claude_desktop_config.json" if appdata else None
        return None


MCP_CLIENTS: list[MCPClientConfig] = [
    ClaudeCodeConfig(),
    CursorConfig(),
    VSCodeConfig(),
    ClaudeDesktopConfig(),
]

def _get_server_entry() -> dict[str, Any]:
    """Build the MCP server entry for config files.

    Uses the full absolute path to the ``notebooklm-mcp-2026`` executable
    so that MCP clients can find it even when the venv isn't on PATH.
    If the command is already on the system PATH, the short name is used
    for portability.
    """
    short_name = "notebooklm-mcp-2026"
    found = shutil.which(short_name)
    if found:
        # Already on PATH — use the short name for cleaner configs
        return {"command": short_name, "args": ["serve"]}

    # Not on PATH — resolve from the running interpreter's venv
    # sys.executable is e.g. /home/user/.venv/bin/python
    venv_bin = Path(sys.executable).parent
    full_path = venv_bin / short_name
    if full_path.exists():
        return {"command": str(full_path), "args": ["serve"]}

    # Last resort: python -m invocation (always works)
    return {"command": sys.executable, "args": ["-m", "notebooklm_mcp_2026", "serve"]}


# ---------------------------------------------------------------------------
# Config file merging
# ---------------------------------------------------------------------------


def merge_mcp_config(
    config_path: Path,
    server_key: str,
    server_name: str,
    server_entry: dict[str, Any],
) -> tuple[bool, str]:
    """Read an MCP client config, merge our server entry, write back.

    Returns ``(success, message)``.
    """
    config: dict[str, Any] = {}

    if config_path.exists():
        try:
            raw = config_path.read_text(encoding="utf-8")
            if raw.strip():
                config = json.loads(raw)
        except json.JSONDecodeError:
            backup = config_path.with_suffix(".json.backup")
            shutil.copy2(config_path, backup)
            return False, f"Corrupt JSON — backed up to {backup.name}"
        except OSError as exc:
            return False, f"Cannot read: {exc}"
    else:
        config_path.parent.mkdir(parents=True, exist_ok=True)

    if server_key not in config:
        config[server_key] = {}

    already_configured = server_name in config[server_key]
    config[server_key][server_name] = server_entry

    try:
        config_path.write_text(
            json.dumps(config, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        return False, f"Cannot write: {exc}"

    if already_configured:
        return True, "Updated (was already configured)"
    return True, "Added successfully"


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------


def handle_setup(*, dry_run: bool = False) -> None:
    """Interactive setup wizard."""
    import questionary

    show_banner()
    console.print()

    if dry_run:
        console.print("[bold yellow]DRY RUN[/bold yellow] — no changes will be made.\n")

    # Step 1: Check authentication ──────────────────────────────────
    console.print("[bold]Step 1:[/bold] Checking authentication...", style=BRAND_COLOR)

    from .auth import load_tokens

    tokens = load_tokens()
    if tokens is None:
        console.print("  [yellow]Not authenticated[/yellow]")
        if not dry_run:
            console.print()
            do_login = questionary.confirm(
                "Would you like to log in now?",
                default=True,
            ).ask()
            if do_login is None:  # Ctrl+C
                console.print("\n[dim]Setup cancelled.[/dim]")
                sys.exit(0)
            if do_login:
                _run_login(timeout=300)
                tokens = load_tokens()
                if tokens is None:
                    console.print("[red]Login failed. Retry with: notebooklm-mcp-2026 login[/red]")
                    sys.exit(1)
            else:
                console.print(
                    "  [dim]Skipping — you can log in later with: "
                    "notebooklm-mcp-2026 login[/dim]"
                )
    else:
        age_hours = (time.time() - tokens.extracted_at) / 3600
        console.print(
            f"  [green]Authenticated[/green] "
            f"({len(tokens.cookies)} cookies, {age_hours:.0f}h old)"
        )

    console.print()
    console.print("[bold]Step 2:[/bold] MCP client configuration", style=BRAND_COLOR)
    results = _configure_mcp_clients(dry_run=dry_run, auto_all=False)
    console.print()
    _show_success_panel(results)


def _verify_authenticated_account() -> dict[str, Any]:
    """Confirm stored credentials work against the NotebookLM API."""
    from .tools.auth_tools import check_auth

    result = check_auth()
    if result["status"] != "authenticated":
        message = result.get("message") or result.get("error") or "Authentication failed"
        hint = result.get("hint", "")
        detail = f"{message} {hint}".strip()
        raise RuntimeError(detail)
    return result


def _configure_mcp_clients(
    *,
    dry_run: bool = False,
    auto_all: bool = False,
) -> list[tuple[str, bool]]:
    """Detect MCP clients and write notebooklm-mcp-2026 into their config."""
    import questionary

    console.print("[bold]Detecting MCP clients…[/bold]", style=BRAND_COLOR)
    detected: list[MCPClientConfig] = []
    for client_cfg in MCP_CLIENTS:
        found = client_cfg.detect()
        status = "[green]found[/green]" if found else "[dim]not found[/dim]"
        console.print(f"  {client_cfg.name}: {status}")
        if found:
            detected.append(client_cfg)

    if not detected:
        console.print("\n[yellow]No MCP clients detected.[/yellow]")
        console.print("Install Claude Code, Cursor, or VS Code, then run setup again.")
        return []

    console.print()

    if dry_run or auto_all:
        selected = detected
        if dry_run:
            console.print("[bold]Would configure all detected clients[/bold]", style=BRAND_COLOR)
    else:
        console.print("[bold]Select clients to configure[/bold]", style=BRAND_COLOR)
        choices = questionary.checkbox(
            "Which clients should be configured?",
            choices=[
                questionary.Choice(title=c.name, value=c.slug, checked=True)
                for c in detected
            ],
        ).ask()

        if choices is None:
            console.print("\n[dim]Setup cancelled.[/dim]")
            sys.exit(0)

        if not choices:
            console.print("[dim]No clients selected.[/dim]")
            return []

        selected = [c for c in detected if c.slug in choices]

    console.print()
    action = "Would configure" if dry_run else "Configuring"
    console.print(f"[bold]{action} MCP clients…[/bold]", style=BRAND_COLOR)
    results: list[tuple[str, bool]] = []

    for client_cfg in selected:
        config_path = client_cfg.config_path()
        if config_path is None:
            console.print(f"  {client_cfg.name}: [yellow]skipped (unsupported platform)[/yellow]")
            continue

        if dry_run:
            console.print(f"  {client_cfg.name}: [cyan]would write to {config_path}[/cyan]")
            results.append((client_cfg.name, True))
            continue

        with console.status(f"  Configuring {client_cfg.name}...", spinner="dots"):
            ok, msg = merge_mcp_config(
                config_path=config_path,
                server_key=client_cfg.server_key,
                server_name="notebooklm-mcp-2026",
                server_entry=_get_server_entry(),
            )

        if ok:
            console.print(f"  {client_cfg.name}: [green]{msg}[/green]")
            console.print(f"    [dim]{config_path}[/dim]")
            results.append((client_cfg.name, True))
        else:
            console.print(f"  {client_cfg.name}: [red]{msg}[/red]")
            results.append((client_cfg.name, False))

    return results


def _auto_setup_after_login() -> None:
    """Verify the account and configure detected MCP clients without extra prompts."""
    console.print()
    console.print("[bold]Verifying account…[/bold]", style=BRAND_COLOR)
    with console.status("  Checking NotebookLM access...", spinner="dots"):
        result = _verify_authenticated_account()
    console.print(
        f"  [green]Account verified[/green] "
        f"({result.get('cookie_count', '?')} cookies)"
    )
    console.print()
    results = _configure_mcp_clients(auto_all=True)
    console.print()
    if results:
        _show_success_panel(results)
    else:
        console.print(Panel(
            "[green bold]Login complete![/green bold]\n\n"
            "Your account is verified, but no MCP clients were detected.\n"
            "Install Cursor, Claude Code, or VS Code and run "
            "[bold]notebooklm-mcp-2026 setup[/bold].",
            title="[green]Authenticated[/green]",
            border_style=SUCCESS_COLOR,
            box=box.ROUNDED,
            padding=(1, 2),
        ))


def _show_success_panel(results: list[tuple[str, bool]]) -> None:
    """Show branded success message with next steps."""
    success_count = sum(1 for _, ok in results if ok)

    if success_count == 0:
        console.print(Panel(
            "[red bold]No clients were configured successfully.[/red bold]\n"
            "Check the error messages above and try again.",
            title="Setup Failed",
            border_style=ERROR_COLOR,
            box=box.ROUNDED,
            padding=(1, 2),
        ))
        return

    lines = [
        f"[green bold]Setup complete![/green bold] "
        f"Configured {success_count} client(s).\n",
        "[bold]Next steps:[/bold]",
        "",
        "  1. Restart your MCP client (Claude Code, Cursor, VS Code)",
        '  2. Try asking: [italic]"List my NotebookLM notebooks"[/italic]',
        "  3. The AI assistant now has access to your NotebookLM notebooks",
        "",
        "[dim]Sessions auto-refresh from Chrome when possible. "
        "Re-run login only if auth fails.[/dim]",
        "[dim]More info: https://github.com/julianoczkowski/notebooklm-mcp-2026[/dim]",
    ]

    console.print(Panel(
        "\n".join(lines),
        title="[green]Success[/green]",
        border_style=SUCCESS_COLOR,
        box=box.ROUNDED,
        padding=(1, 2),
    ))


def _run_login(
    timeout: int,
    chrome_path: str | None = None,
    *,
    method: str = "auto",
    import_file: str | None = None,
    browser: str | None = None,
) -> None:
    """Execute login with the chosen authentication method."""
    from pathlib import Path

    from .auth import (
        extract_cookies_from_browser,
        extract_cookies_via_cdp,
        import_cookies_from_file,
        load_tokens,
        save_tokens,
        try_silent_token_refresh,
        validate_cookies,
    )

    method = method.lower()

    if method == "auto" and load_tokens() is not None:
        tokens = load_tokens()
        if tokens and validate_cookies(tokens.cookies):
            console.print(
                "[green]Already authenticated.[/green] "
                "Use [bold]notebooklm-mcp-2026 logout[/bold] to start fresh."
            )
            return

    if method in ("auto", "browser"):
        if method == "auto":
            console.print("[dim]Trying browser import (Helium, Chrome, Edge, …)…[/dim]")
        else:
            from .auth import BROWSER_META, _normalize_browser_name

            label = (
                BROWSER_META[_normalize_browser_name(browser)]["label"]
                if browser
                else "your browser"
            )
            console.print(f"[dim]Trying to read cookies from {label}…[/dim]")

        try:
            tokens = extract_cookies_from_browser(browser=browser)
            save_tokens(tokens)
            _show_login_success(tokens)
            return
        except Exception as exc:
            if method == "auto":
                console.print(f"  [dim]Browser import skipped: {exc}[/dim]")
            elif _browser_can_open_for_login(browser):
                console.print(
                    f"\n[yellow]No valid session found.[/yellow] {exc}\n"
                    "[dim]Opening the browser so you can log in to NotebookLM…[/dim]"
                )
                _run_cdp_login(timeout, chrome_path=chrome_path, browser=browser)
                return
            console.print(f"\n[red]Browser import failed:[/red] {exc}", highlight=False)
            raise

    if method in ("auto", "profile"):
        console.print("[dim]Trying silent refresh from saved Chrome profile…[/dim]")
        tokens = try_silent_token_refresh(force=True)
        if tokens is not None:
            _show_login_success(tokens)
            return
        if method == "profile":
            console.print(
                "\n[red]Profile refresh failed.[/red] "
                "Run [bold]notebooklm-mcp-2026 login --method cdp[/bold] once to create a profile."
            )
            raise RuntimeError("Persistent profile is not logged in.")

    if method == "import":
        if not import_file:
            raise RuntimeError("--import-file is required for --method import")
        tokens = import_cookies_from_file(Path(import_file))
        save_tokens(tokens)
        _show_login_success(tokens)
        return

    # CDP interactive login (original flow, last resort)
    _run_cdp_login(timeout, chrome_path=chrome_path, browser=browser)


def _browser_can_open_for_login(browser: str | None) -> bool:
    """Return True if we can open an interactive login window for *browser*."""
    from .auth import BROWSER_META, _normalize_browser_name, get_browser_executable, get_cdp_browser_executable

    if browser is not None:
        name = _normalize_browser_name(browser)
        if not BROWSER_META[name]["cdp"]:
            return False
        return get_browser_executable(name) is not None or get_cdp_browser_executable(name) is not None
    return get_cdp_browser_executable() is not None


def _normalize_browser_cli(browser: str | None) -> str:
    from .auth import _normalize_browser_name

    if browser is None:
        raise ValueError("browser is required")
    return _normalize_browser_name(browser)


def _show_login_success(tokens) -> None:
    """Display successful login panel."""
    console.print()
    console.print(Panel(
        f"[green bold]Authenticated![/green bold]  "
        f"Saved {len(tokens.cookies)} cookies.\n"
        + ("  CSRF token: [green]extracted[/green]\n" if tokens.csrf_token else "")
        + ("  Session ID: [green]extracted[/green]" if tokens.session_id else ""),
        title="[green]Login Successful[/green]",
        border_style=SUCCESS_COLOR,
        box=box.ROUNDED,
        padding=(1, 2),
    ))
    console.print()


def _run_cdp_login(
    timeout: int,
    chrome_path: str | None = None,
    *,
    browser: str | None = None,
) -> None:
    """Execute the Chromium CDP login flow with rich output."""
    from .auth import BROWSER_META, get_cdp_browser_executable, get_browser_executable

    browser_label = "Chromium-based browser"
    if browser:
        browser_label = BROWSER_META[_normalize_browser_cli(browser)]["label"]
    else:
        path = get_cdp_browser_executable()
        if path:
            for name, meta in BROWSER_META.items():
                if meta["cdp"] and get_browser_executable(name) == path:
                    browser_label = meta["label"]
                    break

    console.print(Panel(
        f"[bold]Browser Login (CDP)[/bold]\n\n"
        f"Opens {browser_label} in an isolated profile "
        "(your normal browser can stay open).\n"
        "Log in to your Google account on notebooklm.google.com.",
        border_style=BRAND_COLOR,
        box=box.ROUNDED,
        padding=(1, 2),
    ))

    from .auth import extract_cookies_via_cdp, save_tokens

    def _on_manual_launch(port: int, launch_args: list[str]) -> None:
        """Show manual Chrome launch instructions when auto-detect fails."""
        args_str = " ".join(launch_args)
        system = platform.system()
        if system == "Windows":
            hint = r'%LOCALAPPDATA%\imput\Helium\Application\chrome.exe'
            hint_alt = r'"C:\Program Files\Google\Chrome\Application\chrome.exe"'
        elif system == "Darwin":
            hint = '"/Applications/Helium.app/Contents/MacOS/Helium"'
            hint_alt = '"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"'
        else:
            hint = "helium"
            hint_alt = "google-chrome"

        console.print()
        console.print(Panel(
            "[bold yellow]Browser was not found automatically.[/bold yellow]\n\n"
            "Run this command in another terminal (Helium or Chromium):\n\n"
            f"  [bold cyan]{hint} {args_str}[/bold cyan]\n\n"
            f"  [dim]or: {hint_alt} {args_str}[/dim]\n\n"
            "Or re-run with your browser path:\n\n"
            '  [bold]notebooklm-mcp-2026 login --browser helium --method cdp[/bold]\n'
            '  [bold]notebooklm-mcp-2026 login --chrome-path "/path/to/browser"[/bold]',
            title="[yellow]Manual Chrome Launch[/yellow]",
            border_style=WARNING_COLOR,
            box=box.ROUNDED,
            padding=(1, 2),
        ))
        console.print()

    try:
        status = console.status("Launching Chrome and waiting for login...", spinner="dots")
        status.start()

        def _on_manual_launch_wrapper(port: int, launch_args: list[str]) -> None:
            status.stop()
            _on_manual_launch(port, launch_args)
            status.update("Waiting for Chrome connection...")
            status.start()

        tokens = extract_cookies_via_cdp(
            login_timeout=timeout,
            chrome_path=chrome_path,
            browser=browser,
            on_manual_launch_needed=_on_manual_launch_wrapper,
        )
        status.stop()

        save_tokens(tokens)
        _show_login_success(tokens)
    except Exception as exc:
        try:
            status.stop()
        except Exception:
            pass
        console.print(f"\n[red]Login failed:[/red] {exc}", highlight=False)
        raise


def handle_login(
    timeout: int,
    chrome_path: str | None = None,
    *,
    method: str = "auto",
    import_file: str | None = None,
    browser: str | None = None,
    skip_setup: bool = False,
) -> None:
    """Login subcommand handler."""
    show_banner()
    console.print()
    try:
        _run_login(
            timeout,
            chrome_path=chrome_path,
            method=method,
            import_file=import_file,
            browser=browser,
        )
        if skip_setup:
            console.print(Panel(
                "[green bold]Login complete![/green bold]\n\n"
                "Restart your MCP client and try:\n"
                '[italic]"List my NotebookLM notebooks"[/italic]',
                title="[green]Success[/green]",
                border_style=SUCCESS_COLOR,
                box=box.ROUNDED,
                padding=(1, 2),
            ))
            return
        _auto_setup_after_login()
    except Exception:
        sys.exit(1)


def handle_status() -> None:
    """Show auth and config status."""
    show_banner()
    console.print()

    # Auth status ───────────────────────────────────────────────────
    console.print("[bold]Authentication[/bold]", style=BRAND_COLOR)

    from .auth import load_tokens

    tokens = load_tokens()
    if tokens is None:
        console.print("  Status: [red]Not authenticated[/red]")
        console.print("  Run: [bold]notebooklm-mcp-2026 login[/bold]")
    else:
        age_hours = (time.time() - tokens.extracted_at) / 3600
        age_str = f"{age_hours:.0f}h" if age_hours < 48 else f"{age_hours / 24:.0f}d"
        console.print("  Status: [green]Authenticated[/green]")
        console.print(f"  Cookies: {len(tokens.cookies)}")
        console.print(f"  Age: {age_str}")
        console.print(
            f"  CSRF: {'[green]yes[/green]' if tokens.csrf_token else '[yellow]no[/yellow]'}"
        )

    console.print()

    # Client config status ──────────────────────────────────────────
    console.print("[bold]MCP Client Configuration[/bold]", style=BRAND_COLOR)
    table = Table(show_header=True, header_style="bold", box=box.SIMPLE)
    table.add_column("Client")
    table.add_column("Installed")
    table.add_column("Configured")
    table.add_column("Config Path")

    for client_cfg in MCP_CLIENTS:
        installed = client_cfg.detect()
        config_path = client_cfg.config_path()
        configured = False

        if config_path and config_path.exists():
            try:
                data = json.loads(config_path.read_text(encoding="utf-8"))
                servers = data.get(client_cfg.server_key, {})
                configured = "notebooklm-mcp-2026" in servers
            except (json.JSONDecodeError, OSError):
                pass

        table.add_row(
            client_cfg.name,
            "[green]yes[/green]" if installed else "[dim]no[/dim]",
            "[green]yes[/green]" if configured else "[yellow]no[/yellow]",
            str(config_path) if config_path else "N/A",
        )

    console.print(table)


def handle_doctor() -> None:
    """Diagnose common issues."""
    show_banner()
    console.print()
    console.print("[bold]Running diagnostics...[/bold]", style=BRAND_COLOR)
    console.print()

    checks: list[tuple[str, bool, str]] = []

    # Python version
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    checks.append(("Python >= 3.11", sys.version_info >= (3, 11), py_ver))

    # Browsers
    from .auth import BROWSER_META, get_cdp_browser_executable, list_detected_browsers

    detected = list_detected_browsers()
    cdp_path = get_cdp_browser_executable()
    if detected:
        labels = ", ".join(BROWSER_META[b]["label"] for b in detected)
        checks.append(("Browsers detected", True, labels))
    else:
        checks.append(("Browsers detected", False, "none found"))
    checks.append(("CDP browser (login)", cdp_path is not None, cdp_path or "not found"))

    # Auth file exists
    from .config import AUTH_FILE

    checks.append(("Auth credentials", AUTH_FILE.exists(), str(AUTH_FILE)))

    # Auth file permissions (Unix only)
    if AUTH_FILE.exists() and platform.system() != "Windows":
        mode = AUTH_FILE.stat().st_mode & 0o777
        checks.append(("Auth file permissions", mode == 0o600, f"0o{mode:03o} (want 0o600)"))

    # Tokens loadable
    from .auth import load_tokens

    tokens = load_tokens()
    checks.append(("Tokens loadable", tokens is not None, ""))

    # Required cookies present
    if tokens:
        from .auth import validate_cookies

        valid = validate_cookies(tokens.cookies)
        checks.append(("Required cookies", valid, f"{len(tokens.cookies)} cookies"))

    # FastMCP importable
    try:
        import fastmcp

        checks.append(("FastMCP", True, f"v{fastmcp.__version__}"))
    except ImportError:
        checks.append(("FastMCP", False, "not installed"))

    # Print results
    for label, ok, detail in checks:
        icon = "[green]PASS[/green]" if ok else "[red]FAIL[/red]"
        detail_str = f"  [dim]{detail}[/dim]" if detail else ""
        console.print(f"  {icon}  {label}{detail_str}")

    console.print()
    fail_count = sum(1 for _, ok, _ in checks if not ok)
    if fail_count == 0:
        console.print("[green]All checks passed![/green]")
    else:
        console.print(f"[yellow]{fail_count} issue(s) found. See above.[/yellow]")


def handle_logout() -> None:
    """Remove stored credentials."""
    from .config import AUTH_FILE, CHROME_PROFILE_DIR

    removed = []

    if AUTH_FILE.exists():
        AUTH_FILE.unlink()
        removed.append(f"Credentials: {AUTH_FILE}")

    if CHROME_PROFILE_DIR.exists():
        shutil.rmtree(CHROME_PROFILE_DIR, ignore_errors=True)
        removed.append(f"Chrome profile: {CHROME_PROFILE_DIR}")

    if removed:
        console.print(Panel(
            "[green bold]Logged out.[/green bold]\n\n"
            + "\n".join(f"  Removed: [dim]{r}[/dim]" for r in removed)
            + "\n\nRun [bold]notebooklm-mcp-2026 login[/bold] to authenticate again.",
            title="[green]Logout[/green]",
            border_style=SUCCESS_COLOR,
            box=box.ROUNDED,
            padding=(1, 2),
        ))
    else:
        console.print("[dim]No credentials found — already logged out.[/dim]")


def handle_help() -> None:
    """Show branded help with all available commands."""
    show_banner()
    console.print()

    commands = [
        ("setup", "Interactive setup wizard — authenticate and configure MCP clients"),
        ("login", "Log in, verify account, and auto-configure MCP clients"),
        ("logout", "Remove stored credentials and Chrome profile"),
        ("status", "Show authentication and MCP client configuration status"),
        ("doctor", "Diagnose common issues (Chrome, auth, permissions)"),
        ("serve", "Start the MCP server over stdio (used by MCP clients)"),
        ("version", "Print version"),
        ("help", "Show this help message"),
    ]

    table = Table(show_header=True, header_style="bold", box=box.SIMPLE, pad_edge=False)
    table.add_column("Command", style="bold cyan", no_wrap=True)
    table.add_column("Description")

    for cmd, desc in commands:
        table.add_row(f"notebooklm-mcp-2026 {cmd}", desc)

    console.print(table)
    console.print()
    console.print("[bold]Getting started?[/bold] Run [bold cyan]notebooklm-mcp-2026 setup[/bold cyan]")
    console.print()
    console.print("[dim]More info: https://github.com/julianoczkowski/notebooklm-mcp-2026[/dim]")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point (``notebooklm-mcp-2026`` command)."""
    parser = argparse.ArgumentParser(
        prog="notebooklm-mcp-2026",
        description="Secure MCP server for querying Google NotebookLM notebooks.",
        add_help=False,
    )
    subparsers = parser.add_subparsers(dest="command")

    # serve
    serve_parser = subparsers.add_parser("serve", help="Run the MCP server (stdio)")
    serve_parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    # login
    login_parser = subparsers.add_parser(
        "login",
        help="Log in, verify account, and auto-configure MCP clients",
    )
    login_parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Max seconds to wait for login (default: 300)",
    )
    login_parser.add_argument(
        "--browser",
        choices=("auto", "helium", "chrome", "edge", "brave", "chromium", "opera", "vivaldi", "firefox", "librewolf", "safari"),
        default=None,
        help="Browser for import/cdp (default: try all, or NOTEBOOKLM_BROWSER env var)",
    )
    login_parser.add_argument(
        "--method",
        choices=("auto", "browser", "profile", "cdp", "import"),
        default="auto",
        help=(
            "Login method: auto (browser → profile → cdp), browser (import cookies, "
            "open browser if missing), profile (silent CDP), cdp (interactive), import (JSON)"
        ),
    )
    login_parser.add_argument(
        "--import-file",
        help="Cookie JSON file (required with --method import)",
    )
    login_parser.add_argument(
        "--chrome-path",
        help="Path to Chrome/Chromium executable (auto-detected if omitted)",
    )
    login_parser.add_argument(
        "--skip-setup",
        action="store_true",
        help="Skip MCP client auto-configuration after login",
    )
    login_parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    # logout
    subparsers.add_parser("logout", help="Remove stored credentials and Chrome profile")

    # setup
    setup_parser = subparsers.add_parser("setup", help="Interactive setup wizard")
    setup_parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    setup_parser.add_argument(
        "--dry-run", action="store_true", help="Show what would be configured without making changes"
    )

    # status
    status_parser = subparsers.add_parser("status", help="Show auth and config status")
    status_parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    # doctor
    doctor_parser = subparsers.add_parser("doctor", help="Diagnose common issues")
    doctor_parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    # version
    subparsers.add_parser("version", help="Print version and exit")

    # help
    subparsers.add_parser("help", help="Show help message")

    args = parser.parse_args()

    debug = getattr(args, "debug", False)
    if debug:
        logging.basicConfig(level=logging.DEBUG, stream=sys.stderr)

    if args.command == "login":
        browser = None if args.browser in (None, "auto") else args.browser
        handle_login(
            args.timeout,
            chrome_path=args.chrome_path,
            method=args.method,
            import_file=args.import_file,
            browser=browser,
            skip_setup=args.skip_setup,
        )
    elif args.command == "logout":
        handle_logout()
    elif args.command == "setup":
        dry_run = getattr(args, "dry_run", False)
        handle_setup(dry_run=dry_run)
    elif args.command == "status":
        handle_status()
    elif args.command == "doctor":
        handle_doctor()
    elif args.command == "version":
        console.print(f"notebooklm-mcp-2026 {__version__}")
    elif args.command == "serve":
        from .server import mcp

        mcp.run(transport="stdio")
    else:
        # No command or "help" — show branded help
        handle_help()
