"""Backward compatibility tests for the refactored ``src`` package.

These tests lock in Requirement 1.3 and 8.3:

* **1.3** — Every public function/object previously importable from the flat
  top-level modules (``notam_db``, ``notam_parser``, ``notam_request``,
  ``notam_logging``, ``telegram_bot``, ``visualize_notams``,
  ``fetch_faa_advisory``, ``fetch_starbase_closures``) is re-exported from
  ``src.__init__`` and remains resolvable.
* **8.3** — A missing/unknown attribute on the top-level package fails with a
  clear error message that names the missing attribute, and a request that maps
  onto a genuinely missing submodule fails with a clear ``ModuleNotFoundError``.

The test data below is derived from the *actual* re-export tables in
``src/__init__.py`` and each sub-package's ``__init__.py``. Each
entry pairs a public name with the new package path that owns it. For every
name we assert:

1. it is accessible as an attribute of the top-level ``src`` package;
2. it is accessible from its new package path (e.g. ``src.data``);
3. the two resolve to the *same* object (the top-level re-export is a genuine
   alias, not a divergent copy);
4. it is advertised in ``src.__all__`` so ``from src
   import *`` and tooling see it.
"""

from __future__ import annotations

import importlib

import pytest

import src


# ---------------------------------------------------------------------------
# The public API contract.
#
# Maps each old flat module to the (public name -> new package path) pairs that
# used to be importable from it. New package paths are the *packages* whose
# ``__init__`` re-exports the name, matching how a consumer would now import it,
# e.g. ``from src.data import save_notam``.
# ---------------------------------------------------------------------------
OLD_MODULE_EXPORTS: dict[str, dict[str, str]] = {
    # notam_db -> src.data
    "notam_db": {
        "get_connection": "src.data",
        "init_db": "src.data",
        "save_notam": "src.data",
        "get_notams_needing_images": "src.data",
        "mark_image_generated": "src.data",
        "load_all_notams": "src.data",
        "faa_activities": "src.data",
        "beach_alerts": "src.data",
        "road_alerts": "src.data",
    },
    # notam_parser -> src.parsers
    "notam_parser": {
        "parse_notam": "src.parsers",
        "parse_carf_message": "src.parsers",
    },
    # notam_request -> src.scrapers
    "notam_request": {
        "search_notams": "src.scrapers",
    },
    # fetch_faa_advisory -> scrapers (fetch) + parsers (html parse)
    "fetch_faa_advisory": {
        "faa_advisory_fetcher": "src.scrapers",
        "parse_faa_advisory_html": "src.parsers",
    },
    # fetch_starbase_closures -> scrapers (fetch) + parsers (html parse)
    "fetch_starbase_closures": {
        "starbase_status_fetcher": "src.scrapers",
        "parse_starbase_html": "src.parsers",
    },
    # notam_logging -> src.core
    "notam_logging": {
        "TELEGRAM_BOT_TOKEN": "src.core",
        "TELEGRAM_CHANNEL_ID": "src.core",
        "DB_PATH": "src.core",
        "KEYWORD": "src.core",
        "RUNS_PER_HOUR": "src.core",
        "logger": "src.core",
        "console": "src.core",
    },
    # telegram_bot -> src.bot (and bot submodules)
    "telegram_bot": {
        "build_notam_caption": "src.bot",
        "format_faa_activity": "src.bot",
        "format_road_alert": "src.bot",
        "format_beach_alert": "src.bot",
        "main_loop": "src.bot.orchestrator",
        "generate_and_send": "src.bot.orchestrator",
        "send_photo": "src.bot.transport",
        "send_message": "src.bot.transport",
    },
    # visualize_notams -> src.visualization (+ parser coord helper)
    "visualize_notams": {
        "render_map": "src.visualization",
        "render_notam_image": "src.visualization",
        "parse_coords_from_text": "src.parsers",
    },
}


def _flatten() -> list[tuple[str, str, str]]:
    """Yield ``(old_module, public_name, new_package_path)`` triples."""
    triples: list[tuple[str, str, str]] = []
    for old_module, names in OLD_MODULE_EXPORTS.items():
        for name, new_path in names.items():
            triples.append((old_module, name, new_path))
    return triples


ALL_EXPORTS = _flatten()
_IDS = [f"{old}:{name}" for old, name, _ in ALL_EXPORTS]


# ---------------------------------------------------------------------------
# Top-level re-export coverage (Requirement 1.3)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("old_module, name, new_path", ALL_EXPORTS, ids=_IDS)
def test_name_accessible_from_top_level_package(old_module, name, new_path):
    """Every previously-public name resolves from the top-level package."""
    assert hasattr(src, name), (
        f"{name!r} (formerly in {old_module!r}) is not accessible as "
        f"src.{name}"
    )


@pytest.mark.parametrize("old_module, name, new_path", ALL_EXPORTS, ids=_IDS)
def test_name_accessible_from_new_package_path(old_module, name, new_path):
    """Every previously-public name resolves from its new package path."""
    module = importlib.import_module(new_path)
    assert hasattr(module, name), (
        f"{name!r} (formerly in {old_module!r}) is not accessible from its "
        f"new location {new_path}.{name}"
    )


@pytest.mark.parametrize("old_module, name, new_path", ALL_EXPORTS, ids=_IDS)
def test_top_level_and_new_path_resolve_to_same_object(old_module, name, new_path):
    """The top-level re-export is the *same* object as the new-path export."""
    top_level_obj = getattr(src, name)
    new_path_obj = getattr(importlib.import_module(new_path), name)
    assert top_level_obj is new_path_obj, (
        f"src.{name} and {new_path}.{name} are different objects; "
        f"the top-level re-export should be a genuine alias"
    )


@pytest.mark.parametrize("old_module, name, new_path", ALL_EXPORTS, ids=_IDS)
def test_name_advertised_in_top_level_all(old_module, name, new_path):
    """Every re-exported name is advertised in ``src.__all__``."""
    assert name in src.__all__, (
        f"{name!r} is resolvable but missing from src.__all__"
    )


def test_all_only_contains_resolvable_names():
    """Every name in ``__all__`` actually resolves (no dangling entries)."""
    for name in src.__all__:
        assert hasattr(src, name), (
            f"src.__all__ advertises {name!r} but it cannot be resolved"
        )


def test_dir_includes_lazy_reexports():
    """``dir(src)`` surfaces the lazily re-exported names."""
    listed = set(dir(src))
    for _old, name, _new in ALL_EXPORTS:
        assert name in listed, f"{name!r} missing from dir(src)"


# ---------------------------------------------------------------------------
# Old-style ``from ... import ...`` statements (Requirement 1.3)
# ---------------------------------------------------------------------------
def test_from_data_import_save_notam_resolves():
    """The canonical example from the task: ``from src.data import save_notam``."""
    from src.data import save_notam

    assert callable(save_notam)


def test_representative_old_style_imports_resolve():
    """A spread of ``from <package> import <name>`` statements across every layer."""
    from src.core import logger  # noqa: F401
    from src.parsers import parse_notam, parse_coords_from_text  # noqa: F401
    from src.data import save_notam, init_db  # noqa: F401
    from src.scrapers import search_notams, faa_advisory_fetcher  # noqa: F401
    from src.bot import build_notam_caption  # noqa: F401
    from src.bot.transport import send_message  # noqa: F401
    from src.visualization import render_map  # noqa: F401


def test_top_level_from_import_resolves():
    """Names are importable directly off the top-level package too."""
    from src import save_notam, parse_notam, build_notam_caption

    assert callable(save_notam)
    assert callable(parse_notam)
    assert callable(build_notam_caption)


# ---------------------------------------------------------------------------
# Clear failure on missing names / modules (Requirement 8.3)
# ---------------------------------------------------------------------------
def test_unknown_top_level_attribute_raises_clear_attribute_error():
    """An unknown attribute raises AttributeError naming the missing attribute."""
    with pytest.raises(AttributeError) as excinfo:
        _ = src.this_name_does_not_exist  # type: ignore[attr-defined]
    message = str(excinfo.value)
    assert "this_name_does_not_exist" in message
    assert "src" in message


def test_import_of_missing_submodule_raises_clear_error():
    """Importing a genuinely missing submodule fails with a clear, named error."""
    with pytest.raises(ModuleNotFoundError) as excinfo:
        importlib.import_module("src.does_not_exist")
    assert "src.does_not_exist" in str(excinfo.value)
