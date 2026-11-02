import ast
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src"
PACKAGE = "emporio_agent"
DOMAIN = f"{PACKAGE}.domain"
APPLICATION = f"{PACKAGE}.application"
INFRASTRUCTURE = f"{PACKAGE}.infrastructure"
AGENT = f"{PACKAGE}.agent"
CONFIG = f"{PACKAGE}.config"
BOOTSTRAP = f"{PACKAGE}.bootstrap"
SERIALIZATION = f"{AGENT}.tools.serialization"

INTERNAL_IMPORTS_ALLOWED = {
    DOMAIN: (DOMAIN,),
    APPLICATION: (DOMAIN, APPLICATION),
    INFRASTRUCTURE: (DOMAIN, APPLICATION, INFRASTRUCTURE),
    AGENT: (DOMAIN, APPLICATION, AGENT),
    CONFIG: (),
    BOOTSTRAP: (DOMAIN, APPLICATION, INFRASTRUCTURE, AGENT, CONFIG),
}
LAYERS_WITHOUT_THIRD_PARTY = (DOMAIN, APPLICATION)
DOMAIN_FORBIDDEN_STDLIB = frozenset(
    {
        "asyncio",
        "csv",
        "glob",
        "http",
        "io",
        "logging",
        "os",
        "pathlib",
        "shutil",
        "socket",
        "sqlite3",
        "subprocess",
        "tempfile",
        "urllib",
    }
)
DOMAIN_FORBIDDEN_CALLS = frozenset({"open", "print", "input"})
DYNAMIC_IMPORT_CALLS = frozenset({"__import__", "import_module"})


@dataclass(frozen=True)
class ImportedName:
    target: str
    line: int


def module_name_of(path: Path) -> str:
    parts = path.relative_to(SOURCE_ROOT).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def layer_of(module: str) -> str | None:
    for layer in INTERNAL_IMPORTS_ALLOWED:
        if module == layer or module.startswith(f"{layer}."):
            return layer
    return None


def is_inside(target: str, prefix: str) -> bool:
    return target == prefix or target.startswith(f"{prefix}.")


def called_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def relative_base(module: str, is_package: bool, level: int) -> str:
    parts = module.split(".")
    keep = len(parts) - level + (1 if is_package else 0)
    return ".".join(parts[:keep])


def imports_of(tree: ast.AST, module: str, is_package: bool) -> list[ImportedName]:
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [ImportedName(alias.name, node.lineno) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                prefix = relative_base(module, is_package, node.level)
                base = f"{prefix}.{base}" if base else prefix
            imported += [ImportedName(base, node.lineno)]
            imported += [ImportedName(f"{base}.{alias.name}", node.lineno) for alias in node.names]
        elif (
            isinstance(node, ast.Call)
            and called_name(node) in DYNAMIC_IMPORT_CALLS
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            imported.append(ImportedName(node.args[0].value, node.lineno))
    return imported


def import_violation(layer: str, target: str) -> str | None:
    if is_inside(target, PACKAGE):
        allowed_targets = INTERNAL_IMPORTS_ALLOWED[layer]
        if target == PACKAGE or any(is_inside(target, allowed) for allowed in allowed_targets):
            return None
        return f"camada {layer} só pode importar {allowed_targets or 'nada interno'}"
    root = target.split(".")[0]
    if layer == DOMAIN and root in DOMAIN_FORBIDDEN_STDLIB:
        return "domain não faz I/O nem logging"
    if layer in LAYERS_WITHOUT_THIRD_PARTY and root not in sys.stdlib_module_names:
        return f"camada {layer} não usa dependências de terceiros"
    return None


def violations_in_source(module: str, source: str, is_package: bool = False) -> list[str]:
    layer = layer_of(module)
    if layer is None:
        return []
    tree = ast.parse(source)
    violations = []
    for imported in imports_of(tree, module, is_package):
        reason = import_violation(layer, imported.target)
        if reason:
            violations.append(f"{module}:{imported.line} importa {imported.target!r}: {reason}")
    if layer == DOMAIN:
        violations += [
            f"{module}:{node.lineno} chama {called_name(node)}(): domain não faz I/O"
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and called_name(node) in DOMAIN_FORBIDDEN_CALLS
        ]
    if layer == AGENT and module != SERIALIZATION:
        violations += [
            f"{module}:{imported.line} importa json: a saída de texto é só to_tool_json"
            for imported in imports_of(tree, module, is_package)
            if imported.target.split(".")[0] == "json"
        ]
    return violations


def source_files() -> list[Path]:
    return sorted((SOURCE_ROOT / PACKAGE).rglob("*.py"))


def violations_in(path: Path) -> list[str]:
    source = path.read_text(encoding="utf-8")
    return violations_in_source(module_name_of(path), source, path.name == "__init__.py")


@pytest.mark.parametrize(
    "path",
    source_files(),
    ids=lambda path: str(path.relative_to(SOURCE_ROOT)).replace("\\", "/"),
)
def test_module_respects_layer_rules(path):
    violations = violations_in(path)

    assert not violations, "Violação de camadas:\n" + "\n".join(violations)


@pytest.mark.parametrize("layer", list(INTERNAL_IMPORTS_ALLOWED))
def test_every_layer_has_scanned_modules(layer):
    modules = [module_name_of(path) for path in source_files()]

    assert any(layer_of(module) == layer for module in modules)


def test_every_module_belongs_to_a_layer():
    orphans = [
        module_name_of(path)
        for path in source_files()
        if module_name_of(path) != PACKAGE and layer_of(module_name_of(path)) is None
    ]

    assert not orphans


@pytest.mark.parametrize(
    ("module", "source"),
    [
        (f"{DOMAIN}.models", "import logging"),
        (f"{DOMAIN}.models", "from pathlib import Path"),
        (f"{DOMAIN}.models", "import pydantic"),
        (f"{DOMAIN}.models", f"from {APPLICATION}.ports import CatalogRepository"),
        (f"{DOMAIN}.models", f"from {PACKAGE} import application"),
        (f"{DOMAIN}.models", "from .. import infrastructure"),
        (f"{DOMAIN}.models", "open('x')"),
        (f"{APPLICATION}.ports", "import pydantic"),
        (f"{APPLICATION}.ports", "from pydantic import BaseModel"),
        (f"{APPLICATION}.ports", f"import {INFRASTRUCTURE}.persistence.csv_repository"),
        (f"{APPLICATION}.ports", f"from {AGENT}.tools import schemas"),
        (f"{APPLICATION}.catalog.service", "from ...infrastructure import observability"),
        (f"{APPLICATION}.ports", f"from {CONFIG} import Settings"),
        (f"{INFRASTRUCTURE}.persistence.csv_repository", f"from {AGENT}.tools import schemas"),
        (f"{INFRASTRUCTURE}.persistence.csv_repository", f"from {BOOTSTRAP} import Container"),
        (f"{AGENT}.tools.catalog_tools", f"from {INFRASTRUCTURE}.observability import logging"),
        (f"{AGENT}.tools.catalog_tools", f"from {BOOTSTRAP} import build_container"),
        (f"{AGENT}.tools.catalog_tools", "import json"),
        (f"{CONFIG}", f"from {DOMAIN}.models import Product"),
        (
            f"{AGENT}.tools.catalog_tools",
            f"import importlib\nimportlib.import_module('{INFRASTRUCTURE}.persistence')",
        ),
    ],
)
def test_checker_detects_forbidden_imports(module, source):
    assert violations_in_source(module, source)


@pytest.mark.parametrize(
    ("module", "source"),
    [
        (f"{DOMAIN}.pricing", "from decimal import Decimal"),
        (f"{DOMAIN}.availability", "from .models import Product"),
        (f"{APPLICATION}.ports", f"from {DOMAIN}.models import Product"),
        (f"{INFRASTRUCTURE}.persistence.csv_repository", f"from {APPLICATION} import ports"),
        (f"{AGENT}.tools.schemas", "from pydantic import BaseModel"),
        (f"{AGENT}.tools.catalog_tools", f"from {APPLICATION}.ports import ErrorReporter"),
        (f"{SERIALIZATION}", "import json"),
        (f"{BOOTSTRAP}", f"from {INFRASTRUCTURE}.persistence import csv_repository"),
    ],
)
def test_checker_accepts_allowed_imports(module, source):
    assert violations_in_source(module, source) == []
