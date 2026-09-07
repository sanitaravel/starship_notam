"""Dependency-boundary integration tests.

Statically verifies that each package layer only imports the third-party
libraries permitted for that layer (requirements 9.4, 10.8, and the per-layer
dependency rules in requirements 10.2-10.7).

Approach
--------
For every ``.py`` file under a layer, the module is parsed with :mod:`ast` and
its **module-level** ``import`` / ``from ... import`` statements are collected.
Only *top-level* imports are inspected: heavy optional dependencies (Selenium,
Cartopy, Matplotlib, python-telegram-bot) are deliberately imported lazily
*inside function bodies*, so they are legitimately absent from the module-level
import set and are not boundary violations.

Each imported top-level package name is then classified:

    * Internal project imports (``starship_notam...``) are always allowed.
    * Python standard-library modules (per :data:`sys.stdlib_module_names`) are
      always allowed.
    * Any remaining name is a third-party dependency and must appear in that
      layer's allow-list; otherwise it is a dependency-boundary violation.

Requirement 9.4 is enforced explicitly: the parser layer must have no
module-level import referencing the data or visualization layers.

Requirements: 9.4, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

# Root of the installable package: .../starship_notam/starship_notam
PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "starship_notam"

# Set of standard-library top-level module names for this interpreter.
_STDLIB = set(sys.stdlib_module_names)

# Third-party packages each layer is permitted to import at module level.
# The import *name* (what appears in ``import X`` / ``from X import ...``) is
# used, which for a few packages differs from the PyPI distribution name:
#   python-dotenv -> dotenv, beautifulsoup4 -> bs4, pillow -> PIL,
#   python-telegram-bot -> telegram.
LAYER_ALLOWED_THIRD_PARTY = {
    "core": {"rich", "dotenv"},
    # data: standard library only (no third-party packages permitted).
    "data": set(),
    "parsers": {"bs4"},
    "scrapers": {"selenium", "requests"},
    "bot": {"telegram", "dotenv"},
    "visualization": {"matplotlib", "cartopy", "PIL", "shapely"},
}


def _iter_layer_files(layer: str):
    """Yield every ``.py`` source file within a layer package."""
    layer_dir = PACKAGE_ROOT / layer
    for path in sorted(layer_dir.rglob("*.py")):
        # Skip compiled-cache artifacts if any slipped through.
        if "__pycache__" in path.parts:
            continue
        yield path


def _module_level_imports(path: Path) -> list[tuple[str, int]]:
    """Return ``(top_level_module_name, lineno)`` for module-level imports.

    Only imports that are direct children of the module body are considered;
    imports nested inside function or class bodies (i.e. lazy imports) are
    intentionally ignored, since they are allowed by design.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    results: list[tuple[str, int]] = []

    for node in tree.body:  # only top-level statements
        if isinstance(node, ast.Import):
            for alias in node.names:
                results.append((alias.name.split(".")[0], node.lineno))
        elif isinstance(node, ast.ImportFrom):
            # Skip relative imports (level > 0); they are always internal.
            if node.level and node.level > 0:
                continue
            if node.module:
                results.append((node.module.split(".")[0], node.lineno))
    return results


def _classify(top_name: str) -> str:
    """Classify a top-level import name as internal / stdlib / third_party."""
    if top_name == "starship_notam":
        return "internal"
    if top_name in _STDLIB:
        return "stdlib"
    return "third_party"


@pytest.mark.parametrize("layer", sorted(LAYER_ALLOWED_THIRD_PARTY))
def test_layer_has_no_forbidden_third_party_imports(layer):
    """Requirement 10.8 / 10.2-10.7: each layer imports only its allowed libs.

    Walks every source file in the layer and asserts that no module-level
    third-party import falls outside the layer's allow-list.
    """
    allowed = LAYER_ALLOWED_THIRD_PARTY[layer]
    violations: list[str] = []

    for path in _iter_layer_files(layer):
        for top_name, lineno in _module_level_imports(path):
            if _classify(top_name) != "third_party":
                continue
            if top_name not in allowed:
                rel = path.relative_to(PACKAGE_ROOT.parent)
                violations.append(f"{rel}:{lineno} imports '{top_name}'")

    assert not violations, (
        f"Layer '{layer}' has module-level third-party imports outside its "
        f"allowed set {sorted(allowed) or '{}'}:\n  " + "\n  ".join(violations)
    )


def test_data_layer_uses_only_standard_library():
    """Requirement 10.2: the data layer imports only stdlib + internal modules.

    No third-party package may be imported at module level anywhere in the data
    layer.
    """
    violations: list[str] = []
    for path in _iter_layer_files("data"):
        for top_name, lineno in _module_level_imports(path):
            if _classify(top_name) == "third_party":
                rel = path.relative_to(PACKAGE_ROOT.parent)
                violations.append(f"{rel}:{lineno} imports third-party '{top_name}'")

    assert not violations, (
        "Data layer must import only the Python standard library and internal "
        "modules, but found third-party imports:\n  " + "\n  ".join(violations)
    )


def test_parsers_have_no_module_level_data_or_visualization_imports():
    """Requirement 9.4: parser modules must not reference data/visualization.

    Asserts that no parser source file contains a module-level import of the
    ``starship_notam.data`` or ``starship_notam.visualization`` sub-packages.
    """
    forbidden_subpackages = {"data", "visualization"}
    violations: list[str] = []

    for path in _iter_layer_files("parsers"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:  # module level only
            imported_modules: list[str] = []
            if isinstance(node, ast.Import):
                imported_modules = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules = [node.module]

            for mod in imported_modules:
                parts = mod.split(".")
                if (
                    len(parts) >= 2
                    and parts[0] == "starship_notam"
                    and parts[1] in forbidden_subpackages
                ):
                    rel = path.relative_to(PACKAGE_ROOT.parent)
                    violations.append(f"{rel}:{node.lineno} imports '{mod}'")

    assert not violations, (
        "Parser layer must not have module-level imports of the data or "
        "visualization layers (requirement 9.4):\n  " + "\n  ".join(violations)
    )


def test_visualization_does_not_import_bot_scraper_or_data():
    """Requirement 7 (6.7) / boundary: visualization stays independent.

    The visualization layer must not import from the bot, scrapers, or data
    layers at module level.
    """
    forbidden_subpackages = {"bot", "scrapers", "data"}
    violations: list[str] = []

    for path in _iter_layer_files("visualization"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            imported_modules: list[str] = []
            if isinstance(node, ast.Import):
                imported_modules = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules = [node.module]

            for mod in imported_modules:
                parts = mod.split(".")
                if (
                    len(parts) >= 2
                    and parts[0] == "starship_notam"
                    and parts[1] in forbidden_subpackages
                ):
                    rel = path.relative_to(PACKAGE_ROOT.parent)
                    violations.append(f"{rel}:{node.lineno} imports '{mod}'")

    assert not violations, (
        "Visualization layer must not import from bot/scrapers/data layers:\n  "
        + "\n  ".join(violations)
    )
