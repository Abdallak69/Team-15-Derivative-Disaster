"""Environment-backed secret loading with repository guardrails."""

from __future__ import annotations

from pathlib import Path
import os
import stat


PLACEHOLDER_VALUES = frozenset(
    {
        "replace_me",
        "changeme",
        "your_api_key_here",
        "your_secret_here",
        "your_token_here",
    }
)


class SecretConfigurationError(ValueError):
    """Raised when environment-backed secrets are missing or unsafe."""


def load_project_env(env_path: Path) -> None:
    """Load the local .env file after enforcing restrictive permissions."""
    if not env_path.exists():
        return

    _validate_env_permissions(env_path)

    try:
        from dotenv import load_dotenv
    except ImportError:
        return

    load_dotenv(env_path, override=False)


def load_secret_from_env(name: str) -> str | None:
    """Return a sanitized secret value, treating placeholders as unset."""
    raw_value = os.getenv(name)
    if raw_value is None:
        return None

    value = raw_value.strip()
    if not value or value.lower() in PLACEHOLDER_VALUES:
        return None

    return value


def _validate_env_permissions(env_path: Path) -> None:
    if os.name == "nt":
        return

    file_mode = stat.S_IMODE(env_path.stat().st_mode)
    if file_mode & 0o077:
        raise SecretConfigurationError(
            f"{env_path} permissions are too open; expected chmod 600"
        )
