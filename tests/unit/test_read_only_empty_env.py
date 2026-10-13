"""Tests for D14: READ_ONLY_MODE set but empty/whitespace → read-only = True."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Unit tests for is_read_only_mode()
# ---------------------------------------------------------------------------


def test_unset_is_false(monkeypatch):
    """UNSET READ_ONLY_MODE keeps upstream default: False."""
    monkeypatch.delenv("READ_ONLY_MODE", raising=False)
    from mcp_atlassian.utils.io import is_read_only_mode

    assert is_read_only_mode() is False


def test_empty_string_is_true(monkeypatch, caplog):
    """SET but empty READ_ONLY_MODE → True (fail-safe) with a WARNING."""
    monkeypatch.setenv("READ_ONLY_MODE", "")
    with caplog.at_level(logging.WARNING):
        from mcp_atlassian.utils.io import is_read_only_mode

        result = is_read_only_mode()
    assert result is True
    assert any("empty" in r.message.lower() for r in caplog.records)


def test_whitespace_only_is_true(monkeypatch, caplog):
    """SET but whitespace-only READ_ONLY_MODE → True (fail-safe) with a WARNING."""
    monkeypatch.setenv("READ_ONLY_MODE", "  ")
    with caplog.at_level(logging.WARNING):
        from mcp_atlassian.utils.io import is_read_only_mode

        result = is_read_only_mode()
    assert result is True
    assert any("empty" in r.message.lower() for r in caplog.records)


def test_false_string_is_false(monkeypatch):
    """READ_ONLY_MODE='false' → False."""
    monkeypatch.setenv("READ_ONLY_MODE", "false")
    from mcp_atlassian.utils.io import is_read_only_mode

    assert is_read_only_mode() is False


def test_true_string_is_true(monkeypatch):
    """READ_ONLY_MODE='true' → True."""
    monkeypatch.setenv("READ_ONLY_MODE", "true")
    from mcp_atlassian.utils.io import is_read_only_mode

    assert is_read_only_mode() is True


# ---------------------------------------------------------------------------
# F7: Parametrized truthy / falsy values
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value", ["true", "True", "TRUE", "1", "yes", "YES", "y", "Y", "on", "ON"]
)
def test_truthy_values(monkeypatch, value):
    """All canonical truthy strings → True."""
    monkeypatch.setenv("READ_ONLY_MODE", value)
    from mcp_atlassian.utils.io import is_read_only_mode

    assert is_read_only_mode() is True


@pytest.mark.parametrize(
    "value",
    ["false", "False", "FALSE", "0", "no", "NO", "n", "N", "off", "OFF"],
)
def test_falsy_explicit_values(monkeypatch, value):
    """Explicit recognised-falsy strings → False."""
    monkeypatch.setenv("READ_ONLY_MODE", value)
    from mcp_atlassian.utils.io import is_read_only_mode

    assert is_read_only_mode() is False


@pytest.mark.parametrize(
    "value",
    ["random", "${user_config.read_only}", "ture"],
)
def test_unrecognized_value_is_true_with_warning(monkeypatch, caplog, value):
    """Unrecognised (non-empty, non-whitespace) value → True (fail-closed) + WARNING."""
    monkeypatch.setenv("READ_ONLY_MODE", value)
    with caplog.at_level(logging.WARNING):
        from mcp_atlassian.utils.io import is_read_only_mode

        result = is_read_only_mode()
    assert result is True
    assert any("unrecognized" in r.message.lower() for r in caplog.records)


# ---------------------------------------------------------------------------
# End-to-end: empty READ_ONLY_MODE → only 8 read tools exposed
# ---------------------------------------------------------------------------

_THE_13_TOOLS = [
    "jira_get_issue",
    "jira_search",
    "jira_get_project_issues",
    "jira_get_transitions",
    "jira_get_user_profile",
    "jira_get_all_projects",
    "jira_search_assignable_users",
    "jira_get_link_types",
    "jira_create_issue",
    "jira_update_issue",
    "jira_add_comment",
    "jira_transition_issue",
    "jira_create_issue_link",
]
_THE_5_WRITE_TOOLS = {
    "jira_create_issue",
    "jira_update_issue",
    "jira_add_comment",
    "jira_transition_issue",
    "jira_create_issue_link",
}
_THE_8_READ_TOOLS = set(_THE_13_TOOLS) - _THE_5_WRITE_TOOLS
_ENABLED_TOOLS_CSV = ",".join(_THE_13_TOOLS)


def _make_fake_jira_config() -> MagicMock:
    from mcp_atlassian.jira.config import JiraConfig

    cfg = MagicMock(spec=JiraConfig)
    cfg.url = "http://127.0.0.1:9"
    cfg.is_cloud = False
    cfg.auth_type = "pat"
    cfg.is_auth_configured.return_value = True
    return cfg


@pytest.mark.anyio
# F4 note: this test uses Client(main_mcp) rather than spawning the CLI subprocess.
# The CLI's main() only writes READ_ONLY_MODE when --read-only is explicitly provided
# (was_option_provided check), so READ_ONLY_MODE="" in env is preserved as-is.
# The server enforces read-only at both list_tools AND call_tool time (via
# _is_tool_authorized), so the in-process test covers the full security boundary.
# A subprocess test would require a full MCP JSON-RPC handshake (~30 lines) but
# would not exercise any code path that this test does not already cover.
async def test_e2e_empty_read_only_mode_gives_8_read_tools():
    """READ_ONLY_MODE='' + ENABLED_TOOLS=13 → exactly the 8 read tools listed."""
    from fastmcp import Client

    from mcp_atlassian.servers.main import main_mcp

    env = {
        "JIRA_URL": "http://127.0.0.1:9",
        "JIRA_PERSONAL_TOKEN": "",
        "READ_ONLY_MODE": "",
        "TOOLSETS": "all",
        "ENABLED_TOOLS": _ENABLED_TOOLS_CSV,
    }

    fake_jira_config = _make_fake_jira_config()

    with (
        patch.dict("os.environ", env, clear=False),
        patch(
            "mcp_atlassian.utils.environment.get_jira_pat_from_keyring",
            return_value="dummy-pat-123",
        ),
        patch(
            "mcp_atlassian.servers.main.JiraConfig.from_env",
            return_value=fake_jira_config,
        ),
    ):
        async with Client(main_mcp) as client:
            raw_tools = await client.list_tools()

    listed_names = {t.name for t in raw_tools}
    assert listed_names == _THE_8_READ_TOOLS, (
        f"Listed tools mismatch.\n"
        f"  Extra: {listed_names - _THE_8_READ_TOOLS}\n"
        f"  Missing: {_THE_8_READ_TOOLS - listed_names}"
    )
