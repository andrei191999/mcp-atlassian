"""Tests for D5: FASTMCP_CHECK_FOR_UPDATES disabled by default."""

import os
import subprocess
import sys


def test_fastmcp_update_check_off_when_env_unset():
    """Subprocess: importing mcp_atlassian without FASTMCP_CHECK_FOR_UPDATES set
    causes fastmcp.settings.check_for_updates to equal 'off'."""
    env = {k: v for k, v in os.environ.items() if k != "FASTMCP_CHECK_FOR_UPDATES"}
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import mcp_atlassian; from fastmcp import settings; print(settings.check_for_updates)",
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "off"


def test_fastmcp_update_check_user_value_respected():
    """Subprocess: an explicit FASTMCP_CHECK_FOR_UPDATES=stable is preserved."""
    env = {**os.environ, "FASTMCP_CHECK_FOR_UPDATES": "stable"}
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import mcp_atlassian; from fastmcp import settings; print(settings.check_for_updates)",
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "stable"
