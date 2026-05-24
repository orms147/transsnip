from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# Each provider gets its own keyring service so the API keys don't collide and
# `keyring delete transsnip:claude apikey` only removes that one.
_SERVICE_PREFIX = "transsnip"
_USERNAME = "apikey"


def _service(provider: str) -> str:
    return f"{_SERVICE_PREFIX}:{provider}"


def get_api_key(provider: str) -> str | None:
    """Return the stored API key for `provider`, or None if absent.

    Wraps `keyring` so a missing optional dependency or a backend failure (e.g.
    no credential manager service on the host) degrades to "no key" instead of
    crashing the caller.
    """
    try:
        import keyring
    except ImportError:
        log.warning("keyring not installed — cannot load API key")
        return None
    try:
        return keyring.get_password(_service(provider), _USERNAME)
    except Exception as exc:  # noqa: BLE001 — keyring backends raise various errors
        log.warning("keyring read failed for %s: %s", provider, exc)
        return None


def set_api_key(provider: str, api_key: str) -> bool:
    """Persist the API key. Empty `api_key` deletes the entry. Returns success."""
    if not api_key.strip():
        return delete_api_key(provider)
    try:
        import keyring
    except ImportError:
        log.error("keyring not installed — cannot save API key")
        return False
    try:
        keyring.set_password(_service(provider), _USERNAME, api_key.strip())
        return True
    except Exception as exc:  # noqa: BLE001
        log.error("keyring write failed for %s: %s", provider, exc)
        return False


def delete_api_key(provider: str) -> bool:
    try:
        import keyring
    except ImportError:
        return False
    try:
        keyring.delete_password(_service(provider), _USERNAME)
        return True
    except Exception:  # noqa: BLE001 — "no such key" is fine
        return True


def has_api_key(provider: str) -> bool:
    return get_api_key(provider) is not None
