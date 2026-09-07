"""Backward compatibility tests for the refactored ``starship_notam`` package.

These tests lock in Requirement 1.3 and 8.3:

* **1.3** — Every public function/object previously importable from the flat
  top-level modules (``notam_db``, ``notam_parser``, ``notam_request``,
  ``notam_logging``, ``telegram_bot``, ``visualize_notams``,
  ``fetch_faa_advisory``, ``fetch_starbase_closures``) is re-exported from
  ``starship_notam.__init__`` and remains resolvable.
* **8.3** — A missing/unknown attribute on the top-level package fails with a
  clear error message that names the missing attribute, and a request that maps
  onto a genuinely missing submodule fails with a clear ``ModuleNotFoundError``.

The test data below is derived from the *actual* re-export tables in
``starship_notam/__init__.py`` and each sub-package's ``__init__.py``. Each
entry pairs a public name with the new package path that owns it. For every
name we assert:

1. it is accessible as an attribute of the top-level ``starship_notam`` package;
2. it is accessible from its new package path (e.g. ``starship_notam.data``);
3. the two resolve to the *same* object (the top-level re-export is a genuine
   alias, not a divergent copy);
4. it is advertised in ``starship_notam.__all__`` so ``from starship_notam
   import *`` and tooling see it.
"""

from __future__ import annotations

import importlib

import pytest

import starship_notam


# ---------------------------------------------------------------------------
# The public API contract.
#
# Maps each old flat module to the (public name -> new package path) pairs that
# used to be importable from it. New package paths are the *packages* whose
# ``__init__`` re-exports the name, matching how a consumer would now import it,
# e.g. ``from starship_notam.data import save_notam``.
# ---------------------------------------------------------------------------
OLD_MODULE_EXPORTS: dict[str, dict[str, str]] = {
    # notam_db -> starship_notam.data
    "notam_db": {
        "get_connection": "starship_notam.data",
        "init_db": "starship_notam.data",
        "save_notam": "starship_notam.data",
        "get_notams_needing_images": "starship_notam.data",
        "mark_image_generated": "starship_notam.data",
        "load_all_notams": "starship_notam.data",
        "save_faa_activity": "starship_notam.data",
        "get_faa_activities_needing_post": "starship_notam.data",
        "mark_faa_activity_posted": "starship_notam.data",
        "save_beach_alert": "starship_notam.data",
        "save_road_alert": "starship_notam.data",
        "get_beach_alerts_needing_post": "starship_notam.data",
        "get_road_alerts_needing_post": "starship_notam.data",
        "mark_beach_posted": "starship_notam.data",
        "mark_road_posted": "starship_notam.data",
    },
    # notam_parser -> starship_notam.parsers
    "notam_parser": {
        "parse_notam": "starship_notam.parsers",
        "parse_carf_message": "starship_notam.parsers",
    },
    # notam_request -> starship_notam.scrapers
    "notam_request": {
        "search_notams": "starship_notam.scrapers",
    },
    # fetch_faa_advisory -> scrapers (fetch) + parsers (html parse)
    "fetch_faa_advisory": {
        "fetch_faa_advisory": "starship_notam.scrapers",
        "parse_faa_advisory_html": "starship_notam.parsers",
    },
    # fetch_starbase_closures -> scrapers (fetch) + parsers (html parse)
    "fetch_starbase_closures": {
        "fetch_starbase_status": "starship_notam.scrapers",
        "parse_starbase_html": "starship_notam.parsers",
    },
    # notam_logging -> starship_notam.core
    "notam_logging": {
        "TELEGRAM_BOT_TOKEN": "starship_notam.core",
        "CHAT_IDS": "starship_notam.core",
        "DB_PATH": "starship_notam.core",
        "KEYWORD": "starship_notam.core",
        "RUNS_PER_HOUR": "starship_notam.core",
        "STATE_PATH": "starship_notam.core",
        "logger": "starship_notam.core",
        "console": "starship_notam.core",
    },
    # telegram_bot -> starship_notam.bot (and bot submodules)
    "telegram_bot": {
        "build_notam_caption": "starship_notam.bot",
        "format_faa_activity": "starship_notam.bot",
        "format_road_alert": "starship_notam.bot",
        "format_beach_alert": "starship_notam.bot",
        "main_loop": "starship_notam.bot.orchestrator",
        "generate_and_send": "starship_notam.bot.orchestrator",
        "send_photo": "starship_notam.bot.transport",
        "send_message": "starship_notam.bot.transport",
        "refresh_known_chats": "starship_notam.bot.transport",
    },
    # visualize_notams -> starship_notam.visualization (+ parser coord helper)
    "visualize_notams": {
        "render_map": "starship_notam.visualization",
        "render_notam_image": "starship_notam.visualization",
        "parse_coords_from_text": "starship_notam.parsers",
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
    assert hasattr(starship_notam, name), (
        f"{name!r} (formerly in {old_module!r}) is not accessible as "
        f"starship_notam.{name}"
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
    top_level_obj = getattr(starship_notam, name)
    new_path_obj = getattr(importlib.import_module(new_path), name)
    assert top_level_obj is new_path_obj, (
        f"starship_notam.{name} and {new_path}.{name} are different objects; "
        f"the top-level re-export should be a genuine alias"
    )


@pytest.mark.parametrize("old_module, name, new_path", ALL_EXPORTS, ids=_IDS)
def test_name_advertised_in_top_level_all(old_module, name, new_path):
    """Every re-exported name is advertised in ``starship_notam.__all__``."""
    assert name in starship_notam.__all__, (
        f"{name!r} is resolvable but missing from starship_notam.__all__"
    )


def test_all_only_contains_resolvable_names():
    """Every name in ``__all__`` actually resolves (no dangling entries)."""
    for name in starship_notam.__all__:
        assert hasattr(starship_notam, name), (
            f"starship_notam.__all__ advertises {name!r} but it cannot be resolved"
        )


def test_dir_includes_lazy_reexports():
    """``dir(starship_notam)`` surfaces the lazily re-exported names."""
    listed = set(dir(starship_notam))
    for _old, name, _new in ALL_EXPORTS:
        assert name in listed, f"{name!r} missing from dir(starship_notam)"


# ---------------------------------------------------------------------------
# Old-style ``from ... import ...`` statements (Requirement 1.3)
# ---------------------------------------------------------------------------
def test_from_data_import_save_notam_resolves():
    """The canonical example from the task: ``from starship_notam.data import save_notam``."""
    from starship_notam.data import save_notam

    assert callable(save_notam)


def test_representative_old_style_imports_resolve():
    """A spread of ``from <package> import <name>`` statements across every layer."""
    from starship_notam.core import logger  # noqa: F401
    from starship_notam.parsers import parse_notam, parse_coords_from_text  # noqa: F401
    from starship_notam.data import save_notam, init_db  # noqa: F401
    from starship_notam.scrapers import search_notams, fetch_faa_advisory  # noqa: F401
    from starship_notam.bot import build_notam_caption  # noqa: F401
    from starship_notam.bot.transport import send_message  # noqa: F401
    from starship_notam.visualization import render_map  # noqa: F401


def test_top_level_from_import_resolves():
    """Names are importable directly off the top-level package too."""
    from starship_notam import save_notam, parse_notam, build_notam_caption

    assert callable(save_notam)
    assert callable(parse_notam)
    assert callable(build_notam_caption)


# ---------------------------------------------------------------------------
# Clear failure on missing names / modules (Requirement 8.3)
# ---------------------------------------------------------------------------
def test_unknown_top_level_attribute_raises_clear_attribute_error():
    """An unknown attribute raises AttributeError naming the missing attribute."""
    with pytest.raises(AttributeError) as excinfo:
        _ = starship_notam.this_name_does_not_exist  # type: ignore[attr-defined]
    message = str(excinfo.value)
    assert "this_name_does_not_exist" in message
    assert "starship_notam" in message


def test_import_of_missing_submodule_raises_clear_error():
    """Importing a genuinely missing submodule fails with a clear, named error."""
    with pytest.raises(ModuleNotFoundError) as excinfo:
        importlib.import_module("starship_notam.does_not_exist")
    assert "starship_notam.does_not_exist" in str(excinfo.value)
