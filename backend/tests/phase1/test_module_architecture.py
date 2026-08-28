"""Static dependency checks for the VibeGuide module layers."""

from __future__ import annotations

import ast
from pathlib import Path


MODULES_ROOT = Path(__file__).parents[2] / "app" / "modules"
APP_ROOT = MODULES_ROOT.parent
REMOVED_IMPORT_ROOTS = (
    "app.auth",
    "app.ci_ingest",
    "app.modules.atomic.ingestion.bundle_validator",
    "app.modules.workflows.github_result_ingest",
    "app.worker.parsers",
    "app.worker.runner",
    "app.worker.sarif",
    "app.worker.scanners",
    "app.worker.tribal",
)


def _module_name(path: Path) -> str:
    relative = path.relative_to(MODULES_ROOT.parent.parent)
    parts = list(relative.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: list[str] = []
    current = _module_name(path).split(".")
    if path.name != "__init__.py":
        current.pop()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                prefix = current[: len(current) - node.level + 1]
                base = ".".join([*prefix, *(node.module or "").split(".")]).rstrip(".")
            else:
                base = node.module or ""
            if base:
                imported.append(base)
                imported.extend(f"{base}.{alias.name}" for alias in node.names)
    return imported


def test_atomic_and_shared_do_not_depend_on_workflows_or_api() -> None:
    forbidden = ("app.modules.workflows", "app.api")
    violations: list[str] = []
    for layer in ("atomic", "shared"):
        for path in (MODULES_ROOT / layer).rglob("*.py"):
            for imported in _imports(path):
                if imported.startswith(forbidden):
                    violations.append(f"{path.relative_to(MODULES_ROOT)} -> {imported}")
    assert violations == []


def test_atomic_services_do_not_depend_on_concrete_infrastructure_or_frameworks() -> None:
    forbidden = (
        "app.api",
        "app.infrastructure",
        "app.mcp",
        "app.worker",
        "fastapi",
        "pydantic",
        "sqlalchemy",
        "starlette",
    )
    violations: list[str] = []
    for path in (MODULES_ROOT / "atomic").rglob("*.py"):
        if path.name == "_adapters.py":
            continue
        for imported in _imports(path):
            if imported.startswith(forbidden):
                violations.append(f"{path.relative_to(MODULES_ROOT)} -> {imported}")
    assert violations == []


def test_workflows_depend_on_ports_not_legacy_workers_or_repositories() -> None:
    forbidden = (
        "app.infrastructure",
        "app.worker",
        "fastapi",
        "sqlalchemy",
        "starlette",
    )
    violations: list[str] = []
    for path in (MODULES_ROOT / "workflows").rglob("*.py"):
        for imported in _imports(path):
            if imported.startswith(forbidden) or ".repositories" in imported:
                violations.append(f"{path.relative_to(MODULES_ROOT)} -> {imported}")
    assert violations == []


def test_shared_does_not_depend_on_atomic() -> None:
    violations: list[str] = []
    for path in (MODULES_ROOT / "shared").rglob("*.py"):
        for imported in _imports(path):
            if imported.startswith("app.modules.atomic"):
                violations.append(f"{path.relative_to(MODULES_ROOT)} -> {imported}")
    assert violations == []


def test_shared_has_no_web_or_database_dependencies() -> None:
    forbidden = ("fastapi", "starlette", "sqlalchemy", "app.api", "app.infrastructure.db")
    violations: list[str] = []
    for path in (MODULES_ROOT / "shared").rglob("*.py"):
        for imported in _imports(path):
            if imported.startswith(forbidden):
                violations.append(f"{path.relative_to(MODULES_ROOT)} -> {imported}")
    assert violations == []


def test_removed_legacy_import_roots_are_absent_from_application_sources() -> None:
    violations: list[str] = []
    for path in APP_ROOT.rglob("*.py"):
        for imported in _imports(path):
            if imported.startswith(REMOVED_IMPORT_ROOTS):
                violations.append(f"{path.relative_to(APP_ROOT)} -> {imported}")
    assert violations == []

    removed_files = (
        APP_ROOT / "ci_ingest.py",
        APP_ROOT / "worker" / "runner.py",
        APP_ROOT / "worker" / "sarif.py",
        APP_ROOT / "worker" / "scanners.py",
        APP_ROOT / "worker" / "tribal.py",
    )
    assert [str(path.relative_to(APP_ROOT)) for path in removed_files if path.exists()] == []
    assert not (APP_ROOT / "worker" / "parsers").exists()
    assert not any((MODULES_ROOT / "workflows" / "github_result_ingest").glob("*.py"))
    assert not any((MODULES_ROOT / "atomic" / "ingestion" / "bundle_validator").glob("*.py"))


def test_module_dependency_graph_has_no_cycles() -> None:
    module_paths = {
        _module_name(path): path for path in MODULES_ROOT.rglob("*.py")
    }
    graph = {
        module: {
            imported
            for imported in _imports(path)
            if imported in module_paths and imported != module
        }
        for module, path in module_paths.items()
    }
    visiting: list[str] = []
    visited: set[str] = set()

    def visit(module: str) -> None:
        if module in visiting:
            start = visiting.index(module)
            cycle = " -> ".join([*visiting[start:], module])
            raise AssertionError(f"module dependency cycle: {cycle}")
        if module in visited:
            return
        visiting.append(module)
        for dependency in sorted(graph[module]):
            visit(dependency)
        visiting.pop()
        visited.add(module)

    for module in sorted(graph):
        visit(module)
