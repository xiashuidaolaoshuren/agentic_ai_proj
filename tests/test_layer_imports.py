"""Import-direction checks for api → services → repositories layering (8A.1 T1)."""

from __future__ import annotations

import ast
from pathlib import Path

_SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "ai_news_agent"
_FORBIDDEN_PREFIXES = ("ai_news_agent.services", "ai_news_agent.api")


def _iter_python_modules(package_dir: Path) -> list[Path]:
    if not package_dir.is_dir():
        return []
    modules: list[Path] = []
    for path in sorted(package_dir.rglob("*.py")):
        if path.name == "__pycache__":
            continue
        modules.append(path)
    return modules


def _module_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module is None:
                continue
            imports.add(node.module)
    return imports


def _assert_package_rejects_forbidden_imports(package_name: str) -> None:
    package_dir = _SRC_ROOT / package_name
    assert package_dir.is_dir(), f"{package_name} package missing under src/ai_news_agent"

    violations: list[str] = []
    for module_path in _iter_python_modules(package_dir):
        rel = module_path.relative_to(_SRC_ROOT).as_posix()
        for imported in sorted(_module_imports(module_path)):
            if any(
                imported == prefix or imported.startswith(f"{prefix}.")
                for prefix in _FORBIDDEN_PREFIXES
            ):
                violations.append(f"{rel} imports {imported}")

    assert not violations, "Forbidden layer imports:\n" + "\n".join(violations)


def test_repositories_do_not_import_services_or_api() -> None:
    _assert_package_rejects_forbidden_imports("repositories")


def test_services_do_not_import_api_when_present() -> None:
    services_dir = _SRC_ROOT / "services"
    if not services_dir.is_dir():
        return
    _assert_package_rejects_forbidden_imports("services")


def test_storage_reexports_digest_store_without_local_definitions() -> None:
    from ai_news_agent import storage
    from ai_news_agent.repositories import digest_store

    assert storage.DigestStore is digest_store.DigestStore
    assert storage.FollowupContext is digest_store.FollowupContext
    assert storage.SCHEMA_VERSION is digest_store.SCHEMA_VERSION

    storage_path = _SRC_ROOT / "storage.py"
    tree = ast.parse(storage_path.read_text(encoding="utf-8"), filename=str(storage_path))
    local_defs = [
        node.name
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    assert local_defs == []
