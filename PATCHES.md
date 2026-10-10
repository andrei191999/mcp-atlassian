# Patches — upd/uni-335-336

Patches applied on top of `upd/v0.23.1` (commit `5be93a04`), branch `upd/uni-335-336`.

---

## Patch 1 — UNI-335: Write-tool confirmation meta

**Linear:** UNI-335
**Commit:** `025cbbc`
**Files changed:**
- `src/mcp_atlassian/servers/jira.py` — add `WRITE_TOOL_META` constant + 25 decorator changes
- `tests/unit/servers/test_jira_write_meta.py` — 4 tests (tool enumeration + wire)

**Rationale:**
Claude Code's `anthropic/requiresUserInteraction` tool meta flag causes the client to always prompt the user before executing a write tool, even under `--dangerously-skip-permissions` (bypass mode). Without it, automation in bypass mode can silently create/update/delete Jira items. Adding `meta=WRITE_TOOL_META` to every write-tagged `@jira_mcp.tool()` decorator is the lowest-risk approach — no FastMCP private API, explicit per-tool, easy to audit. A test asserts the invariant "write tag ⟺ meta flag" for every registered tool and will catch any new write tool that ships without the flag.

**Re-applying on upstream upgrade:**
1. Rebase `upd/uni-335-336` onto the new `upd/v0.23.x` base.
2. If conflicts appear in `servers/jira.py`, grep for new `tags={"jira", "write", ...}` decorators that lack `meta=WRITE_TOOL_META` and add it.
3. Run `grep -c 'meta=WRITE_TOOL_META' src/mcp_atlassian/servers/jira.py` and update `EXPECTED_WRITE_COUNT` in the test if the count changed.
4. Run `uv run pytest tests/unit/servers/test_jira_write_meta.py`.

---

## Patch 2 — UNI-336: PAT from OS keyring + `--store-jira-pat` CLI

**Linear:** UNI-336
**Commit:** `6b5146c`
**Files changed:**
- `src/mcp_atlassian/jira/config.py` — add `JIRA_PAT_KEYRING_SERVICE` constant + keyring fallback in `from_env()`
- `src/mcp_atlassian/__init__.py` — add `_read_pat_secret()` helper + `--store-jira-pat` CLI flag
- `tests/unit/jira/test_keyring_pat.py` — 12 tests (config logic + CLI)

**Rationale:**
The plugin's `.mcp.json` sets `JIRA_PERSONAL_TOKEN=${UPD_JIRA_TEST_TOKEN:-}` which evaluates to an empty string in normal use, preventing any stale inherited token from the shell. `JiraConfig.from_env()` now falls back to `get_jira_pat_from_keyring(url)` (shared helper in `utils/environment.py`) when the env var is empty and basic auth is not configured. The shared helper is also used in `_check_service_auth()` so `get_available_services()` returns `jira: True` and the lifespan loads JiraConfig. `--store-jira-pat` is modelled on `--oauth-setup`: it reads the PAT via `getpass` on a TTY or one stdin line when piped, stores it in the OS keyring, and exits 0. The token is never echoed, logged, or committed. `keyring.errors.KeyringError` is the only caught exception (no bare `except`). The keyring username is `jira_keyring_username(url)` (strip + rstrip("/")) so trailing-slash variants are handled symmetrically. Basic auth is checked before the keyring lookup so Basic-auth setups never touch the keyring.

**Windows keyring backend confirmed:** `keyring.backends.Windows.WinVaultKeyring (priority: 5)`
**Round-trip verified:** store → read back → delete under `http://127.0.0.1:1` with `dummy-pat-123`.

**Re-applying on upstream upgrade:**
1. Check `from_env()` in `jira/config.py` — if upstream added their own keyring logic, reconcile.
2. Check `__init__.py` click options — if upstream added options, the `store_jira_pat` parameter position in `main()` must match its decorator order.
3. Run `uv run pytest tests/unit/jira/test_keyring_pat.py`.

---

## Patch 3 — D5: Disable FastMCP startup update check

**Linear:** D5 (UNI-335 plan item)
**Commit:** `473dfa1`
**Files changed:**
- `src/mcp_atlassian/__init__.py` — one `os.environ.setdefault(...)` line before fastmcp import
- `tests/unit/test_fastmcp_update_check.py` — 3 tests

**Rationale:**
FastMCP 3.4.x checks for updates and prints a banner on every startup (`check_for_updates='stable'` default). This causes a network call and console noise in the plugin context. `os.environ.setdefault("FASTMCP_CHECK_FOR_UPDATES", "off")` is placed before `from fastmcp import settings` so that the pydantic-settings singleton reads `"off"` at creation time. `setdefault` is a no-op if the user explicitly sets the var, so their preference is respected. The `.mcp.json` in the plugin sets it as belt-and-suspenders.

**FastMCP setting confirmed:** field `check_for_updates: Literal['stable','prerelease','off']`, env var `FASTMCP_CHECK_FOR_UPDATES`, env_prefix `FASTMCP_`.

**Re-applying on upstream upgrade:**
1. Verify the env var name still matches in the new FastMCP version: `python -c "import fastmcp.settings; print(fastmcp.settings.model_fields['check_for_updates'])"`.
2. Ensure the `setdefault` line is still before the first `from fastmcp import ...` in `__init__.py`.
3. Run `uv run pytest tests/unit/test_fastmcp_update_check.py`.

---

## Patch 4 — D12: MCP_ATLASSIAN_DISABLE_DOTENV

**Linear:** D12 (plan item)
**Files changed:**
- `src/mcp_atlassian/__init__.py` — `_DISABLE_DOTENV` flag; skips `dotenv_values()` at import time and `load_dotenv()` in `main()`
- `tests/unit/test_disable_dotenv.py` — 2 subprocess tests

**Rationale:**
`find_dotenv()` walks up from the installed package directory, which on Windows includes `%APPDATA%\uv\tools\...` and ultimately reaches `C:\Users\<user>`. A `~/.env` there could inject `READ_ONLY_MODE=false`, `JIRA_SSL_VERIFY=false`, or proxy settings. Setting `MCP_ATLASSIAN_DISABLE_DOTENV=true` in the plugin's `.mcp.json` prevents both the import-time `dotenv_values()` call (used for the truststore setting) and the `load_dotenv(override=True)` call in `main()`. An explicit `--env-file` argument is unaffected when the flag is not set. The `_DISABLE_DOTENV` variable is computed before the `from dotenv import` line and uses inline `os.getenv` (not a general assignment that would trigger E402) — imports after module-level setup code carry `# noqa: E402`.

**Keyring URL rules (also in this patch):**
- `--store-jira-pat`: `http://` is only allowed for loopback hosts (localhost, 127.0.0.1, ::1, used for the fake Jira); `https://` is required for all other hosts. Atlassian Cloud URLs are rejected (Cloud uses username+API token, not a PAT stored in the keyring).
- `get_jira_pat_from_keyring()`: same loopback rule applied at lookup time, so a misconfigured `JIRA_URL` with `http://` on a non-loopback host cannot leak the PAT over plain text.
- Basic auth (username+api_token) is checked before the keyring lookup in `_check_service_auth()`, so Basic-auth setups never touch the keyring.

**Re-applying on upstream upgrade:**
1. Check `__init__.py` for any new `load_dotenv()` or `dotenv_values()` calls introduced upstream and gate them on `_DISABLE_DOTENV`.
2. Verify the loopback set `{"localhost","127.0.0.1","::1"}` in `utils/environment.py` is still appropriate.
3. Run `uv run pytest tests/unit/test_disable_dotenv.py tests/unit/jira/test_keyring_pat.py tests/unit/servers/test_blocker_e2e.py`.

---

## Patch 5 — D13: stdio no-credentials exit

**Linear:** D13 (plan item)
**Files changed:**
- `src/mcp_atlassian/__init__.py` — `_check_jira_stdio_creds()` helper + call in `main()` after CLI env vars are applied, before the server is imported
- `tests/unit/test_no_creds_exit.py` — 7 tests

**Exit condition:** transport is `stdio` AND `JIRA_URL` is non-empty AND `get_available_services()` returns nothing truthy for *either* jira or confluence. A Confluence-only setup (Jira URL set but only Confluence credentials present) does NOT trigger the exit. HTTP/SSE transports and header-based multi-tenant setups are unaffected.

**Message variants:**

Atlassian Cloud URL (no PAT suggestion — `--store-jira-pat` rejects Cloud):
```
mcp-atlassian: no Jira credentials found for <url>. Set JIRA_USERNAME and JIRA_API_TOKEN (Atlassian Cloud).
```

Env auth vars partially set (names vars, never values):
```
mcp-atlassian: incomplete Jira credentials in environment (<VAR1>, <VAR2>).
```

Server/DC, keyring backend raises KeyringError:
```
mcp-atlassian: keyring unavailable (<ErrorType>). Store your token with: mcp-atlassian --store-jira-pat --jira-url <url>
```

Server/DC, no token (README-quoted exact text):
```
mcp-atlassian: no Jira credentials found for <normalized-url>. Store your token with: mcp-atlassian --store-jira-pat --jira-url <url>
```

**Re-applying on upstream upgrade:**
1. Check that the D13 block in `main()` is still placed after all CLI-arg env-var assignments and before `from mcp_atlassian.servers import main_mcp`.
2. Run `uv run pytest tests/unit/test_no_creds_exit.py`.

---

## Patch 6 — D14: READ_ONLY_MODE set-but-empty → read-only

**Linear:** D14 (plan item)
**Files changed:**
- `src/mcp_atlassian/utils/io.py` — rewrites `is_read_only_mode()` with a three-way env-var check; logs WARNING when the fail-safe fires
- `tests/unit/test_read_only_empty_env.py` — 6 tests (5 unit + 1 e2e through `Client(main_mcp)`)

**Rationale:**
When a plugin writes `READ_ONLY_MODE=${user_config.read_only:-}` and the user has not configured the option, the shell expands the variable to an empty string. `os.getenv("READ_ONLY_MODE", "false")` returns `""` (not `"false"`) when the var is SET to empty, so the old `is_env_extended_truthy` check returned False — all 13 tools appeared instead of the 8 read-only default. The fix distinguishes three states: UNSET (→ False, preserves upstream default), SET-but-empty/whitespace (→ True, fail-safe), and SET-with-value (→ parsed truthy/falsy). A WARNING is logged when the fail-safe fires: `"READ_ONLY_MODE is set but empty; defaulting to read-only"`. The `--read-only` CLI path is unaffected because Click always writes `"true"` or `"false"` (never empty) into `os.environ`.

**Re-applying on upstream upgrade:**
1. Check `utils/io.py` — if upstream rewrote `is_read_only_mode()` with its own logic, merge the three-way distinction in.
2. Run `uv run pytest tests/unit/test_read_only_empty_env.py`.
