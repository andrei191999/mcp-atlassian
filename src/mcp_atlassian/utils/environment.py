"""Utility functions related to environment checking."""

import logging
import os
from urllib.parse import urlparse

from .env import is_env_truthy
from .urls import is_atlassian_cloud_url

logger = logging.getLogger("mcp-atlassian.utils.environment")

# UNI-336: keyring service/username for the Jira PAT.
JIRA_PAT_KEYRING_SERVICE = "mcp-atlassian-jira-pat"


def jira_keyring_username(url: str) -> str:
    """Normalise a Jira URL for use as the keyring username.

    Strips surrounding whitespace and a trailing "/".  A blank result means
    the URL was unusable; callers should treat that as "no keyring lookup".
    """
    return url.strip().rstrip("/")


_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def get_jira_pat_from_keyring(url: str) -> str | None:
    """Return the Jira PAT stored in the OS keyring, or None.

    Returns None and emits a warning when:
    - The normalised URL is empty.
    - The URL is an Atlassian Cloud URL (PAT is a Server/DC concept).
    - The scheme is http and the host is not a loopback address (plain-text
      transmission would expose the PAT).
    - The keyring backend raises a KeyringError.

    Args:
        url: The raw JIRA_URL value.

    Returns:
        The stored token, or None when unavailable.
    """
    username = jira_keyring_username(url)
    if not username:
        return None
    # Check against the normalised URL so trailing-slash variants are handled.
    if is_atlassian_cloud_url(username):
        return None
    parsed = urlparse(username)
    if parsed.scheme == "http" and (parsed.hostname or "") not in _LOOPBACK_HOSTS:
        logger.warning(
            "Refusing to use keyring PAT over plain http for non-loopback host %r; "
            "configure JIRA_URL with https.",
            parsed.hostname,
        )
        return None
    try:
        import keyring
        import keyring.errors

        return keyring.get_password(JIRA_PAT_KEYRING_SERVICE, username)
    except keyring.errors.KeyringError as exc:
        logger.warning(
            "OS keyring lookup failed (%s); continuing without PAT.",
            type(exc).__name__,
        )
        return None


def _check_service_auth(
    service_name: str,
    service_url: str,
    client_id_envs: tuple[str, str],
    client_secret_envs: tuple[str, str],
    access_token_envs: tuple[str, str],
    username_env: str,
    api_env: str,
    pat_env: str,
    client_cert_env: str | None = None,
) -> bool:
    """Detect whether a single Atlassian service is authenticated.

    Args:
        service_name: Human-readable service name (e.g. ``"Confluence"``).
        service_url: URL of the service instance.
        client_id_envs: ``(shared_env, service_env)`` pair for OAuth client ID.
        client_secret_envs: ``(shared_env, service_env)`` pair for OAuth client secret.
        access_token_envs: ``(shared_env, service_env)`` pair for OAuth access token.
        username_env: Env var name for the Basic Auth username.
        api_env: Env var name for the Basic Auth API token / password.
        pat_env: Env var name for the Personal Access Token (Server/DC only).
        client_cert_env: Env var name for the client certificate path
            (mTLS, Server/DC only).

    Returns:
        ``True`` when a valid auth configuration is detected, ``False`` otherwise.
    """
    is_cloud = is_atlassian_cloud_url(service_url)

    client_id = os.getenv(client_id_envs[0]) or os.getenv(client_id_envs[1])
    client_secret = os.getenv(client_secret_envs[0]) or os.getenv(client_secret_envs[1])
    access_token = os.getenv(access_token_envs[0]) or os.getenv(access_token_envs[1])
    cloud_id = os.getenv("ATLASSIAN_OAUTH_CLOUD_ID")

    # Cloud OAuth check (needs cloud_id)
    if all([client_id, client_secret, cloud_id]):
        logger.info("Using %s OAuth 2.0 (3LO) authentication (Cloud)", service_name)
        return True

    # DC OAuth check (no cloud_id, but has client credentials + non-cloud URL)
    if not is_cloud and client_id and client_secret:
        logger.info("Using %s OAuth 2.0 authentication (Data Center)", service_name)
        return True

    # Cloud BYO access token
    if all([access_token, cloud_id]):
        logger.info(
            "Using %s OAuth 2.0 (3LO) authentication (Cloud) "
            "with provided access token",
            service_name,
        )
        return True

    # DC BYO access token (no cloud_id, non-cloud URL)
    if not is_cloud and access_token:
        logger.info(
            "Using %s OAuth 2.0 authentication (Data Center) "
            "with provided access token",
            service_name,
        )
        return True

    if is_cloud:  # Cloud non-OAuth
        if os.getenv(username_env) and os.getenv(api_env):
            logger.info("Using %s Cloud Basic Authentication (API Token)", service_name)
            return True
    else:  # Server/Data Center non-OAuth
        # Check Basic Auth first so a username+api_token setup never touches
        # the keyring or emits a spurious keyring warning.
        if os.getenv(username_env) and os.getenv(api_env):
            logger.info(
                "Using %s Server/Data Center authentication (PAT or Basic Auth)",
                service_name,
            )
            return True
        pat = os.getenv(pat_env)
        # For Jira, also fall back to the OS keyring when the env var is empty.
        # Confluence keyring support is out of scope and stays unchanged.
        if not pat and service_name == "Jira" and service_url:
            pat = get_jira_pat_from_keyring(service_url)
        if pat:
            logger.info(
                "Using %s Server/Data Center authentication (PAT or Basic Auth)",
                service_name,
            )
            return True
        if client_cert_env and os.getenv(client_cert_env):
            logger.info("Using %s mTLS client certificate authentication", service_name)
            return True

    return False


def get_available_services(
    headers: dict[str, str] | None = None,
) -> dict[str, bool | None]:
    """Determine which services are available based on environment variables and optional headers."""
    headers = headers or {}

    confluence_url = os.getenv("CONFLUENCE_URL")
    confluence_is_setup = False
    if confluence_url:
        confluence_is_setup = _check_service_auth(
            service_name="Confluence",
            service_url=confluence_url,
            client_id_envs=("ATLASSIAN_OAUTH_CLIENT_ID", "CONFLUENCE_OAUTH_CLIENT_ID"),
            client_secret_envs=(
                "ATLASSIAN_OAUTH_CLIENT_SECRET",
                "CONFLUENCE_OAUTH_CLIENT_SECRET",
            ),
            access_token_envs=(
                "ATLASSIAN_OAUTH_ACCESS_TOKEN",
                "CONFLUENCE_OAUTH_ACCESS_TOKEN",
            ),
            username_env="CONFLUENCE_USERNAME",
            api_env="CONFLUENCE_API_TOKEN",
            pat_env="CONFLUENCE_PERSONAL_TOKEN",
            client_cert_env="CONFLUENCE_CLIENT_CERT",
        )

    if not confluence_is_setup and os.getenv("ATLASSIAN_OAUTH_ENABLE", "").lower() in (
        "true",
        "1",
        "yes",
    ):
        confluence_is_setup = True
        logger.info(
            "Using Confluence minimal OAuth configuration "
            "- expecting user-provided tokens via headers"
        )

    if not confluence_is_setup and is_env_truthy("ATLASSIAN_EXTERNAL_AUTH_ENABLE"):
        confluence_is_setup = True
        logger.info(
            "Using Confluence external auth passthrough mode "
            "- auth headers injected by upstream proxy"
        )

    if not confluence_is_setup:
        confluence_token = headers.get("X-Atlassian-Confluence-Personal-Token")
        confluence_url_header = headers.get("X-Atlassian-Confluence-Url")

        if confluence_token and confluence_url_header:
            confluence_is_setup = True
            logger.info("Using Confluence authentication from header personal token")

    jira_url = os.getenv("JIRA_URL")
    jira_is_setup = False
    if jira_url:
        jira_is_setup = _check_service_auth(
            service_name="Jira",
            service_url=jira_url,
            client_id_envs=("ATLASSIAN_OAUTH_CLIENT_ID", "JIRA_OAUTH_CLIENT_ID"),
            client_secret_envs=(
                "ATLASSIAN_OAUTH_CLIENT_SECRET",
                "JIRA_OAUTH_CLIENT_SECRET",
            ),
            access_token_envs=(
                "ATLASSIAN_OAUTH_ACCESS_TOKEN",
                "JIRA_OAUTH_ACCESS_TOKEN",
            ),
            username_env="JIRA_USERNAME",
            api_env="JIRA_API_TOKEN",
            pat_env="JIRA_PERSONAL_TOKEN",
            client_cert_env="JIRA_CLIENT_CERT",
        )

    if not jira_is_setup and os.getenv("ATLASSIAN_OAUTH_ENABLE", "").lower() in (
        "true",
        "1",
        "yes",
    ):
        jira_is_setup = True
        logger.info(
            "Using Jira minimal OAuth configuration "
            "- expecting user-provided tokens via headers"
        )

    if not jira_is_setup and is_env_truthy("ATLASSIAN_EXTERNAL_AUTH_ENABLE"):
        jira_is_setup = True
        logger.info(
            "Using Jira external auth passthrough mode "
            "- auth headers injected by upstream proxy"
        )

    if not jira_is_setup:
        jira_token = headers.get("X-Atlassian-Jira-Personal-Token")
        jira_url_header = headers.get("X-Atlassian-Jira-Url")

        if jira_token and jira_url_header:
            jira_is_setup = True
            logger.info("Using Jira authentication from header personal token")

    if not confluence_is_setup:
        logger.info(
            "Confluence is not configured or required environment variables are missing."
        )
    if not jira_is_setup:
        logger.info(
            "Jira is not configured or required environment variables are missing."
        )

    return {"confluence": confluence_is_setup, "jira": jira_is_setup}
