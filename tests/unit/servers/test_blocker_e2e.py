"""Tests for the UNI-336 blocker fix and end-to-end tool listing through main_mcp.

4a: get_available_services() correctly detects Jira when PAT comes from keyring.
4b: Client(main_mcp) lists exactly the 13 enabled tools; writes carry _meta;
    reads do not.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import Client

THE_13_TOOLS = [
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
THE_5_WRITE_TOOLS = {
    "jira_create_issue",
    "jira_update_issue",
    "jira_add_comment",
    "jira_transition_issue",
    "jira_create_issue_link",
}
THE_8_READ_TOOLS = set(THE_13_TOOLS) - THE_5_WRITE_TOOLS

ENABLED_TOOLS_CSV = ",".join(THE_13_TOOLS)


# ---------------------------------------------------------------------------
# 4a — get_available_services keyring path
# ---------------------------------------------------------------------------


class TestGetAvailableServicesKeyring:
    """Test that get_available_services() uses the keyring when PAT env var is empty."""

    def _env(self, extra: dict | None = None) -> dict:
        base = {
            "JIRA_URL": "https://jira.example.com",
            "JIRA_PERSONAL_TOKEN": "",
        }
        if extra:
            base.update(extra)
        return base

    def test_empty_pat_env_keyring_has_token_gives_jira_true(self):
        """With JIRA_PERSONAL_TOKEN="" and keyring returning a token, jira is True."""
        with (
            patch.dict("os.environ", self._env(), clear=True),
            patch(
                "mcp_atlassian.utils.environment.get_jira_pat_from_keyring",
                return_value="keyring-pat",
            ),
        ):
            from mcp_atlassian.utils.environment import get_available_services

            result = get_available_services()
        assert result["jira"] is True

    def test_empty_pat_env_keyring_returns_none_gives_jira_false(self):
        """With JIRA_PERSONAL_TOKEN="" and keyring returning None, jira is False."""
        with (
            patch.dict("os.environ", self._env(), clear=True),
            patch(
                "mcp_atlassian.utils.environment.get_jira_pat_from_keyring",
                return_value=None,
            ),
        ):
            from mcp_atlassian.utils.environment import get_available_services

            result = get_available_services()
        assert result["jira"] is False

    def test_nonempty_pat_env_keyring_not_called(self):
        """With JIRA_PERSONAL_TOKEN set, keyring is not consulted."""
        env = self._env({"JIRA_PERSONAL_TOKEN": "env-token"})
        with (
            patch.dict("os.environ", env, clear=True),
            patch(
                "mcp_atlassian.utils.environment.get_jira_pat_from_keyring"
            ) as mock_kr,
        ):
            from mcp_atlassian.utils.environment import get_available_services

            result = get_available_services()
        assert result["jira"] is True
        mock_kr.assert_not_called()


# ---------------------------------------------------------------------------
# Fix 3 — http non-loopback rejection in get_jira_pat_from_keyring
# ---------------------------------------------------------------------------


def test_get_jira_pat_from_keyring_refuses_http_non_loopback(caplog):
    """get_jira_pat_from_keyring returns None and logs a WARNING for http:// on a
    non-loopback host, so a misconfigured JIRA_URL can't send the PAT in clear text."""
    import logging

    from mcp_atlassian.utils.environment import get_jira_pat_from_keyring

    with caplog.at_level(logging.WARNING, logger="mcp-atlassian.utils.environment"):
        result = get_jira_pat_from_keyring("http://jira.example.com")

    assert result is None
    assert any("plain http" in r.message.lower() for r in caplog.records)


def test_get_jira_pat_from_keyring_allows_http_loopback():
    """get_jira_pat_from_keyring proceeds to keyring for http://127.0.0.1 (fake Jira)."""
    from mcp_atlassian.utils.environment import get_jira_pat_from_keyring

    with patch("keyring.get_password", return_value="dummy-pat-123") as mock_kp:
        result = get_jira_pat_from_keyring("http://127.0.0.1:9")

    assert result == "dummy-pat-123"
    mock_kp.assert_called_once()


# ---------------------------------------------------------------------------
# 4b — end-to-end through Client(main_mcp)
# ---------------------------------------------------------------------------


def _make_fake_jira_config():
    """Return a mock JiraConfig that looks like a valid Server/DC PAT config."""
    from mcp_atlassian.jira.config import JiraConfig

    cfg = MagicMock(spec=JiraConfig)
    cfg.url = "http://127.0.0.1:9"
    cfg.is_cloud = False
    cfg.auth_type = "pat"
    cfg.is_auth_configured.return_value = True
    return cfg


@pytest.mark.anyio
async def test_e2e_main_mcp_lists_13_tools_with_meta():
    """End-to-end: Client(main_mcp) lists exactly the 13 enabled tools.

    The 5 writes must carry _meta['anthropic/requiresUserInteraction'] == True.
    The 8 reads must NOT carry that key.
    """
    from mcp_atlassian.servers.main import main_mcp

    env = {
        "JIRA_URL": "http://127.0.0.1:9",
        "JIRA_PERSONAL_TOKEN": "",
        "READ_ONLY_MODE": "false",
        "TOOLSETS": "all",
        "ENABLED_TOOLS": ENABLED_TOOLS_CSV,
    }

    fake_jira_config = _make_fake_jira_config()

    with (
        patch.dict("os.environ", env, clear=False),
        # Keyring returns a token → get_available_services() says jira=True
        patch(
            "mcp_atlassian.utils.environment.get_jira_pat_from_keyring",
            return_value="dummy-pat-123",
        ),
        # JiraConfig.from_env() returns our fake config (no real network call)
        patch(
            "mcp_atlassian.servers.main.JiraConfig.from_env",
            return_value=fake_jira_config,
        ),
    ):
        async with Client(main_mcp) as client:
            raw_tools = await client.list_tools()

    tool_map = {t.name: t.model_dump(by_alias=True) for t in raw_tools}
    listed_names = set(tool_map)

    # Exactly the 13 tools
    assert listed_names == set(THE_13_TOOLS), (
        f"Listed tools mismatch.\n"
        f"  Extra: {listed_names - set(THE_13_TOOLS)}\n"
        f"  Missing: {set(THE_13_TOOLS) - listed_names}"
    )

    # 5 writes carry requiresUserInteraction
    for name in THE_5_WRITE_TOOLS:
        meta = tool_map[name].get("_meta") or {}
        assert meta.get("anthropic/requiresUserInteraction") is True, (
            f"{name} should have requiresUserInteraction in _meta, got _meta={meta}"
        )

    # 8 reads do NOT carry the flag
    for name in THE_8_READ_TOOLS:
        meta = tool_map[name].get("_meta") or {}
        assert meta.get("anthropic/requiresUserInteraction") is not True, (
            f"{name} should NOT have requiresUserInteraction in _meta, got _meta={meta}"
        )
