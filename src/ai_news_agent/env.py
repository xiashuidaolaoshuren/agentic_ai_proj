"""Load local ``.env`` for CLI and Gradio entrypoints."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from dotenv import find_dotenv, load_dotenv

if TYPE_CHECKING:
    from bilibili_api import Credential

_loaded = False


def load_local_env(*, dotenv_path: str | Path | None = None) -> bool:
    """Load variables from a ``.env`` file once per process.

    Shell-exported variables take precedence (``override=False``).

    Lookup order when ``dotenv_path`` is omitted:

    1. ``./.env`` in the current working directory
    2. First ``.env`` found walking parent directories from cwd

    Returns ``True`` if a file was found and loaded.
    """
    global _loaded
    if _loaded:
        return True

    if dotenv_path is not None:
        path = Path(dotenv_path)
        loaded = load_dotenv(path, override=False) if path.is_file() else False
    else:
        cwd_file = Path.cwd() / ".env"
        if cwd_file.is_file():
            loaded = load_dotenv(cwd_file, override=False)
        else:
            found = find_dotenv(usecwd=True)
            loaded = load_dotenv(found, override=False) if found else False

    _loaded = True
    return loaded


def _cookie_raw_to_dict(raw: str) -> dict[str, str]:
    s = raw.strip()
    if not s:
        return {}
    if "=" not in s:
        return {"SESSDATA": s}
    out: dict[str, str] = {}
    for part in s.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        key, val = part.split("=", 1)
        out[key.strip()] = val.strip()
    return out


def get_bilibili_cookie() -> str | None:
    """Optional Bilibili session cookie(s) for anti-bot resilience.

    Accepts a full ``Cookie`` header value, ``SESSDATA=...`` pair, or bare
    ``SESSDATA`` token via ``BILIBILI_COOKIE`` / ``BILIBILI_SESSDATA``.
    """
    for key in ("BILIBILI_COOKIE", "BILIBILI_SESSDATA"):
        val = os.environ.get(key)
        if val and str(val).strip():
            return str(val).strip()
    return None


def get_bilibili_credential() -> Credential | None:
    """Build ``bilibili_api.Credential`` from env when any session field is set."""
    from bilibili_api import Credential

    cookie_raw = get_bilibili_cookie()
    cookies = _cookie_raw_to_dict(cookie_raw) if cookie_raw else {}
    sessdata = cookies.get("SESSDATA") or os.environ.get("BILIBILI_SESSDATA", "").strip()
    bili_jct = cookies.get("bili_jct") or os.environ.get("BILIBILI_BILI_JCT", "").strip()
    buvid3 = cookies.get("buvid3") or os.environ.get("BILIBILI_BUVID3", "").strip()

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
    global _loaded
    _loaded = False


__all__ = [
    "get_bilibili_cookie",
    "get_bilibili_credential",
    "load_local_env",
    "_reset_loaded_state_for_testing",
]
