"""Load local ``.env`` for CLI and Gradio entrypoints."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dotenv import find_dotenv, load_dotenv

if TYPE_CHECKING:
    from bilibili_api import Credential

_loaded = False
_last_dotenv_path: str | None = None
_last_dotenv_loaded: bool = False

BILIBILI_ENV_KEYS = ("BILIBILI_SESSDATA", "BILIBILI_BILI_JCT", "BILIBILI_BUVID3")
BILIBILI_NETWORK_ENV_KEYS = (
    "BILIBILI_HTTP_CLIENT",
    "BILIBILI_PROXY_URL",
    "BILIBILI_TIMEOUT_SECONDS",
    "BILIBILI_IMPERSONATE",
)


def load_local_env(
    *,
    dotenv_path: str | Path | None = None,
    force_reload: bool = False,
) -> bool:
    """Load variables from a ``.env`` file (once per process unless ``force_reload``).

    Shell-exported variables take precedence (``override=False``).

    Lookup order when ``dotenv_path`` is omitted:

    1. ``./.env`` in the current working directory
    2. First ``.env`` found walking parent directories from cwd

    Returns ``True`` if a file was found and loaded.
    """
    global _loaded, _last_dotenv_path, _last_dotenv_loaded

    if _loaded and not force_reload:
        return _last_dotenv_loaded

    resolved_path: Path | None = None
    loaded = False

    dotenv_override = force_reload

    if dotenv_path is not None:
        path = Path(dotenv_path)
        if path.is_file():
            resolved_path = path
            loaded = load_dotenv(path, override=dotenv_override)
    else:
        cwd_file = Path.cwd() / ".env"
        if cwd_file.is_file():
            resolved_path = cwd_file
            loaded = load_dotenv(cwd_file, override=dotenv_override)
        else:
            found = find_dotenv(usecwd=True)
            if found:
                resolved_path = Path(found)
                loaded = load_dotenv(found, override=dotenv_override)

    _last_dotenv_path = str(resolved_path) if resolved_path is not None else None
    _last_dotenv_loaded = loaded
    _loaded = True
    return loaded


def bilibili_env_diagnostics() -> dict[str, Any]:
    """Report whether Bilibili cookie env vars are set (values never included)."""
    presence = {key: bool(_env(key)) for key in BILIBILI_ENV_KEYS}
    return {
        "dotenv_path": _last_dotenv_path,
        "dotenv_loaded": _last_dotenv_loaded,
        "vars": presence,
        "any_set": any(presence.values()),
        "all_set": all(presence.values()),
        "credential_available": get_bilibili_credential() is not None,
    }


def log_bilibili_env_diagnostics(logger: Any) -> None:
    """Log redacted Bilibili env state for startup troubleshooting."""
    diag = bilibili_env_diagnostics()
    logger.info(
        "bilibili env: dotenv_loaded=%s dotenv_path=%s vars=%s credential_available=%s",
        diag["dotenv_loaded"],
        diag["dotenv_path"],
        diag["vars"],
        diag["credential_available"],
    )


def configure_bilibili_network_from_env(
    logger: Any | None = None,
) -> dict[str, Any]:
    """Apply bilibili-api-python network client/settings from environment.

    Safe to call multiple times (e.g. after ``load_local_env(force_reload=True)``).
    Falls back when requested HTTP client is unavailable.
    """
    from bilibili_api import get_registered_clients, get_selected_client, request_settings

    result: dict[str, Any] = {
        "requested_client": None,
        "selected_client": None,
        "client_fallback": None,
        "proxy_configured": False,
        "timeout_seconds": None,
        "impersonate": None,
        "network_env": {key: bool(_env(key)) for key in BILIBILI_NETWORK_ENV_KEYS},
    }

    client_name = _env("BILIBILI_HTTP_CLIENT").lower()
    if client_name:
        result["requested_client"] = client_name
        registered = get_registered_clients()
        if client_name in registered:
            try:
                from bilibili_api import select_client

                select_client(client_name)
            except Exception as exc:
                result["client_fallback"] = str(exc)[:200]
                if logger is not None:
                    logger.warning(
                        "bilibili network: could not select client %r: %s",
                        client_name,
                        result["client_fallback"],
                    )
        else:
            available = ", ".join(sorted(registered.keys()))
            result["client_fallback"] = (
                f"client {client_name!r} not registered; available: {available}"
            )
            if logger is not None:
                logger.warning("bilibili network: %s", result["client_fallback"])

    proxy_url = _env("BILIBILI_PROXY_URL")
    if proxy_url:
        request_settings.set_proxy(proxy_url)
        result["proxy_configured"] = True

    timeout_raw = _env("BILIBILI_TIMEOUT_SECONDS")
    if timeout_raw:
        try:
            timeout = float(timeout_raw)
            if timeout > 0:
                request_settings.set_timeout(timeout)
                result["timeout_seconds"] = timeout
        except ValueError:
            if logger is not None:
                logger.warning(
                    "bilibili network: invalid BILIBILI_TIMEOUT_SECONDS=%r",
                    timeout_raw,
                )

    impersonate = _env("BILIBILI_IMPERSONATE")
    if impersonate:
        try:
            request_settings.set("impersonate", impersonate)
            result["impersonate"] = impersonate
        except Exception as exc:
            if logger is not None:
                logger.warning(
                    "bilibili network: could not set impersonate=%r: %s",
                    impersonate,
                    exc,
                )

    selected = get_selected_client()
    if isinstance(selected, tuple) and selected:
        result["selected_client"] = selected[0]
    elif selected is not None:
        result["selected_client"] = str(selected)

    if logger is not None:
        logger.info(
            "bilibili network: requested=%s selected=%s proxy=%s timeout=%s impersonate=%s fallback=%s",
            result["requested_client"],
            result["selected_client"],
            result["proxy_configured"],
            result["timeout_seconds"],
            result["impersonate"],
            result["client_fallback"],
        )

    return result


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def get_bilibili_credential() -> Credential | None:
    """Build ``bilibili_api.Credential`` from discrete env vars.

    Reads ``BILIBILI_SESSDATA``, ``BILIBILI_BILI_JCT``, and ``BILIBILI_BUVID3``.
    Channel/uploader feeds typically need all three; video URL fetches may work
    with fewer fields when Bilibili anti-bot is lenient.
    """
    from bilibili_api import Credential

    sessdata = _env("BILIBILI_SESSDATA")
    bili_jct = _env("BILIBILI_BILI_JCT")
    buvid3 = _env("BILIBILI_BUVID3")

    if not any((sessdata, bili_jct, buvid3)):
        return None

    kwargs: dict[str, str] = {}
    if sessdata:
        kwargs["sessdata"] = sessdata
    if bili_jct:
        kwargs["bili_jct"] = bili_jct
    if buvid3:
        kwargs["buvid3"] = buvid3
    return Credential(**kwargs)


def _reset_loaded_state_for_testing() -> None:
    """Allow tests to reload ``.env`` with a different cwd or path."""
    global _loaded, _last_dotenv_path, _last_dotenv_loaded
    _loaded = False
    _last_dotenv_path = None
    _last_dotenv_loaded = False


__all__ = [
    "BILIBILI_ENV_KEYS",
    "BILIBILI_NETWORK_ENV_KEYS",
    "bilibili_env_diagnostics",
    "configure_bilibili_network_from_env",
    "get_bilibili_credential",
    "load_local_env",
    "log_bilibili_env_diagnostics",
    "_reset_loaded_state_for_testing",
]
