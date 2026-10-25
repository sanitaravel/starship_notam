"""Starship NOTAM monitoring and Telegram bot package.

This top-level package provides backward-compatible re-exports so that code
written against the original flat modules continues to work. The old flat
modules map onto the new sub-packages as follows:

    notam_db              -> src.data
    notam_parser          -> src.parsers
    notam_request         -> src.scrapers
    fetch_faa_advisory    -> src.scrapers
    fetch_starbase_closures -> src.scrapers
    notam_logging         -> src.core
    telegram_bot          -> src.bot
    visualize_notams      -> src.visualization

All public names are resolved lazily via a PEP 562 module-level ``__getattr__``.
This keeps ``import src`` cheap and side-effect free: heavy
dependencies (cartopy, matplotlib, python-telegram-bot, rich) are only
imported on first attribute access, and configuration (which requires
``TELEGRAM_BOT_TOKEN``) is not loaded merely by importing this package.
"""

from typing import Any

# Mapping of public name -> (submodule import path, attribute name).
# Resolution is deferred until the name is first accessed so that importing the
# top-level package never triggers config loading or heavy dependency imports.
_EXPORTS: dict[str, tuple[str, str]] = {
    # notam_db -> data
    "get_connection": ("src.data", "get_connection"),
    "init_db": ("src.data", "init_db"),
    "save_notam": ("src.data", "save_notam"),
    "get_notams_needing_images": ("src.data", "get_notams_needing_images"),
    "mark_image_generated": ("src.data", "mark_image_generated"),
    "load_all_notams": ("src.data", "load_all_notams"),
    "faa_activities": ("src.data", "faa_activities"),
    "beach_alerts": ("src.data", "beach_alerts"),
    "road_alerts": ("src.data", "road_alerts"),
    # notam_parser -> parsers
    "parse_notam": ("src.parsers", "parse_notam"),
    "parse_carf_message": ("src.parsers", "parse_carf_message"),
    "parse_coords_from_text": ("src.parsers", "parse_coords_from_text"),
    "parse_faa_advisory_html": ("src.parsers", "parse_faa_advisory_html"),
    "parse_starbase_html": ("src.parsers", "parse_starbase_html"),
    # notam_request / fetch_faa_advisory / fetch_starbase_closures -> scrapers
    "search_notams": ("src.scrapers", "search_notams"),
    "faa_advisory_fetcher": ("src.scrapers", "faa_advisory_fetcher"),
    "starbase_status_fetcher": ("src.scrapers", "starbase_status_fetcher"),
    # notam_logging -> core
    "TELEGRAM_BOT_TOKEN": ("src.core", "TELEGRAM_BOT_TOKEN"),
    "TELEGRAM_CHANNEL_ID": ("src.core", "TELEGRAM_CHANNEL_ID"),
    "DB_PATH": ("src.core", "DB_PATH"),
    "KEYWORD": ("src.core", "KEYWORD"),
    "RUNS_PER_HOUR": ("src.core", "RUNS_PER_HOUR"),
    "logger": ("src.core", "logger"),
    "console": ("src.core", "console"),
    # telegram_bot -> bot
    "build_notam_caption": ("src.bot", "build_notam_caption"),
    "format_faa_activity": ("src.bot", "format_faa_activity"),
    "format_road_alert": ("src.bot", "format_road_alert"),
    "format_beach_alert": ("src.bot", "format_beach_alert"),
    "main_loop": ("src.bot.orchestrator", "main_loop"),
    "generate_and_send": ("src.bot.orchestrator", "generate_and_send"),
    "send_photo": ("src.bot.transport", "send_photo"),
    "send_message": ("src.bot.transport", "send_message"),
    # visualize_notams -> visualization
    "render_map": ("src.visualization", "render_map"),
    "render_notam_image": ("src.visualization", "render_notam_image"),
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
    """Include lazily re-exported names in ``dir(src)``."""
    return sorted(set(globals()) | set(_EXPORTS))
