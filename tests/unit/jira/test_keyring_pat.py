"""Tests for UNI-336: Jira PAT loaded from OS keyring when env var is unset."""

import logging
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from mcp_atlassian.jira.config import JIRA_PAT_KEYRING_SERVICE, JiraConfig

# ---------------------------------------------------------------------------
# from_env keyring integration
# ---------------------------------------------------------------------------


def _pat_env(extra: dict | None = None) -> dict:
    """Minimal Server/DC env that reaches the PAT branch."""
    base = {"JIRA_URL": "https://jira.example.com/"}
    if extra:
        base.update(extra)
    return base


def test_env_var_wins_over_keyring():
    """A non-empty JIRA_PERSONAL_TOKEN env var is used; keyring is never called."""
    with (
        patch.dict(
            "os.environ", _pat_env({"JIRA_PERSONAL_TOKEN": "env-token"}), clear=True
        ),
        patch("keyring.get_password") as mock_get,
    ):
        config = JiraConfig.from_env()
    assert config.personal_token == "env-token"
    mock_get.assert_not_called()


def test_empty_env_var_falls_back_to_keyring():
    """Empty JIRA_PERSONAL_TOKEN causes keyring lookup (plugin always sets it to '')."""
    with (
        patch.dict("os.environ", _pat_env({"JIRA_PERSONAL_TOKEN": ""}), clear=True),
        patch("keyring.get_password", return_value="keyring-token") as mock_get,
    ):
        config = JiraConfig.from_env()
    assert config.personal_token == "keyring-token"
    mock_get.assert_called_once_with(
        JIRA_PAT_KEYRING_SERVICE, "https://jira.example.com"
    )


def test_keyring_error_is_logged_without_token(caplog):
    """KeyringError is caught and logged; no token leaks; auth error fires later."""
    import keyring.errors

    with (
        patch.dict("os.environ", _pat_env({"JIRA_PERSONAL_TOKEN": ""}), clear=True),
        patch(
            "keyring.get_password",
            side_effect=keyring.errors.KeyringError("backend unavailable"),
        ),
        caplog.at_level(logging.WARNING, logger="mcp-atlassian.jira.config"),
    ):
        with pytest.raises(ValueError):
            JiraConfig.from_env()

    # Warning was logged and the token value is not in it
    assert any("keyring" in r.message.lower() for r in caplog.records)
    for record in caplog.records:
        assert "keyring-token" not in record.message
        assert (
            "backend unavailable" not in record.message or "token" not in record.message
        )


def test_pat_source_logged_env(caplog):
    """INFO line 'Jira PAT source: env' is logged when env var has a value."""
    with (
        patch.dict(
            "os.environ", _pat_env({"JIRA_PERSONAL_TOKEN": "env-token"}), clear=True
        ),
        patch("keyring.get_password"),
        caplog.at_level(logging.INFO, logger="mcp-atlassian.jira.config"),
    ):
        JiraConfig.from_env()
    assert any("Jira PAT source: env" in r.message for r in caplog.records)


def test_pat_source_logged_keyring(caplog):
    """INFO line 'Jira PAT source: keyring' is logged when keyring returns a token."""
    with (
        patch.dict("os.environ", _pat_env({"JIRA_PERSONAL_TOKEN": ""}), clear=True),
        patch("keyring.get_password", return_value="keyring-token"),
        caplog.at_level(logging.INFO, logger="mcp-atlassian.jira.config"),
    ):
        JiraConfig.from_env()
    assert any("Jira PAT source: keyring" in r.message for r in caplog.records)


def test_pat_source_logged_none(caplog):
    """When no PAT is found anywhere, a WARNING with the service and actionable hint is logged."""
    with (
        patch.dict("os.environ", _pat_env({"JIRA_PERSONAL_TOKEN": ""}), clear=True),
        patch("keyring.get_password", return_value=None),
        caplog.at_level(logging.WARNING, logger="mcp-atlassian.jira.config"),
    ):
        with pytest.raises(ValueError):
            JiraConfig.from_env()
    assert any(
        "No Jira PAT found" in r.message and "mcp-atlassian-jira-pat" in r.message
        for r in caplog.records
    )


def test_keyring_not_called_when_basic_auth_set():
    """Keyring is not consulted when JIRA_USERNAME + JIRA_API_TOKEN are both set."""
    env = {
        "JIRA_URL": "https://jira.example.com",
        "JIRA_USERNAME": "user",
        "JIRA_API_TOKEN": "apitoken",
        "JIRA_PERSONAL_TOKEN": "",
    }
    with (
        patch.dict("os.environ", env, clear=True),
        patch("keyring.get_password") as mock_get,
    ):
        config = JiraConfig.from_env()
    assert config.auth_type == "basic"
    mock_get.assert_not_called()


# ---------------------------------------------------------------------------
# --store-jira-pat CLI tests
# ---------------------------------------------------------------------------


def test_store_jira_pat_tty_uses_getpass():
    """On a TTY, _read_pat_secret calls getpass.getpass (token never echoed)."""
    import mcp_atlassian

    # Verify the helper calls getpass when stdin.isatty() is True.
    with (
        patch("sys.stdin") as mock_stdin,
        patch("getpass.getpass", return_value="my-secret-pat") as mock_gp,
    ):
        mock_stdin.isatty.return_value = True
        result = mcp_atlassian._read_pat_secret("Jira personal access token: ")

    assert result == "my-secret-pat"
    mock_gp.assert_called_once_with("Jira personal access token: ")

    # Also verify the full CLI path stores the token via keyring.
    from mcp_atlassian import main

    runner = CliRunner()
    with (
        patch("keyring.set_password") as mock_set,
        patch("mcp_atlassian._read_pat_secret", return_value="my-secret-pat"),
    ):
        result = runner.invoke(
            main,
            ["--store-jira-pat", "--jira-url", "https://jira.example.com"],
            catch_exceptions=False,
        )
    assert result.exit_code == 0, result.output
    mock_set.assert_called_once_with(
        JIRA_PAT_KEYRING_SERVICE, "https://jira.example.com", "my-secret-pat"
    )


def test_store_jira_pat_piped_reads_stdin():
    """_read_pat_secret reads one stripped line from stdin when not a TTY."""
    import mcp_atlassian

    with patch("sys.stdin") as mock_stdin:
        mock_stdin.isatty.return_value = False
        mock_stdin.readline.return_value = "piped-pat\n"
        result = mcp_atlassian._read_pat_secret("Jira personal access token: ")

    assert result == "piped-pat"

    # Also verify full CLI path stores the token.
    from mcp_atlassian import main

    runner = CliRunner()
    with (
        patch("keyring.set_password") as mock_set,
        patch("mcp_atlassian._read_pat_secret", return_value="piped-pat"),
    ):
        result = runner.invoke(
            main,
            ["--store-jira-pat", "--jira-url", "https://jira.example.com"],
            catch_exceptions=False,
        )
    assert result.exit_code == 0, result.output
    mock_set.assert_called_once_with(
        JIRA_PAT_KEYRING_SERVICE, "https://jira.example.com", "piped-pat"
    )


def test_store_jira_pat_empty_token_exits_1():
    """An empty PAT value must be rejected with exit code 1."""
    from mcp_atlassian import main

    runner = CliRunner()
    with (
        patch("keyring.set_password") as mock_set,
        patch("mcp_atlassian._read_pat_secret", return_value=""),
    ):
        result = runner.invoke(
            main,
            ["--store-jira-pat", "--jira-url", "https://jira.example.com"],
        )
    assert result.exit_code == 1
    mock_set.assert_not_called()


def test_store_jira_pat_missing_url_exits_1():
    """--store-jira-pat without a URL must exit 1 (not start the server)."""
    from mcp_atlassian import main

    runner = CliRunner()
    with patch("keyring.set_password") as mock_set:
        result = runner.invoke(
            main,
            ["--store-jira-pat"],
            env={"JIRA_URL": ""},
        )
    assert result.exit_code == 1
    mock_set.assert_not_called()


def test_store_jira_pat_does_not_start_server():
    """--store-jira-pat exits before the server starts."""
    from mcp_atlassian import main

    runner = CliRunner()
    with (
        patch("keyring.set_password"),
        patch("mcp_atlassian._read_pat_secret", return_value="dummy-pat-123"),
        patch("mcp_atlassian.servers.main_mcp") as mock_server,
    ):
        result = runner.invoke(
            main,
            ["--store-jira-pat", "--jira-url", "https://jira.example.com"],
            catch_exceptions=False,
        )
    assert result.exit_code == 0
    mock_server.run_async.assert_not_called()


# ---------------------------------------------------------------------------
# Fix 9 — mutation-testing gaps
# ---------------------------------------------------------------------------


def test_keyring_service_name_is_literal():
    """The keyring service string is exactly 'mcp-atlassian-jira-pat'.

    Tests must assert the literal, not just the imported constant, so that
    renaming the constant would break the test and alert maintainers that
    existing stored PATs would become orphaned.
    """
    from mcp_atlassian.utils.environment import JIRA_PAT_KEYRING_SERVICE

    assert JIRA_PAT_KEYRING_SERVICE == "mcp-atlassian-jira-pat"


def test_trailing_slash_store_lookup_symmetry():
    """A URL with a trailing slash is normalised consistently for store and lookup."""
    from mcp_atlassian.utils.environment import jira_keyring_username

    with_slash = jira_keyring_username("https://jira.example.com/")
    without_slash = jira_keyring_username("https://jira.example.com")
    assert with_slash == without_slash == "https://jira.example.com"


def test_store_jira_pat_cli_token_not_in_output():
    """The PAT value never appears in stdout or stderr."""
    from mcp_atlassian import main

    secret = "super-secret-pat-99"
    runner = CliRunner()
    with (
        patch("keyring.set_password"),
        patch("mcp_atlassian._read_pat_secret", return_value=secret),
    ):
        result = runner.invoke(
            main,
            ["--store-jira-pat", "--jira-url", "https://jira.example.com"],
            catch_exceptions=False,
        )
    assert secret not in (result.output or "")
    assert secret not in (result.stderr or "") if hasattr(result, "stderr") else True


def test_pat_source_log_never_contains_token(caplog):
    """The 'Jira PAT source' INFO line never includes the actual token value."""
    with (
        patch.dict(
            "os.environ",
            _pat_env({"JIRA_PERSONAL_TOKEN": "env-secret-xyz"}),
            clear=True,
        ),
        patch("keyring.get_password"),
        caplog.at_level(logging.INFO, logger="mcp-atlassian.jira.config"),
    ):
        from mcp_atlassian.jira.config import JiraConfig

        JiraConfig.from_env()
    for record in caplog.records:
        assert "env-secret-xyz" not in record.message


def test_store_jira_pat_http_non_loopback_rejected():
    """--store-jira-pat must reject http:// for non-loopback servers."""
    from mcp_atlassian import main

    runner = CliRunner()
    with patch("keyring.set_password") as mock_set:
        result = runner.invoke(
            main,
            ["--store-jira-pat", "--jira-url", "http://jira.example.com"],
            env={"JIRA_URL": ""},
        )
    assert result.exit_code == 1
    mock_set.assert_not_called()


def test_store_jira_pat_http_loopback_allowed():
    """--store-jira-pat allows http:// for 127.0.0.1 (fake Jira)."""
    from mcp_atlassian import main

    runner = CliRunner()
    with (
        patch("keyring.set_password") as mock_set,
        patch("mcp_atlassian._read_pat_secret", return_value="dummy-pat-123"),
    ):
        result = runner.invoke(
            main,
            ["--store-jira-pat", "--jira-url", "http://127.0.0.1:9"],
            catch_exceptions=False,
        )
    assert result.exit_code == 0
    mock_set.assert_called_once_with(
        JIRA_PAT_KEYRING_SERVICE, "http://127.0.0.1:9", "dummy-pat-123"
    )


def test_store_jira_pat_cloud_url_rejected():
    """--store-jira-pat must reject Atlassian Cloud URLs."""
    from mcp_atlassian import main

    runner = CliRunner()
    with patch("keyring.set_password") as mock_set:
        result = runner.invoke(
            main,
            ["--store-jira-pat", "--jira-url", "https://company.atlassian.net"],
            env={"JIRA_URL": ""},
        )
    assert result.exit_code == 1
    mock_set.assert_not_called()


def test_jiraconfig_personal_token_not_in_repr():
    """personal_token must be excluded from JiraConfig repr to prevent log leaks."""
    from mcp_atlassian.jira.config import JiraConfig

    env = {
        "JIRA_URL": "https://jira.example.com",
        "JIRA_PERSONAL_TOKEN": "my-secret-pat",
    }
    with (
        patch.dict("os.environ", env, clear=True),
        patch("keyring.get_password", return_value=None),
    ):
        cfg = JiraConfig.from_env()
    assert "my-secret-pat" not in repr(cfg)
