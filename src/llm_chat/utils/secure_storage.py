"""Secure credential storage using system keyring.

Supports storing/retrieving API keys via the system keyring (macOS Keychain,
Windows Credential Manager, Linux Secret Service). Falls back to environment
variables if keyring is unavailable.

Usage:
    # Store a key: vermilion-bird keyring set openai
    # Config reference: api_key: "keyring:vermilion-bird/openai"
    # Environment fallback: LLM_API_KEY env var
"""

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_KEYRING_AVAILABLE = False
try:
    import keyring
    _KEYRING_AVAILABLE = True
except ImportError:
    pass

_SERVICE_NAME = "vermilion-bird"
_KEYRING_PREFIX = "keyring:"


def is_keyring_available() -> bool:
    """Check if system keyring is available."""
    return _KEYRING_AVAILABLE


def resolve_api_key(api_key: Optional[str], env_var: str = "LLM_API_KEY") -> Optional[str]:
    """Resolve an API key from config, keyring, or environment.

    Resolution order:
    1. If api_key is a direct value (not starting with 'keyring:'), return as-is
    2. If api_key starts with 'keyring:', fetch from system keyring
    3. If api_key is None, fall back to environment variable
    4. If all fail, return None

    Args:
        api_key: Raw api_key from config (may be None, plain text, or 'keyring:name')
        env_var: Environment variable name to check as fallback

    Returns:
        Resolved API key or None
    """
    # 1. Plain text API key
    if api_key and not api_key.startswith(_KEYRING_PREFIX):
        return api_key

    # 2. Keyring reference
    if api_key and api_key.startswith(_KEYRING_PREFIX):
        if not _KEYRING_AVAILABLE:
            logger.warning(
                "API key references keyring but keyring package is not installed. "
                "Install with: pip install keyring"
            )
            return None

        keyring_name = api_key[len(_KEYRING_PREFIX):]
        if "/" in keyring_name:
            service, username = keyring_name.split("/", 1)
        else:
            service = _SERVICE_NAME
            username = keyring_name

        try:
            stored = keyring.get_password(service, username)
            if stored:
                logger.debug(f"API key resolved from keyring: {service}/{username}")
                return stored
            else:
                logger.warning(
                    f"No API key found in keyring for {service}/{username}. "
                    f"Store it with: vermilion-bird keyring set {username}"
                )
        except Exception as e:
            logger.error(f"Failed to read from keyring: {e}")

    # 3. Environment variable fallback
    env_value = os.getenv(env_var)
    if env_value:
        logger.debug(f"API key resolved from environment variable: {env_var}")
        return env_value

    return None


def store_api_key(username: str, api_key: str, service: str = _SERVICE_NAME) -> bool:
    """Store an API key in the system keyring.

    Args:
        username: Key identifier (e.g., 'openai', 'anthropic', 'gemini')
        api_key: The API key to store
        service: Keyring service name (default: 'vermilion-bird')

    Returns:
        True if stored successfully, False otherwise
    """
    if not _KEYRING_AVAILABLE:
        logger.error(
            "Cannot store API key: keyring package is not installed. "
            "Install with: pip install keyring"
        )
        return False

    try:
        keyring.set_password(service, username, api_key)
        logger.info(f"API key stored in keyring: {service}/{username}")
        return True
    except Exception as e:
        logger.error(f"Failed to store API key in keyring: {e}")
        return False


def delete_api_key(username: str, service: str = _SERVICE_NAME) -> bool:
    """Delete an API key from the system keyring.

    Args:
        username: Key identifier
        service: Keyring service name

    Returns:
        True if deleted successfully, False otherwise
    """
    if not _KEYRING_AVAILABLE:
        return False

    try:
        keyring.delete_password(service, username)
        logger.info(f"API key deleted from keyring: {service}/{username}")
        return True
    except Exception as e:
        logger.error(f"Failed to delete API key from keyring: {e}")
        return False
