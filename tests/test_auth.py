"""Tests for the auth module."""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from notebooklm_mcp_2026 import auth
from notebooklm_mcp_2026.auth import (
    AuthTokens,
    build_tokens_from_cookies,
    extract_csrf_from_html,
    extract_session_id_from_html,
    filter_essential_cookies,
    import_cookies_from_file,
    load_tokens,
    save_tokens,
    validate_cookies,
)


class TestAuthTokens:
    def test_round_trip(self, sample_cookies, sample_csrf_token):
        tokens = AuthTokens(
            cookies=sample_cookies,
            csrf_token=sample_csrf_token,
            session_id="12345",
            extracted_at=1700000000.0,
        )
        data = tokens.to_dict()
        restored = AuthTokens.from_dict(data)
        assert restored.cookies == sample_cookies
        assert restored.csrf_token == sample_csrf_token
        assert restored.session_id == "12345"
        assert restored.extracted_at == 1700000000.0

    def test_from_dict_missing_fields(self):
        tokens = AuthTokens.from_dict({"cookies": {"SID": "x"}})
        assert tokens.cookies == {"SID": "x"}
        assert tokens.csrf_token == ""
        assert tokens.session_id == ""

    def test_from_dict_empty(self):
        tokens = AuthTokens.from_dict({})
        assert tokens.cookies == {}


class TestSaveLoadTokens:
    def test_save_and_load(self, sample_cookies, tmp_path):
        auth_file = tmp_path / "auth.json"
        tokens = AuthTokens(cookies=sample_cookies, csrf_token="csrf123")

        with patch("notebooklm_mcp_2026.auth.AUTH_FILE", auth_file), \
             patch("notebooklm_mcp_2026.auth.STORAGE_DIR", tmp_path):
            save_tokens(tokens)
            loaded = load_tokens()

        assert loaded is not None
        assert loaded.cookies == sample_cookies
        assert loaded.csrf_token == "csrf123"

    def test_file_permissions(self, sample_cookies, tmp_path):
        auth_file = tmp_path / "auth.json"
        tokens = AuthTokens(cookies=sample_cookies)

        with patch("notebooklm_mcp_2026.auth.AUTH_FILE", auth_file), \
             patch("notebooklm_mcp_2026.auth.STORAGE_DIR", tmp_path):
            save_tokens(tokens)

        if os.name != "nt":  # Skip on Windows
            mode = auth_file.stat().st_mode & 0o777
            assert mode == 0o600

    def test_load_missing_file(self, tmp_path):
        with patch("notebooklm_mcp_2026.auth.AUTH_FILE", tmp_path / "nonexistent.json"):
            assert load_tokens() is None

    def test_load_corrupt_file(self, tmp_path):
        auth_file = tmp_path / "auth.json"
        auth_file.write_text("not valid json{{{")
        with patch("notebooklm_mcp_2026.auth.AUTH_FILE", auth_file):
            assert load_tokens() is None

    def test_load_empty_cookies(self, tmp_path):
        auth_file = tmp_path / "auth.json"
        auth_file.write_text(json.dumps({"cookies": {}}))
        with patch("notebooklm_mcp_2026.auth.AUTH_FILE", auth_file):
            assert load_tokens() is None


class TestValidateCookies:
    def test_valid(self, sample_cookies):
        assert validate_cookies(sample_cookies) is True

    def test_missing_required(self):
        cookies = {"SID": "x", "HSID": "y"}  # Missing SSID, APISID, SAPISID
        assert validate_cookies(cookies) is False

    def test_empty(self):
        assert validate_cookies({}) is False


class TestFilterEssentialCookies:
    def test_keeps_essential_only(self, sample_cookies):
        extra = {**sample_cookies, "NID": "noise", "1P_JAR": "noise"}
        filtered = filter_essential_cookies(extra)
        assert "NID" not in filtered
        assert filtered["SID"] == sample_cookies["SID"]


class TestImportCookiesFromFile:
    def test_flat_dict(self, sample_cookies, tmp_path):
        path = tmp_path / "cookies.json"
        path.write_text(json.dumps(sample_cookies))
        with patch("notebooklm_mcp_2026.auth.build_tokens_from_cookies") as mock_build:
            mock_build.return_value = AuthTokens(cookies=sample_cookies)
            result = import_cookies_from_file(path)
        mock_build.assert_called_once()
        assert result.cookies == sample_cookies

    def test_nested_cookies_key(self, sample_cookies, tmp_path):
        path = tmp_path / "cookies.json"
        path.write_text(json.dumps({"cookies": sample_cookies}))
        with patch("notebooklm_mcp_2026.auth.build_tokens_from_cookies") as mock_build:
            mock_build.return_value = AuthTokens(cookies=sample_cookies)
            import_cookies_from_file(path)
        mock_build.assert_called_once_with(sample_cookies)

    def test_devtools_list_format(self, tmp_path):
        path = tmp_path / "cookies.json"
        path.write_text(json.dumps([
            {"name": "SID", "value": "abc"},
            {"name": "HSID", "value": "def"},
        ]))
        with patch("notebooklm_mcp_2026.auth.build_tokens_from_cookies") as mock_build:
            mock_build.return_value = AuthTokens(cookies={"SID": "abc"})
            import_cookies_from_file(path)
        mock_build.assert_called_once_with({"SID": "abc", "HSID": "def"})


class TestBuildTokensFromCookies:
    def test_missing_required_raises(self):
        with pytest.raises(RuntimeError, match="Missing required"):
            build_tokens_from_cookies({"SID": "only-one"})

    def test_fetches_csrf(self, sample_cookies):
        html = '"SNlM0e":"csrf-from-page"'
        mock_resp = MagicMock()
        mock_resp.url = "https://notebooklm.google.com/"
        mock_resp.status_code = 200
        mock_resp.text = html

        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("httpx.Client", return_value=mock_client):
            tokens = build_tokens_from_cookies(sample_cookies)

        assert tokens.csrf_token == "csrf-from-page"
        assert tokens.cookies["SID"] == sample_cookies["SID"]


class TestHeliumSupport:
    def test_user_data_dir_windows(self):
        from notebooklm_mcp_2026.auth import helium_user_data_dir

        with patch.dict(os.environ, {"LOCALAPPDATA": r"C:\Users\Test\AppData\Local"}), \
             patch("notebooklm_mcp_2026.auth.platform.system", return_value="Windows"):
            path = helium_user_data_dir()
        assert path == Path(r"C:\Users\Test\AppData\Local\imput\Helium\User Data")

    def test_user_data_dir_macos(self):
        from notebooklm_mcp_2026.auth import helium_user_data_dir

        with patch("notebooklm_mcp_2026.auth.platform.system", return_value="Darwin"):
            path = helium_user_data_dir()
        assert path.name == "net.imput.helium"

    def test_cookie_db_paths(self, tmp_path):
        from notebooklm_mcp_2026.auth import helium_cookie_db_paths

        user_data = tmp_path / "User Data"
        profile = user_data / "Default" / "Network"
        profile.mkdir(parents=True)
        cookies = profile / "Cookies"
        cookies.write_bytes(b"sqlite")
        (user_data / "Local State").write_text("{}")

        with patch("notebooklm_mcp_2026.auth.helium_user_data_dir", return_value=user_data):
            paths = helium_cookie_db_paths()

        assert paths is not None
        assert paths[0] == cookies

    def test_executable_candidates_versioned(self, tmp_path):
        from notebooklm_mcp_2026.auth import _helium_executable_candidates

        app = tmp_path / "imput" / "Helium" / "Application" / "145.0.0.0"
        app.mkdir(parents=True)
        exe = app / "chrome.exe"
        exe.write_text("")

        with patch.dict(os.environ, {"LOCALAPPDATA": str(tmp_path)}), \
             patch("notebooklm_mcp_2026.auth.platform.system", return_value="Windows"):
            found = _helium_executable_candidates()

        assert str(exe) in [str(p) for p in found]

    @patch("notebooklm_mcp_2026.auth.helium_cookie_db_paths")
    def test_load_helium_cookies(self, mock_paths, sample_cookies):
        mock_paths.return_value = (Path("/fake/Cookies"), Path("/fake/Local State"))
        cookie = MagicMock()
        cookie.name = "SID"
        cookie.value = sample_cookies["SID"]

        import browser_cookie3

        with patch.object(browser_cookie3, "chrome", return_value=[cookie]) as mock_chrome:
            from notebooklm_mcp_2026.auth import _load_helium_cookies

            cookies = _load_helium_cookies()
        assert cookies["SID"] == sample_cookies["SID"]
        mock_chrome.assert_called_once()

    @patch("notebooklm_mcp_2026.auth._load_helium_cookies")
    @patch("notebooklm_mcp_2026.auth.build_tokens_from_cookies")
    def test_extract_helium_browser(self, mock_build, mock_load, sample_cookies):
        mock_load.return_value = sample_cookies
        mock_build.return_value = AuthTokens(cookies=sample_cookies)

        from notebooklm_mcp_2026.auth import extract_cookies_from_browser

        extract_cookies_from_browser(browser="helium")
        mock_load.assert_called_once()


class TestBrowserSupport:
    def test_normalize_unknown_browser(self):
        from notebooklm_mcp_2026.auth import _normalize_browser_name

        with pytest.raises(ValueError, match="Unknown browser"):
            _normalize_browser_name("internet-explorer")

    def test_chromium_detected_on_windows_playwright(self):
        from notebooklm_mcp_2026.auth import get_browser_executable

        with patch("notebooklm_mcp_2026.auth.platform.system", return_value="Windows"), \
             patch.object(Path, "exists", return_value=True):
            path = get_browser_executable("chromium")
        assert path is not None

    @patch("notebooklm_mcp_2026.auth._load_cookies_with_browser_cookie3")
    @patch("notebooklm_mcp_2026.auth.build_tokens_from_cookies")
    def test_extract_from_specific_browser(self, mock_build, mock_load, sample_cookies):
        mock_load.return_value = sample_cookies
        mock_build.return_value = AuthTokens(cookies=sample_cookies)

        from notebooklm_mcp_2026.auth import extract_cookies_from_browser

        tokens = extract_cookies_from_browser(browser="firefox")
        mock_load.assert_called_once_with("firefox")
        assert tokens.cookies == sample_cookies

    @patch("notebooklm_mcp_2026.auth._load_cookies_with_browser_cookie3")
    def test_extract_tries_multiple_browsers(self, mock_load, sample_cookies):
        mock_load.side_effect = [RuntimeError("fail"), sample_cookies]

        from notebooklm_mcp_2026.auth import extract_cookies_from_browser

        with patch("notebooklm_mcp_2026.auth.build_tokens_from_cookies") as mock_build:
            mock_build.return_value = AuthTokens(cookies=sample_cookies)
            extract_cookies_from_browser()

        assert mock_load.call_count == 2


class TestExtractCsrf:
    def test_extracts_token(self):
        html = 'some stuff "SNlM0e":"AHBxJ9q_test_token" more stuff'
        assert extract_csrf_from_html(html) == "AHBxJ9q_test_token"

    def test_no_token(self):
        assert extract_csrf_from_html("<html>no token here</html>") == ""

    def test_empty_html(self):
        assert extract_csrf_from_html("") == ""


class TestExtractSessionId:
    def test_extracts_fdrfje(self):
        html = 'stuff "FdrFJe":"1234567890" more'
        assert extract_session_id_from_html(html) == "1234567890"

    def test_extracts_fsid_pattern(self):
        html = 'f.sid="9876543210"'
        assert extract_session_id_from_html(html) == "9876543210"

    def test_no_session_id(self):
        assert extract_session_id_from_html("<html>nothing</html>") == ""


class TestLaunchChrome:
    """Cover the Windows multi-process launcher behavior in _launch_chrome."""

    def _patches(self, popen_mock):
        return [
            patch("notebooklm_mcp_2026.auth.subprocess.Popen", return_value=popen_mock),
            patch("notebooklm_mcp_2026.auth.time.sleep"),
            patch("notebooklm_mcp_2026.auth._remove_stale_locks"),
            patch("notebooklm_mcp_2026.auth.CHROME_PROFILE_DIR", MagicMock()),
        ]

    def _enter(self, patches):
        for p in patches:
            p.start()

    def _exit(self, patches):
        for p in patches:
            p.stop()

    def test_windows_multi_process_exit_with_live_cdp_succeeds(self):
        process = MagicMock()
        process.poll.return_value = 0  # launcher exited cleanly
        patches = self._patches(process)
        self._enter(patches)
        try:
            with patch(
                "notebooklm_mcp_2026.auth._get_debugger_ws_url",
                return_value="ws://localhost:9222/devtools/browser/abc",
            ):
                result = auth._launch_chrome(9222, chrome_path="/fake/chrome")
            assert result is process
        finally:
            self._exit(patches)

    def test_exit_with_no_cdp_raises(self):
        process = MagicMock()
        process.poll.return_value = 0
        process.stderr.read.return_value = b""
        patches = self._patches(process)
        self._enter(patches)
        try:
            with patch("notebooklm_mcp_2026.auth._get_debugger_ws_url", return_value=None):
                with pytest.raises(RuntimeError, match="Chrome exited immediately"):
                    auth._launch_chrome(9222, chrome_path="/fake/chrome")
        finally:
            self._exit(patches)

    def test_nonzero_exit_raises_even_if_cdp_responds(self):
        process = MagicMock()
        process.poll.return_value = 1  # real failure
        process.stderr.read.return_value = b"profile in use"
        patches = self._patches(process)
        self._enter(patches)
        try:
            with patch(
                "notebooklm_mcp_2026.auth._get_debugger_ws_url",
                return_value="ws://localhost:9222/devtools/browser/abc",
            ):
                with pytest.raises(RuntimeError, match="Chrome exited immediately"):
                    auth._launch_chrome(9222, chrome_path="/fake/chrome")
        finally:
            self._exit(patches)

    def test_running_process_returned(self):
        process = MagicMock()
        process.poll.return_value = None  # still running
        patches = self._patches(process)
        self._enter(patches)
        try:
            result = auth._launch_chrome(9222, chrome_path="/fake/chrome")
            assert result is process
        finally:
            self._exit(patches)
