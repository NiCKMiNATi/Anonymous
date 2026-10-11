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


def calls_of(attribute: str, receiver: str | None = None) -> list[str]:
    """Files under ``src`` that call ``<receiver>.<attribute>(`` (production code only)."""
    found = []
    for path in ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if node.func.attr != attribute:
                continue
            owner = node.func.value
            name = owner.attr if isinstance(owner, ast.Attribute) else getattr(owner, "id", None)
            if receiver is None or name == receiver:
                found.append(path.relative_to(ROOT).as_posix())
    return sorted(set(found))


def test_the_runtime_is_started_from_exactly_one_place() -> None:
    # G-2: only the supervised worker, after T3b, under the handoff gate. Reconcile, retry,
    # replay and restart have no code path to ``start``.
    assert calls_of("start", "_runtime") == ["application/worker.py"]
    assert calls_of("mark_handoff_started", "_store") == ["application/worker.py"]
    assert calls_of("await_result", "_runtime") == ["application/worker.py"]


def test_closure_of_an_open_fence_has_a_single_gated_code_path() -> None:
    # A-4: every closure goes through RunSettler (which takes the handoff gate). The worker's only
    # other writer is the atomic closure+settlement after the bound instance has delivered.
    assert calls_of("close_run", "_store") == ["application/settling.py"]
    assert calls_of("settle_in_flight", "_store") == ["application/settling.py"]
