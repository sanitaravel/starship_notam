"""Starship NOTAM monitoring and Telegram bot package.

This top-level package provides backward-compatible re-exports so that code
written against the original flat modules continues to work. The old flat
modules map onto the new sub-packages as follows:

    notam_db              -> starship_notam.data
    notam_parser          -> starship_notam.parsers
    notam_request         -> starship_notam.scrapers
    fetch_faa_advisory    -> starship_notam.scrapers
    fetch_starbase_closures -> starship_notam.scrapers
    notam_logging         -> starship_notam.core
    telegram_bot          -> starship_notam.bot
    visualize_notams      -> starship_notam.visualization

All public names are resolved lazily via a PEP 562 module-level ``__getattr__``.
This keeps ``import starship_notam`` cheap and side-effect free: heavy
dependencies (selenium, cartopy, matplotlib, python-telegram-bot, rich) are only
imported on first attribute access, and configuration (which requires
``TELEGRAM_BOT_TOKEN``) is not loaded merely by importing this package.
"""

from typing import Any

# Mapping of public name -> (submodule import path, attribute name).
# Resolution is deferred until the name is first accessed so that importing the
# top-level package never triggers config loading or heavy dependency imports.
_EXPORTS: dict[str, tuple[str, str]] = {
    # notam_db -> data
    "get_connection": ("starship_notam.data", "get_connection"),
    "init_db": ("starship_notam.data", "init_db"),
    "save_notam": ("starship_notam.data", "save_notam"),
    "get_notams_needing_images": ("starship_notam.data", "get_notams_needing_images"),
    "mark_image_generated": ("starship_notam.data", "mark_image_generated"),
    "load_all_notams": ("starship_notam.data", "load_all_notams"),
    "save_faa_activity": ("starship_notam.data", "save_faa_activity"),
    "get_faa_activities_needing_post": (
        "starship_notam.data",
        "get_faa_activities_needing_post",
    ),
    "mark_faa_activity_posted": ("starship_notam.data", "mark_faa_activity_posted"),
    "save_beach_alert": ("starship_notam.data", "save_beach_alert"),
    "save_road_alert": ("starship_notam.data", "save_road_alert"),
    "get_beach_alerts_needing_post": (
        "starship_notam.data",
        "get_beach_alerts_needing_post",
    ),
    "get_road_alerts_needing_post": (
        "starship_notam.data",
        "get_road_alerts_needing_post",
    ),
    "mark_beach_posted": ("starship_notam.data", "mark_beach_posted"),
    "mark_road_posted": ("starship_notam.data", "mark_road_posted"),
    # notam_parser -> parsers
    "parse_notam": ("starship_notam.parsers", "parse_notam"),
    "parse_carf_message": ("starship_notam.parsers", "parse_carf_message"),
    "parse_coords_from_text": ("starship_notam.parsers", "parse_coords_from_text"),
    "parse_faa_advisory_html": ("starship_notam.parsers", "parse_faa_advisory_html"),
    "parse_starbase_html": ("starship_notam.parsers", "parse_starbase_html"),
    # notam_request / fetch_faa_advisory / fetch_starbase_closures -> scrapers
    "search_notams": ("starship_notam.scrapers", "search_notams"),
    "fetch_faa_advisory": ("starship_notam.scrapers", "fetch_faa_advisory"),
    "fetch_starbase_status": ("starship_notam.scrapers", "fetch_starbase_status"),
    # notam_logging -> core
    "TELEGRAM_BOT_TOKEN": ("starship_notam.core", "TELEGRAM_BOT_TOKEN"),
    "CHAT_IDS": ("starship_notam.core", "CHAT_IDS"),
    "DB_PATH": ("starship_notam.core", "DB_PATH"),
    "KEYWORD": ("starship_notam.core", "KEYWORD"),
    "RUNS_PER_HOUR": ("starship_notam.core", "RUNS_PER_HOUR"),
    "STATE_PATH": ("starship_notam.core", "STATE_PATH"),
    "logger": ("starship_notam.core", "logger"),
    "console": ("starship_notam.core", "console"),
    # telegram_bot -> bot
    "build_notam_caption": ("starship_notam.bot", "build_notam_caption"),
    "format_faa_activity": ("starship_notam.bot", "format_faa_activity"),
    "format_road_alert": ("starship_notam.bot", "format_road_alert"),
    "format_beach_alert": ("starship_notam.bot", "format_beach_alert"),
    "main_loop": ("starship_notam.bot.orchestrator", "main_loop"),
    "generate_and_send": ("starship_notam.bot.orchestrator", "generate_and_send"),
    "send_photo": ("starship_notam.bot.transport", "send_photo"),
    "send_message": ("starship_notam.bot.transport", "send_message"),
    "refresh_known_chats": ("starship_notam.bot.transport", "refresh_known_chats"),
    # visualize_notams -> visualization
    "render_map": ("starship_notam.visualization", "render_map"),
    "render_notam_image": ("starship_notam.visualization", "render_notam_image"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    """Lazily resolve a re-exported public name (PEP 562).

    On first access the owning submodule is imported and the requested
    attribute is fetched, cached on this module's globals, and returned. This
    defers heavy dependency imports and configuration loading until a name is
    actually used.
    """
    try:
        module_path, attr = _EXPORTS[name]
    except KeyError:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}"
        ) from None

    import importlib

    module = importlib.import_module(module_path)
    value = getattr(module, attr)
    globals()[name] = value  # cache so subsequent access skips __getattr__
    return value


def __dir__() -> list[str]:
    """Include lazily re-exported names in ``dir(starship_notam)``."""
    return sorted(set(globals()) | set(_EXPORTS))
