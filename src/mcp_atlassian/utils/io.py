"""I/O utility functions for MCP Atlassian."""

import logging
import os
from pathlib import Path

logger = logging.getLogger("mcp-atlassian.utils.io")

_FALSY: frozenset[str] = frozenset({"false", "0", "no", "n", "off"})
_TRUTHY: frozenset[str] = frozenset({"true", "1", "yes", "y", "on"})


def is_read_only_mode() -> bool:
    """Check if the server is running in read-only mode.

    Read-only mode prevents all write operations (create, update, delete)
    while allowing all read operations. This is useful for working with
    production Atlassian instances where you want to prevent accidental
    modifications.

    Four-way distinction on READ_ONLY_MODE:
    - UNSET (not in os.environ): False — preserves upstream default.
    - SET but empty or whitespace-only: True — fail-safe for unconfigured plugins
      that expand ``READ_ONLY_MODE=${unset_var:-}`` to an empty string.
    - SET to a recognised falsy value (false/0/no/n/off, case-insensitive): False.
    - SET to a recognised truthy value (true/1/yes/y/on, case-insensitive): True.
    - SET to anything else (unrecognised): True — fail-closed; a warning is logged
      naming the bad value so operators can diagnose misconfiguration.

    Returns:
        True if read-only mode is enabled, False otherwise
    """
    raw = os.environ.get("READ_ONLY_MODE")
    if raw is None:
        return False
    stripped = raw.strip()
    if not stripped:
        logger.warning("READ_ONLY_MODE is set but empty; defaulting to read-only")
        return True
    lower = stripped.lower()
    if lower in _FALSY:
        return False
    if lower in _TRUTHY:
        return True
    logger.warning(
        "READ_ONLY_MODE has unrecognized value %r; defaulting to read-only", stripped
    )
    return True


def validate_safe_path(
    path: str | os.PathLike[str],
    base_dir: str | os.PathLike[str] | None = None,
) -> Path:
    """Validate that a path does not escape the base directory.

    Resolves symlinks and normalizes the path to prevent path traversal
    attacks (e.g., ``../../etc/passwd``).

    Args:
        path: The path to validate.
        base_dir: The directory the path must stay within.
            Defaults to the current working directory.

    Returns:
        The resolved, validated path.

    Raises:
        ValueError: If the resolved path escapes *base_dir*.
    """
    if base_dir is None:
        base_dir = os.getcwd()

    resolved_base = Path(base_dir).resolve(strict=False)
    p = Path(path)
    # Resolve relative paths against base_dir, not cwd
    if not p.is_absolute():
        p = resolved_base / p
    resolved_path = p.resolve(strict=False)

    if not resolved_path.is_relative_to(resolved_base):
        raise ValueError(
            f"Path traversal detected: {path} resolves outside {resolved_base}"
        )

    return resolved_path
