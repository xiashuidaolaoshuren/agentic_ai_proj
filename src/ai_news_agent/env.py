"""Load local ``.env`` for CLI and Gradio entrypoints."""

from __future__ import annotations

from pathlib import Path

from dotenv import find_dotenv, load_dotenv

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


def _reset_loaded_state_for_testing() -> None:
    """Allow tests to reload ``.env`` with a different cwd or path."""
    global _loaded
    _loaded = False


__all__ = ["load_local_env", "_reset_loaded_state_for_testing"]
