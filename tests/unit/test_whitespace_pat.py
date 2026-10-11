"""Tests for whitespace-only JIRA_PERSONAL_TOKEN treated as unset (D14b follow-up)."""

import os
import subprocess
import sys
from unittest.mock import patch

_AUTH_VARS = (
    "JIRA_URL",
    "JIRA_PAT",
    "JIRA_PERSONAL_TOKEN",
    "JIRA_USERNAME",
    "JIRA_API_TOKEN",
    "JIRA_CLIENT_CERT",
    "JIRA_OAUTH_CLIENT_ID",
    "JIRA_OAUTH_CLIENT_SECRET",
    "JIRA_OAUTH_ACCESS_TOKEN",
    "CONFLUENCE_URL",
    "CONFLUENCE_PERSONAL_TOKEN",
    "ATLASSIAN_OAUTH_CLIENT_ID",
    "ATLASSIAN_OAUTH_CLIENT_SECRET",
    "ATLASSIAN_OAUTH_ACCESS_TOKEN",
    "ATLASSIAN_OAUTH_CLOUD_ID",
    "ATLASSIAN_EXTERNAL_AUTH_ENABLE",
    "ATLASSIAN_OAUTH_ENABLE",
)


def _clean_env(**overrides: str) -> dict[str, str]:
    """Inherit OS env, wipe any Jira/Atlassian auth that might be set."""
    env = dict(os.environ)
    for key in _AUTH_VARS:
        env.pop(key, None)
    env["MCP_ATLASSIAN_DISABLE_DOTENV"] = "true"
    env.update(overrides)
    return env


def _clear_auth(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Clear all auth env vars via monkeypatch for in-process tests."""
    for var in _AUTH_VARS:
        monkeypatch.delenv(var, raising=False)


# ---------------------------------------------------------------------------
# Test a: whitespace PAT falls back to keyring (in-process)
# ---------------------------------------------------------------------------


def test_whitespace_pat_falls_back_to_keyring(monkeypatch):
    """JIRA_PERSONAL_TOKEN='   ' is treated as unset; keyring fallback runs."""
    _clear_auth(monkeypatch)
    monkeypatch.setenv("JIRA_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("JIRA_PERSONAL_TOKEN", "   ")

    with patch(
        "mcp_atlassian.utils.environment.get_jira_pat_from_keyring",
        return_value="dummy-keyring-pat",
    ):
        from mcp_atlassian.utils.environment import get_available_services

        services = get_available_services()

    assert services.get("jira") is True


# ---------------------------------------------------------------------------
# Test b: whitespace PAT + no keyring → D13 exits 1 (subprocess)
# ---------------------------------------------------------------------------

_INVOKE = "from mcp_atlassian import main; main()"


def test_whitespace_pat_no_keyring_d13_exits():
    """Whitespace JIRA_PERSONAL_TOKEN + null keyring → exit 1 with one-line stderr."""
    result = subprocess.run(
        [sys.executable, "-c", _INVOKE],
        input=b"",
        capture_output=True,
        timeout=30,
        env=_clean_env(
            JIRA_URL="http://127.0.0.1:9",
            JIRA_PERSONAL_TOKEN="   ",
            PYTHON_KEYRING_BACKEND="keyring.backends.null.Keyring",
        ),
    )
    assert result.returncode == 1
    assert result.stdout == b""
    stderr = result.stderr.decode("utf-8", errors="replace")
    assert "no Jira credentials found" in stderr, repr(stderr)
    assert len(stderr.splitlines()) == 1, (
        f"Expected exactly 1 stderr line, got:\n{stderr}"
    )


# ---------------------------------------------------------------------------
# Test c: JiraConfig.from_env with whitespace PAT uses keyring token
# ---------------------------------------------------------------------------


def test_config_from_env_whitespace_pat_uses_keyring():
    """JiraConfig.from_env() with whitespace JIRA_PERSONAL_TOKEN falls back to keyring."""
    env = {
        "JIRA_URL": "https://jira.example.com/",
        "JIRA_PERSONAL_TOKEN": "   ",
    }
    with (
        patch.dict("os.environ", env, clear=True),
        patch(
            "mcp_atlassian.jira.config.get_jira_pat_from_keyring",
            return_value="keyring-pat-value",
        ),
    ):
        from mcp_atlassian.jira.config import JiraConfig

        config = JiraConfig.from_env()

    assert config.personal_token == "keyring-pat-value"
