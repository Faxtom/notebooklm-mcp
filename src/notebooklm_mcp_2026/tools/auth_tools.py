"""Authentication tools — login and check_auth."""

from __future__ import annotations

import time
from typing import Any


def login(timeout: int = 300) -> dict[str, Any]:
    """Refresh authentication without opening Chrome when possible.

    Tries importing cookies from the system Chrome profile first, then
    silent profile refresh, then interactive CDP as a last resort.

    Args:
        timeout: Maximum seconds to wait for interactive CDP login (default: 300).

    Returns:
        Status dict with cookie count on success, or error message.
    """
    from ..auth import (
        extract_cookies_from_browser,
        extract_cookies_via_cdp,
        get_cdp_browser_executable,
        save_tokens,
        try_silent_token_refresh,
    )

    try:
        tokens = try_silent_token_refresh(force=True)
        if tokens is None:
            try:
                tokens = extract_cookies_from_browser()
            except Exception:
                if get_cdp_browser_executable() is not None:
                    tokens = extract_cookies_via_cdp(login_timeout=timeout)
                else:
                    raise
        save_tokens(tokens)
        return {
            "status": "success",
            "message": f"Authenticated successfully. Saved {len(tokens.cookies)} cookies.",
            "has_csrf": bool(tokens.csrf_token),
            "has_session_id": bool(tokens.session_id),
        }
    except RuntimeError as e:
        return {"status": "error", "error": str(e)}
    except Exception as e:
        return {"status": "error", "error": f"Login failed: {e}"}


def check_auth() -> dict[str, Any]:
    """Check if stored credentials are valid.

    Loads saved tokens from disk and attempts to validate them by
    fetching the NotebookLM homepage. No browser window is needed.

    Returns:
        Status dict indicating authenticated, expired, or not found.
    """
    from ..auth import load_tokens

    tokens = load_tokens()
    if tokens is None:
        return {
            "status": "not_authenticated",
            "message": "No saved credentials found. Run 'notebooklm-mcp-2026 login' first.",
        }

    # Validate with a real API call (homepage CSRF alone can look valid while RPC fails)
    from ..client import NotebookLMClient, AuthenticationError, APIError

    try:
        client = NotebookLMClient(
            cookies=tokens.cookies,
            csrf_token=tokens.csrf_token,
            session_id=tokens.session_id,
        )
        client.list_notebooks()
        client.close()

        age_hours = (time.time() - tokens.extracted_at) / 3600
        return {
            "status": "authenticated",
            "message": "Credentials are valid.",
            "cookie_count": len(tokens.cookies),
            "age_hours": round(age_hours, 1),
        }
    except APIError as e:
        return {
            "status": "error",
            "error": f"API validation failed: {e}",
        }
    except AuthenticationError as e:
        # Last attempt: silent refresh before reporting expired
        from ..auth import try_silent_token_refresh

        refreshed = try_silent_token_refresh(force=True)
        if refreshed is not None:
            try:
                client = NotebookLMClient(
                    cookies=refreshed.cookies,
                    csrf_token=refreshed.csrf_token,
                    session_id=refreshed.session_id,
                )
                client.list_notebooks()
                client.close()
                age_hours = (time.time() - refreshed.extracted_at) / 3600
                return {
                    "status": "authenticated",
                    "message": "Credentials refreshed automatically.",
                    "cookie_count": len(refreshed.cookies),
                    "age_hours": round(age_hours, 1),
                }
            except AuthenticationError:
                pass

        return {
            "status": "expired",
            "message": str(e),
            "hint": (
                "Run 'notebooklm-mcp-2026 login' (auto-imports from Chrome) "
                "or 'notebooklm-mcp-2026 login --method cdp'."
            ),
        }
    except Exception as e:
        return {
            "status": "error",
            "error": f"Validation failed: {e}",
        }
