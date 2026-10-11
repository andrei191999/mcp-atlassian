"""Tests for D13: stdio + JIRA_URL + no credentials → exit 1 with clear message."""

import os
import subprocess
import sys
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


_INVOKE = "from mcp_atlassian import main; main()"
_INVOKE_HTTP = (
    "import sys; sys.argv = ['mcp-atlassian', '--transport', 'streamable-http']; "
    "from mcp_atlassian import main; main()"
)


# ---------------------------------------------------------------------------
# Test 1: no credentials → exit 1, correct Server/DC message, empty stdout
# ---------------------------------------------------------------------------


def test_stdio_no_creds_exits_1_with_message():
    """stdio + JIRA_URL + no credentials → exit 1, message on stderr, no stdout."""
    result = subprocess.run(
        [sys.executable, "-c", _INVOKE],
        input=b"",
        capture_output=True,
        timeout=30,
        env=_clean_env(
            JIRA_URL="http://127.0.0.1:9",
            JIRA_PERSONAL_TOKEN="",
            PYTHON_KEYRING_BACKEND="keyring.backends.null.Keyring",
        ),
    )
    assert result.returncode == 1
    stderr = result.stderr.decode("utf-8", errors="replace")
    assert "no Jira credentials found" in stderr, repr(stderr)
    assert "--store-jira-pat" in stderr, repr(stderr)
    assert result.stdout == b""
    assert len(stderr.splitlines()) == 1, (
        f"Expected exactly 1 stderr line, got:\n{stderr}"
    )


# ---------------------------------------------------------------------------
# Test 2: keyring holds a dummy token → check passes
# ---------------------------------------------------------------------------


def test_stdio_keyring_token_passes_check(monkeypatch):
    """With keyring returning a token, _check_jira_stdio_creds returns None."""
    _clear_auth(monkeypatch)
    monkeypatch.setenv("JIRA_URL", "http://127.0.0.1:9")

    with patch("keyring.get_password", return_value="dummy-keyring-token"):
        from mcp_atlassian import _check_jira_stdio_creds  # noqa: PLC0415

        result = _check_jira_stdio_creds("http://127.0.0.1:9")

    assert result is None, f"Expected no error message, got: {result!r}"


# ---------------------------------------------------------------------------
# Test 3: HTTP transport → D13 check is skipped
# ---------------------------------------------------------------------------


def test_http_transport_skips_d13_check():
    """HTTP transport: D13 check is skipped — no 'no Jira credentials found' on stderr."""
    proc = subprocess.Popen(
        [sys.executable, "-c", _INVOKE_HTTP],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_clean_env(
            JIRA_URL="http://127.0.0.1:9",
            JIRA_PERSONAL_TOKEN="",
            PYTHON_KEYRING_BACKEND="keyring.backends.null.Keyring",
        ),
    )
    try:
        try:
            proc.wait(timeout=2)
            stderr = proc.stderr.read().decode("utf-8", errors="replace")
            assert "no Jira credentials found" not in stderr, (
                f"D13 incorrectly applied to HTTP transport. stderr: {stderr}"
            )
        except subprocess.TimeoutExpired:
            pass  # Server still running — expected for HTTP transport.
    finally:
        proc.kill()
        proc.communicate()


# ---------------------------------------------------------------------------
# Test 4: Confluence configured → D13 does not exit even without Jira creds
# ---------------------------------------------------------------------------


def test_confluence_configured_prevents_exit(monkeypatch):
    """JIRA_URL without Jira creds + Confluence configured → no exit (service available)."""
    _clear_auth(monkeypatch)
    monkeypatch.setenv("JIRA_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("CONFLUENCE_URL", "http://127.0.0.1:8")
    monkeypatch.setenv("CONFLUENCE_PERSONAL_TOKEN", "dummy")

    with patch("keyring.get_password", return_value=None):
        from mcp_atlassian import _check_jira_stdio_creds  # noqa: PLC0415

        result = _check_jira_stdio_creds("http://127.0.0.1:9")

    assert result is None, f"Expected no error (Confluence configured), got: {result!r}"


# ---------------------------------------------------------------------------
# Test 5: Atlassian Cloud URL → no --store-jira-pat suggestion
# ---------------------------------------------------------------------------


def test_cloud_url_suggests_api_token_not_pat(monkeypatch):
    """Cloud URL → message suggests JIRA_USERNAME/JIRA_API_TOKEN, not --store-jira-pat."""
    _clear_auth(monkeypatch)
    monkeypatch.setenv("JIRA_URL", "https://example.atlassian.net")

    from mcp_atlassian import _check_jira_stdio_creds  # noqa: PLC0415

    result = _check_jira_stdio_creds("https://example.atlassian.net")

    assert result is not None, "Expected an error message for Cloud URL with no creds"
    assert "JIRA_USERNAME" in result, repr(result)
    assert "JIRA_API_TOKEN" in result, repr(result)
    assert "Atlassian Cloud" in result, repr(result)
    assert "store-jira-pat" not in result, repr(result)


# ---------------------------------------------------------------------------
# Test 6: Partial env vars → "incomplete credentials" message, no values
# ---------------------------------------------------------------------------


def test_partial_env_creds_message(monkeypatch):
    """JIRA_USERNAME set without JIRA_API_TOKEN → 'incomplete credentials' message."""
    _clear_auth(monkeypatch)
    monkeypatch.setenv("JIRA_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("JIRA_USERNAME", "testuser@example.com")

    with patch("keyring.get_password", return_value=None):
        from mcp_atlassian import _check_jira_stdio_creds  # noqa: PLC0415

        result = _check_jira_stdio_creds("http://127.0.0.1:9")

    assert result is not None, "Expected an error for partial credentials"
    assert "incomplete" in result, repr(result)
    assert "JIRA_USERNAME" in result, repr(result)
    assert "testuser" not in result, f"Values must not appear in message: {result!r}"


# ---------------------------------------------------------------------------
# Test 7: KeyringError → distinct message naming the error type
# ---------------------------------------------------------------------------


def test_keyring_error_message(monkeypatch):
    """When keyring raises KeyringError, message names the error type."""
    _clear_auth(monkeypatch)
    monkeypatch.setenv("JIRA_URL", "http://127.0.0.1:9")

    import keyring.errors

    with patch("keyring.get_password", side_effect=keyring.errors.KeyringError("fail")):
        from mcp_atlassian import _check_jira_stdio_creds  # noqa: PLC0415

        result = _check_jira_stdio_creds("http://127.0.0.1:9")

    assert result is not None, "Expected an error for keyring failure"
    assert "keyring unavailable" in result, repr(result)
    assert "KeyringError" in result, repr(result)
    assert "store-jira-pat" in result, repr(result)


# ---------------------------------------------------------------------------
# Test 8: env PAT set → helper passes (returns None)
# ---------------------------------------------------------------------------


def test_env_pat_passes_check(monkeypatch):
    """JIRA_PERSONAL_TOKEN set to non-empty → _check_jira_stdio_creds returns None."""
    _clear_auth(monkeypatch)
    monkeypatch.setenv("JIRA_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("JIRA_PERSONAL_TOKEN", "dummy-pat")

    from mcp_atlassian import _check_jira_stdio_creds  # noqa: PLC0415

    result = _check_jira_stdio_creds("http://127.0.0.1:9")

    assert result is None, f"Expected None (PAT configured), got: {result!r}"


# ---------------------------------------------------------------------------
# Test 9: JIRA_USERNAME + JIRA_API_TOKEN set → helper passes (returns None)
# ---------------------------------------------------------------------------


def test_basic_auth_passes_check(monkeypatch):
    """JIRA_USERNAME + JIRA_API_TOKEN set → _check_jira_stdio_creds returns None."""
    _clear_auth(monkeypatch)
    monkeypatch.setenv("JIRA_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("JIRA_USERNAME", "user@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "dummy-api-token")

    from mcp_atlassian import _check_jira_stdio_creds  # noqa: PLC0415

    result = _check_jira_stdio_creds("http://127.0.0.1:9")

    assert result is None, f"Expected None (basic auth configured), got: {result!r}"


# ---------------------------------------------------------------------------
# Test 10: non-KeyringError backend exception → one-line message, no secret
# ---------------------------------------------------------------------------


def test_non_keyring_error_no_secret_leak(monkeypatch):
    """RuntimeError from backend → one-line 'keyring unavailable' message; secret not echoed.

    get_available_services() calls keyring once (returns None → no jira creds).
    The re-probe in _check_jira_stdio_creds calls it a second time and gets the
    RuntimeError.  side_effect=[None, RuntimeError(...)] sequences the two calls.
    """
    _clear_auth(monkeypatch)
    monkeypatch.setenv("JIRA_URL", "http://127.0.0.1:9")

    with patch("keyring.get_password", side_effect=[None, RuntimeError("SECRET-xyz")]):
        from mcp_atlassian import _check_jira_stdio_creds  # noqa: PLC0415

        result = _check_jira_stdio_creds("http://127.0.0.1:9")

    assert result is not None, "Expected an error message for RuntimeError"
    assert "keyring unavailable" in result, repr(result)
    assert "RuntimeError" in result, repr(result)
    assert "SECRET-xyz" not in result, f"Secret must not appear in message: {result!r}"
    assert len(result.splitlines()) == 1, f"Message must be one line: {result!r}"


# ---------------------------------------------------------------------------
# Test 11: RuntimeError on FIRST keyring call (from get_available_services)
# ---------------------------------------------------------------------------


def test_keyring_error_on_first_call_no_secret_leak(monkeypatch):
    """RuntimeError on any keyring call (including first from get_available_services) → caught.

    F3: Tests the try/except around get_available_services() so that if it crashes
    (e.g. RuntimeError propagating from keyring), the secret is never leaked.
    """
    _clear_auth(monkeypatch)
    monkeypatch.setenv("JIRA_URL", "http://127.0.0.1:9")

    with patch("keyring.get_password", side_effect=RuntimeError("SECRET-xyz")):
        from mcp_atlassian import _check_jira_stdio_creds  # noqa: PLC0415

        result = _check_jira_stdio_creds("http://127.0.0.1:9")

    assert result is not None, "Expected an error message (not propagated exception)"
    assert "SECRET-xyz" not in result, f"Secret must not appear in message: {result!r}"
    assert "RuntimeError" in result, repr(result)
    assert len(result.splitlines()) == 1, f"Message must be one line: {result!r}"


# ---------------------------------------------------------------------------
# Test 12: URL with embedded newline → still exactly 1 stderr line  (F1+F2)
# ---------------------------------------------------------------------------


def test_url_with_newline_gives_one_stderr_line():
    """JIRA_URL with embedded newline → sanitized; exactly 1 stderr line on exit 1."""
    result = subprocess.run(
        [sys.executable, "-c", _INVOKE],
        input=b"",
        capture_output=True,
        timeout=30,
        env=_clean_env(
            JIRA_URL="http://127.0.0.1:9\nmalicious-line",
            JIRA_PERSONAL_TOKEN="",
            PYTHON_KEYRING_BACKEND="keyring.backends.null.Keyring",
        ),
    )
    assert result.returncode == 1
    assert result.stdout == b""
    stderr = result.stderr.decode("utf-8", errors="replace")
    assert len(stderr.splitlines()) == 1, (
        f"Expected exactly 1 stderr line, got:\n{stderr}"
    )


# ---------------------------------------------------------------------------
# Test 13: URL with embedded credentials → secret never appears on stderr (F1+F2)
# ---------------------------------------------------------------------------


def test_url_with_credentials_not_leaked():
    """JIRA_URL with embedded credentials → 'SECRET' never appears in output."""
    result = subprocess.run(
        [sys.executable, "-c", _INVOKE],
        input=b"",
        capture_output=True,
        timeout=30,
        env=_clean_env(
            JIRA_URL="https://user:SECRET@127.0.0.1:9/?t=SECRET2",
            JIRA_PERSONAL_TOKEN="",
            PYTHON_KEYRING_BACKEND="keyring.backends.null.Keyring",
        ),
    )
    assert result.returncode == 1
    assert result.stdout == b""
    stderr = result.stderr.decode("utf-8", errors="replace")
    stdout = result.stdout.decode("utf-8", errors="replace")
    assert "SECRET" not in stderr, f"Secret leaked to stderr: {stderr!r}"
    assert "SECRET" not in stdout, f"Secret leaked to stdout: {stdout!r}"


# ---------------------------------------------------------------------------
# Test 14: URL with context path → path preserved, secrets stripped (task 2)
# ---------------------------------------------------------------------------


def test_url_with_context_path_preserved_and_secrets_stripped(monkeypatch):
    """Path is preserved in the --jira-url hint; userinfo/query/fragment are stripped."""
    _clear_auth(monkeypatch)
    monkeypatch.setenv("JIRA_URL", "https://user:SECRET@host:8443/jira/?t=SECRET2#frag")

    with patch("keyring.get_password", return_value=None):
        from mcp_atlassian import _safe_url_for_message  # noqa: PLC0415

        result = _safe_url_for_message(
            "https://user:SECRET@host:8443/jira/?t=SECRET2#frag"
        )

    assert result == "https://host:8443/jira", f"Unexpected URL: {result!r}"
    assert "SECRET" not in result, f"Credential leaked: {result!r}"
    assert "SECRET2" not in result, f"Query secret leaked: {result!r}"
    assert "frag" not in result, f"Fragment leaked: {result!r}"


# ---------------------------------------------------------------------------
# Test 15: mixed-case hostname preserved (keyring key uses raw URL, not lowercase)
# ---------------------------------------------------------------------------


def test_url_with_mixed_case_host_preserved(monkeypatch):
    """Mixed-case hostname preserved — parsed.netloc keeps case; parsed.hostname lowercases."""
    _clear_auth(monkeypatch)

    from mcp_atlassian import _safe_url_for_message  # noqa: PLC0415

    result = _safe_url_for_message(
        "https://user:SECRET@Tickets.Example.com:8443/jira/?t=S2#frag"
    )

    assert result == "https://Tickets.Example.com:8443/jira", f"Unexpected: {result!r}"
    assert "SECRET" not in result
