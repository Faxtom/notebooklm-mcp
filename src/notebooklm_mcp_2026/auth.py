"""Authentication — Chrome CDP cookie extraction and credential storage.

Security model:
- Data directory created with 0o700 (owner-only access).
- Credential file written with 0o600 (owner read/write only).
- Chrome launched via ``subprocess.Popen(list)`` — never ``shell=True``.
- Chrome process always cleaned up in ``finally`` blocks.
- Only essential Google cookies are persisted (not the full cookie jar).
"""

from __future__ import annotations

import atexit
import json
import os
import logging
import platform
import re
import shutil
import socket
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from collections.abc import Callable

from .config import (
    AUTH_FILE,
    CHROME_PROFILE_DIR,
    ESSENTIAL_COOKIES,
    REQUIRED_COOKIES,
    STORAGE_DIR,
)
from . import config

logger = logging.getLogger("notebooklm_mcp_2026.auth")

NOTEBOOKLM_URL = "https://notebooklm.google.com/"
CDP_PORT_START = 9222
CDP_PORT_RANGE = 10  # scan 9222–9231


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class AuthTokens:
    """Persisted authentication state."""

    cookies: dict[str, str]
    csrf_token: str = ""
    session_id: str = ""
    extracted_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AuthTokens:
        return cls(
            cookies=data.get("cookies", {}),
            csrf_token=data.get("csrf_token", ""),
            session_id=data.get("session_id", ""),
            extracted_at=data.get("extracted_at", 0.0),
        )


# ---------------------------------------------------------------------------
# Credential storage (file-based, secure permissions)
# ---------------------------------------------------------------------------


def ensure_storage_dir() -> Path:
    """Create the storage directory with owner-only permissions."""
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        STORAGE_DIR.chmod(0o700)
    except OSError:
        pass  # Windows doesn't support Unix permissions
    return STORAGE_DIR


def save_tokens(tokens: AuthTokens) -> None:
    """Write tokens to disk with restricted permissions (0o600)."""
    ensure_storage_dir()
    AUTH_FILE.write_text(json.dumps(tokens.to_dict(), indent=2))
    try:
        AUTH_FILE.chmod(0o600)
    except OSError:
        pass


def load_tokens() -> AuthTokens | None:
    """Load tokens from disk. Returns ``None`` if missing or corrupt."""
    if not AUTH_FILE.exists():
        return None
    try:
        data = json.loads(AUTH_FILE.read_text())
        tokens = AuthTokens.from_dict(data)
        if not tokens.cookies:
            return None
        return tokens
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def validate_cookies(cookies: dict[str, str]) -> bool:
    """Check that all required Google auth cookies are present."""
    return REQUIRED_COOKIES.issubset(cookies.keys())


def filter_essential_cookies(cookies: dict[str, str]) -> dict[str, str]:
    """Keep only the Google cookies needed for NotebookLM API calls."""
    return {name: value for name, value in cookies.items() if name in ESSENTIAL_COOKIES}


def build_tokens_from_cookies(cookies: dict[str, str]) -> AuthTokens:
    """Build auth tokens from cookie dict, fetching CSRF + session ID over HTTP."""
    import httpx

    from .config import BASE_URL, PAGE_FETCH_HEADERS

    filtered = filter_essential_cookies(cookies)
    if not validate_cookies(filtered):
        missing = REQUIRED_COOKIES - filtered.keys()
        raise RuntimeError(
            f"Missing required Google cookies: {', '.join(sorted(missing))}. "
            "Log in to https://notebooklm.google.com in your browser first."
        )

    jar = httpx.Cookies()
    for name, value in filtered.items():
        jar.set(name, value, domain=".google.com")

    with httpx.Client(
        cookies=jar,
        headers=PAGE_FETCH_HEADERS,
        follow_redirects=True,
        timeout=15.0,
    ) as client:
        resp = client.get(f"{BASE_URL}/")
        if "accounts.google.com" in str(resp.url):
            raise RuntimeError(
                "Google session expired in browser. "
                "Open https://notebooklm.google.com in your browser and log in again."
            )
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to reach NotebookLM: HTTP {resp.status_code}")

        html = resp.text
        csrf_token = extract_csrf_from_html(html)
        session_id = extract_session_id_from_html(html)
        if not csrf_token:
            raise RuntimeError("Could not extract CSRF token from NotebookLM page.")

    return AuthTokens(
        cookies=filtered,
        csrf_token=csrf_token,
        session_id=session_id,
        extracted_at=time.time(),
    )


# ---------------------------------------------------------------------------
# Alternative auth — import from system browser or file (no CDP window)
# ---------------------------------------------------------------------------

_last_silent_refresh: float = 0.0

# Shown when the on-disk cookie DB is locked (browser open on Windows).
_CDP_COOKIE_IMPORT_HINT = (
    "On Windows the browser locks its cookie database while it is running. "
    "To import cookies without closing it, restart the browser once with "
    "--remote-debugging-port=9222 (or set NOTEBOOKLM_CDP_PORT), then retry. "
    "Run: notebooklm-mcp-2026 enable-cdp --browser helium"
)


def _cookie_db_locked_error(exc: BaseException) -> bool:
    """Return True when *exc* indicates the Chromium cookie DB cannot be read."""
    name = type(exc).__name__
    if name in ("RequiresAdminError", "PermissionError", "BrowserCookieError"):
        return True
    msg = str(exc).lower()
    return any(
        token in msg
        for token in (
            "being used by another process",
            "utilizado por otro proceso",
            "unable to read database",
            "requires admin",
        )
    )


def helium_user_data_dir() -> Path:
    """Default Helium profile directory (https://github.com/imputnet/helium)."""
    system = platform.system()
    if system == "Windows":
        return Path(os.environ.get("LOCALAPPDATA", "")) / "imput" / "Helium" / "User Data"
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "net.imput.helium"
    return Path.home() / ".config" / "helium"


def helium_cookie_db_paths() -> tuple[Path, Path] | None:
    """Return ``(cookies_db, local_state)`` for Helium's default profile."""
    user_data = helium_user_data_dir()
    if not user_data.is_dir():
        return None

    key_file = user_data / "Local State"
    if not key_file.is_file():
        return None

    default_profile = user_data / "Default"
    for cookie_file in (
        default_profile / "Network" / "Cookies",
        default_profile / "Cookies",
    ):
        if cookie_file.is_file():
            return cookie_file, key_file

    for profile_dir in sorted(user_data.glob("Profile *")):
        for rel in ("Network/Cookies", "Cookies"):
            cookie_file = profile_dir / rel
            if cookie_file.is_file():
                return cookie_file, key_file

    return None


def _helium_executable_candidates() -> list[Path]:
    """Helium installs chrome.exe under %LOCALAPPDATA%\\imput\\Helium\\Application."""
    system = platform.system()
    local = Path(os.environ.get("LOCALAPPDATA", ""))

    if system == "Darwin":
        return [Path("/Applications/Helium.app/Contents/MacOS/Helium")]

    if system == "Linux":
        return []

    app_dir = local / "imput" / "Helium" / "Application"
    candidates: list[Path] = []
    root_exe = app_dir / "chrome.exe"
    if root_exe.is_file():
        candidates.append(root_exe)
    if app_dir.is_dir():
        candidates.extend(sorted(app_dir.glob("*/chrome.exe"), reverse=True))
    return candidates


def _load_helium_cookies_from_disk() -> dict[str, str]:
    """Import Google cookies from Helium's on-disk Chromium profile."""
    import browser_cookie3

    paths = helium_cookie_db_paths()
    if paths is None:
        raise RuntimeError(
            "Helium profile not found. Install Helium from https://github.com/imputnet/helium, "
            "log in to https://notebooklm.google.com, then close Helium and retry."
        )

    cookie_file, key_file = paths
    try:
        jar = browser_cookie3.chrome(
            cookie_file=str(cookie_file),
            domain_name=".google.com",
            key_file=str(key_file),
        )
    except Exception as exc:
        if _cookie_db_locked_error(exc):
            raise RuntimeError(
                "Could not read Helium cookies while Helium is open.\n"
                f"{_CDP_COOKIE_IMPORT_HINT}\n({exc})"
            ) from exc
        raise RuntimeError(
            "Could not read Helium cookies. Close Helium completely and try again, "
            f"or use: notebooklm-mcp-2026 login --method cdp --browser helium\n({exc})"
        ) from exc

    cookies: dict[str, str] = {}
    for cookie in jar:
        cookie_name = getattr(cookie, "name", "")
        if cookie_name in ESSENTIAL_COOKIES:
            cookies[cookie_name] = getattr(cookie, "value", "")
    return cookies


def _load_helium_cookies() -> dict[str, str]:
    """Import Google cookies from Helium (CDP while open, else on-disk profile)."""
    cookies = _try_load_cookies_via_running_cdp()
    if cookies is not None:
        logger.info("Imported Helium cookies via CDP (browser can stay open).")
        return cookies
    return _load_helium_cookies_from_disk()


def _load_cookies_with_browser_cookie3(browser: str) -> dict[str, str]:
    """Load Google cookies from a specific browser profile via browser_cookie3."""
    try:
        import browser_cookie3
    except ImportError as exc:
        raise RuntimeError(
            "browser-cookie3 is not installed. Run: pip install browser-cookie3"
        ) from exc

    name = _normalize_browser_name(browser)
    if BROWSER_META[name]["cdp"]:
        cookies = _try_load_cookies_via_running_cdp()
        if cookies is not None:
            logger.info(
                "Imported cookies via CDP for %s (browser can stay open).",
                BROWSER_META[name]["label"],
            )
            return cookies

    if name == "helium":
        return _load_helium_cookies_from_disk()

    loader_name = BROWSER_META[name]["cookie3"]
    loader = getattr(browser_cookie3, loader_name, None)
    if loader is None:
        raise RuntimeError(f"browser-cookie3 does not support {BROWSER_META[name]['label']}.")

    label = BROWSER_META[name]["label"]
    try:
        jar = loader(domain_name=".google.com")
    except Exception as exc:
        if BROWSER_META[name]["cdp"] and _cookie_db_locked_error(exc):
            raise RuntimeError(
                f"Could not read {label} cookies while the browser is open.\n"
                f"{_CDP_COOKIE_IMPORT_HINT}\n({exc})"
            ) from exc
        raise RuntimeError(
            f"Could not read {label} cookies. Close the browser completely and try again "
            f"or use --method cdp with a Chromium browser.\n({exc})"
        ) from exc

    cookies: dict[str, str] = {}
    for cookie in jar:
        cookie_name = getattr(cookie, "name", "")
        if cookie_name in ESSENTIAL_COOKIES:
            cookies[cookie_name] = getattr(cookie, "value", "")
    return cookies


def _browser_import_order(browser: str | None) -> list[str]:
    """Resolve which browsers to try for cookie import."""
    if browser is not None:
        return [_normalize_browser_name(browser)]

    preferred = os.environ.get("NOTEBOOKLM_BROWSER", "").strip().lower()
    order: list[str] = []
    if preferred and preferred in BROWSER_META:
        order.append(preferred)
    for name in BROWSER_ORDER:
        if name == "safari" and platform.system() != "Darwin":
            continue
        if name not in order:
            order.append(name)
    return order


def extract_cookies_from_browser(browser: str | None = None) -> AuthTokens:
    """Import Google cookies from an installed browser profile.

    Tries *browser* if given, otherwise every supported browser in order.
    Most browsers must be **closed** on Windows while cookies are read.
    """
    errors: list[str] = []
    for name in _browser_import_order(browser):
        try:
            cookies = _load_cookies_with_browser_cookie3(name)
            tokens = build_tokens_from_cookies(cookies)
            logger.info("Imported cookies from %s.", BROWSER_META[name]["label"])
            return tokens
        except Exception as exc:
            errors.append(f"{BROWSER_META[name]['label']}: {exc}")
            logger.debug("Cookie import failed for %s: %s", name, exc)

    if browser is not None:
        raise RuntimeError(errors[-1] if errors else f"Could not import from {browser}.")

    summary = "; ".join(errors[:3])
    if len(errors) > 3:
        summary += f"; …and {len(errors) - 3} more"
    raise RuntimeError(
        "Could not import cookies from any supported browser. "
        "Log in to notebooklm.google.com, close your browser, and retry — "
        f"or use --method cdp.\n{summary}"
    )


def import_cookies_from_file(path: Path) -> AuthTokens:
    """Import cookies from a JSON file.

    Supported formats:
    - ``{"SID": "...", "HSID": "..."}``
    - ``{"cookies": {"SID": "..."}}``
    - ``[{"name": "SID", "value": "..."}, ...]`` (Chrome DevTools export)
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Invalid cookie file: {exc}") from exc

    cookies: dict[str, str] = {}

    if isinstance(data, dict):
        if "cookies" in data and isinstance(data["cookies"], dict):
            cookies = {str(k): str(v) for k, v in data["cookies"].items()}
        else:
            cookies = {str(k): str(v) for k, v in data.items() if not k.startswith("_")}
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                name = item.get("name", "")
                value = item.get("value", "")
                if name and value:
                    cookies[str(name)] = str(value)

    if not cookies:
        raise RuntimeError("No cookies found in file.")

    return build_tokens_from_cookies(cookies)


def try_silent_token_refresh(*, force: bool = False) -> AuthTokens | None:
    """Try to refresh stored tokens without user interaction.

    Attempts, in order:
    1. Import cookies from installed browsers (Chrome, Edge, Firefox, …).
    2. Re-extract from the isolated Chromium profile used by prior CDP logins.

    Returns ``None`` if all methods fail or cooldown has not elapsed.
    """
    global _last_silent_refresh

    if not force:
        elapsed = time.time() - _last_silent_refresh
        if elapsed < config.AUTH_SILENT_REFRESH_COOLDOWN:
            return None

    _last_silent_refresh = time.time()

    # 1. Installed browser profiles
    try:
        tokens = extract_cookies_from_browser()
        save_tokens(tokens)
        logger.info("Silently refreshed tokens from system browser profile.")
        return tokens
    except Exception as exc:
        logger.debug("Browser cookie import failed: %s", exc)

    # 2. Persistent isolated profile (headless CDP, no login prompt)
    try:
        tokens = extract_cookies_via_cdp(
            login_timeout=30,
            interactive=False,
            headless=True,
        )
        save_tokens(tokens)
        logger.info("Silently refreshed tokens from persistent Chrome profile.")
        return tokens
    except Exception as exc:
        logger.debug("Profile CDP refresh failed: %s", exc)

    return None


# Browsers supported for cookie import (browser_cookie3) and/or CDP login (Chromium-based)
BROWSER_ORDER = (
    "helium",
    "chrome",
    "edge",
    "brave",
    "chromium",
    "opera",
    "vivaldi",
    "firefox",
    "librewolf",
    "safari",
)

# cookie3 loader name (or "helium" for custom) → supports CDP interactive login
BROWSER_META: dict[str, dict[str, Any]] = {
    "helium": {"label": "Helium", "cookie3": "helium", "cdp": True},
    "chrome": {"label": "Google Chrome", "cookie3": "chrome", "cdp": True},
    "edge": {"label": "Microsoft Edge", "cookie3": "edge", "cdp": True},
    "brave": {"label": "Brave", "cookie3": "brave", "cdp": True},
    "chromium": {"label": "Chromium", "cookie3": "chromium", "cdp": True},
    "opera": {"label": "Opera", "cookie3": "opera", "cdp": True},
    "vivaldi": {"label": "Vivaldi", "cookie3": "vivaldi", "cdp": True},
    "firefox": {"label": "Firefox", "cookie3": "firefox", "cdp": False},
    "librewolf": {"label": "LibreWolf", "cookie3": "librewolf", "cdp": False},
    "safari": {"label": "Safari", "cookie3": "safari", "cdp": False},
}


def _normalize_browser_name(browser: str) -> str:
    name = browser.strip().lower()
    if name not in BROWSER_META:
        supported = ", ".join(BROWSER_ORDER)
        raise ValueError(f"Unknown browser '{browser}'. Supported: {supported}, auto")
    return name


def _browser_executable_candidates(browser: str) -> list[Path]:
    """Return platform-specific executable paths to probe for *browser*."""
    system = platform.system()
    local = Path(os.environ.get("LOCALAPPDATA", ""))

    if browser == "helium":
        if system == "Darwin":
            return _helium_executable_candidates()
        if system == "Linux":
            return []
        return _helium_executable_candidates()

    if browser == "chrome":
        if system == "Darwin":
            return [Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")]
        if system == "Linux":
            return []  # resolved via shutil.which below
        return [
            Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
            Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
            local / "Google" / "Chrome" / "Application" / "chrome.exe",
        ]

    if browser == "edge":
        if system == "Darwin":
            return [Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge")]
        if system == "Linux":
            return []
        return [
            Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
            Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
            local / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        ]

    if browser == "brave":
        if system == "Darwin":
            return [Path("/Applications/Brave Browser.app/Contents/MacOS/Brave Browser")]
        if system == "Linux":
            return []
        return [
            Path(r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"),
            local / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe",
        ]

    if browser == "opera":
        if system == "Darwin":
            return [Path("/Applications/Opera.app/Contents/MacOS/Opera")]
        if system == "Linux":
            return []
        return [
            local / "Programs" / "Opera" / "opera.exe",
            Path(r"C:\Program Files\Opera\opera.exe"),
        ]

    if browser == "vivaldi":
        if system == "Darwin":
            return [Path("/Applications/Vivaldi.app/Contents/MacOS/Vivaldi")]
        if system == "Linux":
            return []
        return [local / "Vivaldi" / "Application" / "vivaldi.exe"]

    if browser == "chromium":
        if system == "Darwin":
            return [Path("/Applications/Chromium.app/Contents/MacOS/Chromium")]
        if system == "Linux":
            return []
        playwright_root = local / "ms-playwright"
        if playwright_root.is_dir():
            return sorted(
                playwright_root.glob("chromium-*/chrome-win64/chrome.exe"),
                reverse=True,
            )
        return []

    if browser == "firefox":
        if system == "Darwin":
            return [Path("/Applications/Firefox.app/Contents/MacOS/firefox")]
        if system == "Linux":
            return []
        return [
            Path(r"C:\Program Files\Mozilla Firefox\firefox.exe"),
            local / "Mozilla Firefox" / "firefox.exe",
        ]

    return []


def _linux_which_names(browser: str) -> tuple[str, ...]:
    return {
        "helium": ("helium", "helium-browser"),
        "chrome": ("google-chrome", "google-chrome-stable", "chrome"),
        "chromium": ("chromium", "chromium-browser"),
        "edge": ("microsoft-edge", "microsoft-edge-stable"),
        "brave": ("brave", "brave-browser"),
        "opera": ("opera",),
        "vivaldi": ("vivaldi", "vivaldi-stable"),
        "firefox": ("firefox",),
        "librewolf": ("librewolf",),
    }.get(browser, ())


def get_browser_executable(browser: str) -> str | None:
    """Return the executable path for *browser*, or ``None`` if not found."""
    name = _normalize_browser_name(browser)

    if platform.system() == "Linux":
        for candidate in _linux_which_names(name):
            found = shutil.which(candidate)
            if found:
                return found

    for path in _browser_executable_candidates(name):
        if path.exists():
            return str(path)

    return None


def list_detected_browsers() -> list[str]:
    """Return browser slugs that appear installed on this system."""
    detected: list[str] = []
    for name in BROWSER_ORDER:
        if name == "safari" and platform.system() != "Darwin":
            continue
        if get_browser_executable(name) is not None:
            detected.append(name)
    return detected


def get_cdp_browser_executable(browser: str | None = None) -> str | None:
    """Return a Chromium-based browser executable suitable for CDP login."""
    if browser is not None:
        name = _normalize_browser_name(browser)
        if not BROWSER_META[name]["cdp"]:
            raise ValueError(
                f"{BROWSER_META[name]['label']} does not support CDP login. "
                "Use --method browser to import cookies, or a Chromium-based browser."
            )
        return get_browser_executable(name)

    for name in BROWSER_ORDER:
        if not BROWSER_META[name]["cdp"]:
            continue
        path = get_browser_executable(name)
        if path:
            return path
    return None


def get_chrome_path() -> str | None:
    """Return a Chromium-based browser path (backward-compatible alias)."""
    return get_cdp_browser_executable()


def _find_available_port() -> int:
    """Find an available TCP port in the CDP range."""
    for offset in range(CDP_PORT_RANGE):
        port = CDP_PORT_START + offset
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("localhost", port))
                return port
        except OSError:
            continue
    raise RuntimeError(
        f"No available ports in range {CDP_PORT_START}–{CDP_PORT_START + CDP_PORT_RANGE - 1}. "
        "Close some applications and try again."
    )


# ---------------------------------------------------------------------------
# Chrome lifecycle
# ---------------------------------------------------------------------------

# Module-level reference so atexit can clean up
_chrome_process: subprocess.Popen | None = None


def _cleanup_chrome() -> None:
    """atexit handler — terminate Chrome if still running."""
    global _chrome_process
    if _chrome_process is not None:
        try:
            _chrome_process.terminate()
            _chrome_process.wait(timeout=5)
        except Exception:
            try:
                _chrome_process.kill()
            except Exception:
                pass
        _chrome_process = None


atexit.register(_cleanup_chrome)


def _remove_stale_locks(profile_dir: Path) -> None:
    """Remove stale Chrome lock files so a fresh instance can start.

    Chrome uses ``SingletonLock`` and ``SingletonSocket`` to enforce one
    instance per user-data-dir. If a previous run crashed or was killed,
    these locks are left behind and cause the next launch to immediately
    delegate to the (dead) "existing" instance and exit.
    """
    for name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
        lock = profile_dir / name
        try:
            lock.unlink(missing_ok=True)
        except OSError:
            pass


def _get_chrome_launch_args(port: int, *, headless: bool = False) -> list[str]:
    """Return Chrome CLI arguments for CDP login (without the executable)."""
    args = [
        f"--remote-debugging-port={port}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        f"--user-data-dir={CHROME_PROFILE_DIR}",
        "--remote-allow-origins=*",
    ]
    if headless:
        args.append("--headless=new")
    args.append(NOTEBOOKLM_URL)
    return args


def _wait_for_cdp_connection(port: int, timeout: int) -> None:
    """Poll until a CDP-enabled browser is reachable on *port*."""
    start = time.time()
    while time.time() - start < timeout:
        if _get_debugger_ws_url(port):
            return
        time.sleep(2)
    raise RuntimeError(
        f"No Chrome connection detected on port {port} after {timeout}s. "
        f"Make sure Chrome is running with --remote-debugging-port={port}."
    )


def _launch_chromium(
    port: int,
    browser_path: str | None = None,
    *,
    chrome_path: str | None = None,
    headless: bool = False,
) -> subprocess.Popen:
    """Launch a Chromium-based browser with remote debugging. Never uses ``shell=True``."""
    global _chrome_process

    resolved = browser_path or chrome_path or get_cdp_browser_executable()
    if not resolved:
        raise RuntimeError(
            "No Chromium-based browser found (Chrome, Edge, Brave, Chromium, …). "
            "Install one or pass --browser-path."
        )

    CHROME_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    _remove_stale_locks(CHROME_PROFILE_DIR)

    args = [resolved] + _get_chrome_launch_args(port, headless=headless)

    process = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    _chrome_process = process

    # Wait for Chrome to start, then verify it's still alive.
    # Chrome exits immediately when it delegates to an existing instance
    # with the same user-data-dir (the "3-second close" problem).
    #
    # On Windows, Chrome uses a multi-process architecture: the launcher
    # process exits with code 0 immediately while the actual browser runs
    # as a detached child process.  In that case the CDP port will still
    # become available, so we treat a code-0 exit as a warning rather
    # than an immediate error and fall through to the CDP check below.
    time.sleep(3)

    exit_code = process.poll()
    if exit_code is not None:
        if exit_code == 0 and _get_debugger_ws_url(port):
            # Windows launcher exited but the browser child is alive and
            # CDP is already responding — continue normally.
            logger.debug(
                "Chrome launcher exited (code 0) but CDP is live — Windows multi-process mode."
            )
        else:
            stderr_bytes = process.stderr.read() if process.stderr else b""
            stderr_text = stderr_bytes.decode(errors="replace").strip()
            hint = ""
            if stderr_text:
                hint = f"\nChrome stderr: {stderr_text[:500]}"
            raise RuntimeError(
                f"Chrome exited immediately (code {exit_code}). "
                "This usually means another Chrome instance is using the same profile. "
                "Close all Chrome windows and try again, or run:\n"
                f"  rm -rf {CHROME_PROFILE_DIR}/Singleton*"
                f"{hint}"
            )

    return process


# Backward-compatible alias used in tests
_launch_chrome = _launch_chromium


# ---------------------------------------------------------------------------
# Chrome DevTools Protocol helpers
# ---------------------------------------------------------------------------


def _get_debugger_ws_url(port: int, *, timeout: float = 5.0) -> str | None:
    """Get the browser-level WebSocket debugger URL."""
    import httpx

    try:
        resp = httpx.get(f"http://localhost:{port}/json/version", timeout=timeout)
        return resp.json().get("webSocketDebuggerUrl")
    except Exception:
        return None


def _cdp_ports_to_try() -> list[int]:
    """Ports to probe for a running Chromium browser with CDP enabled."""
    ports: list[int] = []
    env_port = os.environ.get("NOTEBOOKLM_CDP_PORT", "").strip()
    if env_port:
        for part in env_port.split(","):
            part = part.strip()
            if part.isdigit():
                ports.append(int(part))
    for offset in range(CDP_PORT_RANGE):
        port = CDP_PORT_START + offset
        if port not in ports:
            ports.append(port)
    return ports


def _find_cdp_port(*, timeout: float = 0.4) -> int | None:
    """Return the first localhost port that exposes a Chromium CDP endpoint."""
    for port in _cdp_ports_to_try():
        if _get_debugger_ws_url(port, timeout=timeout):
            return port
    return None


def _try_load_cookies_via_running_cdp() -> dict[str, str] | None:
    """Read Google cookies from a running Chromium browser via CDP.

    Works while the browser is open, but the browser must have been started
    with ``--remote-debugging-port`` (see ``enable_cdp_launcher``).
    """
    port = _find_cdp_port()
    if port is None:
        return None

    ws_url = _get_debugger_ws_url(port)
    if not ws_url:
        pages = _get_pages(port)
        if pages:
            ws_url = pages[0].get("webSocketDebuggerUrl")
    if not ws_url:
        return None

    try:
        return _extract_cookies_from_ws(ws_url)
    except Exception as exc:
        logger.debug("CDP cookie import failed on port %s: %s", port, exc)
        return None


def enable_cdp_launcher(browser: str = "helium", port: int = CDP_PORT_START) -> Path:
    """Create a launcher script that starts *browser* with remote debugging enabled.

    The user must start the browser through this launcher (or an equivalent
    shortcut) once so CDP cookie import works while the browser stays open.
    """
    name = _normalize_browser_name(browser)
    if not BROWSER_META[name]["cdp"]:
        raise ValueError(f"{BROWSER_META[name]['label']} does not support CDP.")

    executable = get_browser_executable(name)
    if not executable:
        raise RuntimeError(f"{BROWSER_META[name]['label']} executable not found.")

    label = BROWSER_META[name]["label"]
    system = platform.system()

    if system == "Windows":
        launcher = Path.home() / "Desktop" / f"{label} (MCP debug).cmd"
        content = (
            "@echo off\n"
            f'start "" "{executable}" --remote-debugging-port={port}\n'
        )
        launcher.write_text(content, encoding="utf-8")
        return launcher

    if system == "Darwin":
        launcher = Path.home() / "Desktop" / f"{label} (MCP debug).command"
        content = (
            "#!/bin/bash\n"
            f'exec "{executable}" --remote-debugging-port={port}\n'
        )
        launcher.write_text(content, encoding="utf-8")
        launcher.chmod(0o755)
        return launcher

    launcher = Path.home() / f"{name}-mcp-debug.sh"
    content = f'#!/bin/sh\nexec "{executable}" --remote-debugging-port={port}\n'
    launcher.write_text(content, encoding="utf-8")
    launcher.chmod(0o755)
    return launcher


def _get_pages(port: int) -> list[dict]:
    """List open pages via CDP HTTP API."""
    import httpx

    try:
        resp = httpx.get(f"http://localhost:{port}/json", timeout=5)
        return resp.json()
    except Exception:
        return []


def execute_cdp_command(ws_url: str, method: str, params: dict | None = None) -> dict:
    """Execute a single CDP command over WebSocket and return the result."""
    import websocket

    try:
        ws = websocket.create_connection(ws_url, timeout=30, suppress_origin=True)
    except TypeError:
        ws = websocket.create_connection(ws_url, timeout=30)

    try:
        command = {"id": 1, "method": method, "params": params or {}}
        ws.send(json.dumps(command))
        while True:
            response = json.loads(ws.recv())
            if response.get("id") == 1:
                return response.get("result", {})
    finally:
        ws.close()


def _get_page_cookies(ws_url: str) -> list[dict]:
    """Extract all cookies via ``Network.getAllCookies``."""
    result = execute_cdp_command(ws_url, "Network.getAllCookies")
    return result.get("cookies", [])


def _get_page_html(ws_url: str) -> str:
    """Get the page HTML via ``Runtime.evaluate``."""
    execute_cdp_command(ws_url, "Runtime.enable")
    result = execute_cdp_command(
        ws_url,
        "Runtime.evaluate",
        {"expression": "document.documentElement.outerHTML"},
    )
    return result.get("result", {}).get("value", "")


def _get_current_url(ws_url: str) -> str:
    """Get the current page URL."""
    execute_cdp_command(ws_url, "Runtime.enable")
    result = execute_cdp_command(
        ws_url,
        "Runtime.evaluate",
        {"expression": "window.location.href"},
    )
    return result.get("result", {}).get("value", "")


def _navigate_to_url(ws_url: str, url: str) -> None:
    """Navigate the page to *url* and wait for it to load."""
    execute_cdp_command(ws_url, "Page.enable")
    execute_cdp_command(ws_url, "Page.navigate", {"url": url})
    time.sleep(3)


# ---------------------------------------------------------------------------
# Token extraction helpers
# ---------------------------------------------------------------------------


def extract_csrf_from_html(html: str) -> str:
    """Extract the CSRF token (``SNlM0e``) from page HTML."""
    match = re.search(r'"SNlM0e":"([^"]+)"', html)
    return match.group(1) if match else ""


def extract_session_id_from_html(html: str) -> str:
    """Extract the session ID (``FdrFJe``) from page HTML."""
    for pattern in (r'"FdrFJe":"(\d+)"', r'f\.sid["\s:=]+["\']?(\d+)'):
        match = re.search(pattern, html)
        if match:
            return match.group(1)
    return ""


# ---------------------------------------------------------------------------
# Main authentication flow
# ---------------------------------------------------------------------------


def _extract_cookies_from_ws(ws_url: str) -> dict[str, str]:
    """Read essential Google cookies from a CDP page."""
    raw = _get_page_cookies(ws_url)
    cookies: dict[str, str] = {}
    for c in raw:
        name = c.get("name", "")
        domain = c.get("domain", "")
        if name in ESSENTIAL_COOKIES and ".google.com" in domain:
            cookies[name] = c.get("value", "")
    return cookies


def _extract_tokens_from_cdp_page(ws_url: str) -> AuthTokens:
    """Extract cookies, CSRF, and session ID from an open CDP page."""
    cookies = _extract_cookies_from_ws(ws_url)
    if not validate_cookies(cookies):
        missing = REQUIRED_COOKIES - cookies.keys()
        raise RuntimeError(f"Missing cookies: {', '.join(sorted(missing))}")

    try:
        current_url = _get_current_url(ws_url)
        if "notebooklm.google.com" not in current_url:
            _navigate_to_url(ws_url, NOTEBOOKLM_URL)
            time.sleep(2)
    except Exception:
        pass

    html = _get_page_html(ws_url)
    return AuthTokens(
        cookies=cookies,
        csrf_token=extract_csrf_from_html(html),
        session_id=extract_session_id_from_html(html),
        extracted_at=time.time(),
    )


def extract_cookies_via_cdp(
    port: int | None = None,
    login_timeout: int = 300,
    chrome_path: str | None = None,
    browser_path: str | None = None,
    browser: str | None = None,
    on_manual_launch_needed: Callable[[int, list[str]], None] | None = None,
    *,
    interactive: bool = True,
    headless: bool = False,
) -> AuthTokens:
    """Launch Chrome, wait for the user to log in, and extract auth tokens.

    This is the primary authentication entry point. It:

    1. Finds an available CDP port.
    2. Launches Chrome pointing at notebooklm.google.com.
    3. Waits for the user to complete Google OAuth.
    4. Extracts cookies, CSRF token, and session ID via CDP.
    5. Filters to essential cookies only.
    6. Cleans up the Chrome process in a ``finally`` block.

    If Chrome cannot be found and *on_manual_launch_needed* is provided,
    the callback is invoked with ``(port, launch_args)`` so the caller
    can display instructions for the user to launch Chrome manually.
    The function then waits for a CDP connection before continuing.

    Args:
        port: Explicit port to use (auto-detected if ``None``).
        login_timeout: Maximum seconds to wait for login.
        chrome_path: Explicit path to Chrome/Chromium executable.
        on_manual_launch_needed: Called when Chrome is not found, receives
            ``(port, launch_args)`` so the caller can show manual instructions.

    Returns:
        Populated :class:`AuthTokens`.

    Raises:
        RuntimeError: On Chrome launch failure, login timeout, or extraction error.
    """
    if port is None:
        port = _find_available_port()

    chrome_proc: subprocess.Popen | None = None
    explicit_path = browser_path or chrome_path
    if explicit_path:
        resolved = explicit_path
    elif browser is not None:
        name = _normalize_browser_name(browser)
        if not BROWSER_META[name]["cdp"]:
            raise RuntimeError(
                f"{BROWSER_META[name]['label']} does not support CDP login. "
                "Use --method browser instead."
            )
        resolved = get_browser_executable(name)
    else:
        resolved = get_cdp_browser_executable()

    try:
        if resolved:
            chrome_proc = _launch_chromium(port, resolved, headless=headless)
        elif on_manual_launch_needed:
            # Chrome not found — let the caller show manual instructions
            CHROME_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
            _remove_stale_locks(CHROME_PROFILE_DIR)
            on_manual_launch_needed(port, _get_chrome_launch_args(port, headless=headless))
            _wait_for_cdp_connection(port, login_timeout)
        else:
            raise RuntimeError("Google Chrome not found. Install Chrome or use --chrome-path.")

        # Find the NotebookLM page
        page = _find_notebooklm_page(port)
        if not page:
            raise RuntimeError("Failed to open NotebookLM page in Chrome.")

        ws_url = page.get("webSocketDebuggerUrl")
        if not ws_url:
            raise RuntimeError("No WebSocket URL for Chrome page — try restarting Chrome.")

        if not interactive:
            # Silent mode: profile should already be logged in
            start = time.time()
            while time.time() - start < login_timeout:
                try:
                    return _extract_tokens_from_cdp_page(ws_url)
                except RuntimeError:
                    time.sleep(2)
            raise RuntimeError(
                "Persistent Chrome profile is not logged in. "
                "Run: notebooklm-mcp-2026 login --method cdp"
            )

        # Interactive mode — wait for the user to complete Google OAuth.
        logger.info("Waiting for Google login…")
        start = time.time()

        while time.time() - start < login_timeout:
            try:
                cookies = _extract_cookies_from_ws(ws_url)
                if validate_cookies(cookies):
                    return _extract_tokens_from_cdp_page(ws_url)
            except Exception:
                pass
            time.sleep(2)
        else:
            raise RuntimeError(
                f"Login timed out after {login_timeout}s. "
                "Please log in to NotebookLM in the Chrome window."
            )

    finally:
        # Always clean up Chrome
        global _chrome_process
        proc = chrome_proc or _chrome_process
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            if _chrome_process is proc:
                _chrome_process = None


def _find_notebooklm_page(port: int, max_attempts: int = 5) -> dict | None:
    """Find an existing NotebookLM page or create one.

    Retries up to *max_attempts* times with 2-second delays because
    Chrome's CDP endpoint may not be ready immediately after launch.
    """
    import httpx
    from urllib.parse import quote

    for attempt in range(max_attempts):
        pages = _get_pages(port)
        for page in pages:
            if "notebooklm.google.com" in page.get("url", ""):
                return page

        # If we got pages but none match, try creating a new tab
        if pages:
            try:
                encoded = quote(NOTEBOOKLM_URL, safe="")
                resp = httpx.put(f"http://localhost:{port}/json/new?{encoded}", timeout=15)
                if resp.status_code == 200 and resp.text.strip():
                    return resp.json()

                # Fallback: blank tab + navigate
                resp = httpx.put(f"http://localhost:{port}/json/new", timeout=10)
                if resp.status_code == 200 and resp.text.strip():
                    page = resp.json()
                    ws_url = page.get("webSocketDebuggerUrl")
                    if ws_url:
                        _navigate_to_url(ws_url, NOTEBOOKLM_URL)
                    return page
            except Exception:
                pass

        # CDP not ready yet — wait and retry
        if attempt < max_attempts - 1:
            logger.debug(
                "CDP not ready yet (attempt %d/%d), retrying...", attempt + 1, max_attempts
            )
            time.sleep(2)

    return None
