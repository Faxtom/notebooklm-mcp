# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.3.7] - 2026-06-18

### Fixed
- Helium multi-profile support: use `profile.last_used` from Local State (not always `Default`)
- CDP launcher passes `--profile-directory` for the active Helium profile
- CDP cookie import scans all open tabs/profiles and picks the best Google session

### Added
- `NOTEBOOKLM_HELIUM_PROFILE` env var to force a specific Helium profile (e.g. `Profile 1`)

## [0.3.6] - 2026-06-18

### Fixed
- `login --browser helium` no longer aborts after browser import when `--method` is `auto` (regression caused immediate failure instead of continuing)
- CDP cookie import: enable Network domain, navigate to NotebookLM, broader Google domain matching
- Clear message when CDP is active but Google session cookies are missing (sign in first)

## [0.3.5] - 2026-06-18

### Fixed
- Windows `enable-cdp` launcher now closes existing Helium processes before start so `--remote-debugging-port` is not ignored
- Launcher verifies CDP on port 9222 and prints `[OK]` / `[WARN]` feedback

### Changed
- CDP port discovery also reads Chromium `DevToolsActivePort` files
- Clearer troubleshooting when Helium is open but CDP is not active

## [0.3.3] - 2026-06-18

### Added
- CDP cookie import while Chromium browsers (Helium, Chrome, Edge, …) stay open on Windows
- `notebooklm-mcp-2026 enable-cdp` — creates a desktop launcher with `--remote-debugging-port=9222`
- `NOTEBOOKLM_CDP_PORT` for custom CDP ports during silent refresh

### Fixed
- Clear error when the cookie database is locked (browser open) instead of a generic admin/shadowcopy failure

## [0.3.2] - 2026-06-18

### Changed
- PyPI package renamed to `notebooklm-mcp-faxtom` (fork publish; upstream name owned by Julian)
- CLI command remains `notebooklm-mcp-2026`

## [0.3.1] - 2026-06-17

### Fixed
- Cross-platform auth tests for Linux CI matrix (Helium paths, Playwright Chromium detection)

## [0.3.0] - 2026-06-17

Fork by [@Faxtom](https://github.com/Faxtom) — based on [julianoczkowski/notebooklm-mcp-2026](https://github.com/julianoczkowski/notebooklm-mcp-2026).

### Added
- Multi-browser authentication (Chrome, Edge, Brave, Opera, Vivaldi, Firefox, Safari)
- First-class [Helium](https://github.com/imputnet/helium) browser support (cookie import + CDP login)
- `login --method browser` opens the browser automatically when no valid session is found
- `login` auto-verifies the account via real API call and configures MCP clients (no separate `setup` needed)
- Silent session refresh from installed browsers and persistent CDP profile
- `NOTEBOOKLM_BROWSER` and `NOTEBOOKLM_AUTH_REFRESH_COOLDOWN` environment variables
- Login flags: `--browser`, `--method`, `--skip-setup`, `--import-file`

### Changed
- `check_auth` validates credentials with a real `list_notebooks` API call
- `doctor` reports all detected browsers, not only Chrome
- README updated for the new one-command workflow

### Dependencies
- Added `browser-cookie3>=0.19.1`

## [0.2.1] - 2026-05-01

### Added
- Flow animation GIF in README
- Sponsor links: Buy Me a Coffee and Ko-fi (`.github/FUNDING.yml` + README badges)
- `/cleanup-branches` skill for post-merge branch cleanup
- `/sync-docs` skill to keep CLAUDE.md and CHANGELOG.md in sync
- Unit tests for `_launch_chrome` covering Windows multi-process launcher behavior

### Fixed
- Windows Chrome login crash: launcher process exits with code 0 immediately
  while the browser runs as a detached child. `_launch_chrome` now treats a
  code-0 exit as success when CDP is reachable, so login no longer fails on
  Windows (#19, thanks @WillWetzel)

## [0.2.0] - 2026-02-15

### Added
- Windows CI (ubuntu, macos, windows matrix)
- Code coverage with pytest-cov
- `--debug` flag on all CLI subcommands
- `--dry-run` flag on `setup` command
- Pre-commit hooks (ruff check + ruff format)
- Unit tests for all 9 MCP tool functions (`test_tools.py`)
- Example scripts (`examples/basic_workflow.py`, `examples/follow_up_conversation.py`)
- SECURITY.md with threat model and trust boundaries
- CONTRIBUTING.md, CODE_OF_CONDUCT.md, CHANGELOG.md
- CODEOWNERS, PR template, issue templates
- Dependabot for pip and GitHub Actions dependencies
- `[project.urls]` in pyproject.toml (Homepage, Repository, Issues, Changelog)
- Example JSON outputs in README
- "Getting Help" section in README

### Changed
- Improved error messages: rate limit hints, doctor command suggestions
- Hero image in README updated and set to full width

## [0.1.2] - 2026-02-14

### Added
- Branded help screen as default CLI command

### Fixed
- Ruff lint: removed extraneous f-string prefix

## [0.1.1] - 2026-02-14

### Added
- `logout` command to clear stored credentials
- Platform-specific prerequisites in README

### Changed
- Rewrote README for zero-friction onboarding
- Recommend `pipx` as primary install method

## [0.1.0] - 2026-02-14

### Added
- Initial release
- MCP server with 9 tools for querying NotebookLM notebooks
- Chrome CDP cookie extraction for authentication
- Branded CLI with `serve`, `login`, `status`, and `doctor` commands
- CI/CD pipelines for testing and PyPI publishing
