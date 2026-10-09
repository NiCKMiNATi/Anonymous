"""Static dependency-direction checks (architecture §6): inward-only imports."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import anonymous

ROOT = Path(anonymous.__file__).parent


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def modules_under(package: str) -> list[Path]:
    return sorted((ROOT / package).rglob("*.py"))


FORBIDDEN = {
    "domain": (
        "sqlite3",
        "fastapi",
        "starlette",
        "pydantic",
        "uvicorn",
        "anonymous.adapters",
        "anonymous.application",
        "anonymous.api",
        "anonymous.composition",
    ),
    "application": (
        "sqlite3",
        "fastapi",
        "starlette",
        "pydantic",
        "uvicorn",
        "anonymous.adapters",
        "anonymous.api",
        "anonymous.composition",
    ),
    "api": ("sqlite3", "anonymous.adapters"),
}


@pytest.mark.parametrize("layer", sorted(FORBIDDEN))
def test_layer_does_not_import_outward(layer: str) -> None:
    offenders = []
    for path in modules_under(layer):
        for module in imported_modules(path):
            if any(module == bad or module.startswith(bad + ".") for bad in FORBIDDEN[layer]):
                offenders.append(f"{path.relative_to(ROOT)} imports {module}")
    assert offenders == []


def test_only_the_sqlite_package_imports_sqlite3() -> None:
    offenders = [
        str(p.relative_to(ROOT))
        for p in ROOT.rglob("*.py")
        if "sqlite3" in imported_modules(p) and "adapters/persistence/sqlite" not in p.as_posix()
    ]
    assert offenders == []


def test_only_composition_names_concrete_adapters() -> None:
    allowed = {"composition.py"}
    offenders = []
    for path in ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith("adapters/") or rel in allowed:
            continue
        for module in imported_modules(path):
            if module.startswith("anonymous.adapters"):
                offenders.append(f"{rel} imports {module}")
    assert offenders == []
