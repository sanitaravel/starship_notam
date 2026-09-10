"""Bot package: Telegram message formatting, transport, and orchestration.

Re-exports the public bot entry points. The formatting functions are pure and
carry no heavy dependencies, so they are imported eagerly:

    from starship_notam.bot import (
        build_notam_caption,
        format_faa_activity,
        format_road_alert,
        format_beach_alert,
    )
"""

from starship_notam.bot.formatting import (
    build_notam_caption,
    format_beach_alert,
    format_faa_activity,
    format_road_alert,
)

__all__ = [
    "build_notam_caption",
    "format_faa_activity",
    "format_road_alert",
    "format_beach_alert",
]
