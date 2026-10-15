"""Message formatting for Telegram posts.

Pure formatting functions extracted from the flat ``telegram_bot.py`` module.
This package produces HTML-formatted caption/message strings from plain Python
dictionaries. It performs NO network I/O and does NOT import the Telegram API.

Only standard library modules are used. Each source has its own submodule;
shared helpers live in ``_common``:

    notam             build_notam_caption(name, parsed) -> str
    faa               format_faa_activity(activity) -> str
                      format_faa_license(item) -> str
    starbase          format_road_alert(alert) -> str
                      format_beach_alert(alert) -> str
    fcc_els           format_fcc_els_application(app) -> str
    compass           format_compass_file(item) -> str
    federal_register  format_federal_register_document(item) -> str
    regulations_gov   format_regulations_gov_document(item) -> str
"""

from src.bot.formatting.compass import format_compass_file
from src.bot.formatting.faa import format_faa_activity, format_faa_license
from src.bot.formatting.fcc_els import format_fcc_els_application
from src.bot.formatting.federal_register import (
    format_federal_register_document,
)
from src.bot.formatting.notam import _CAPTION_LIMIT, build_notam_caption
from src.bot.formatting.regulations_gov import format_regulations_gov_document
from src.bot.formatting.starbase import (
    DEST_TRANSLATION,
    format_beach_alert,
    format_road_alert,
    translate_place,
)

__all__ = [
    "DEST_TRANSLATION",
    "build_notam_caption",
    "format_beach_alert",
    "format_compass_file",
    "format_faa_activity",
    "format_faa_license",
    "format_fcc_els_application",
    "format_federal_register_document",
    "format_regulations_gov_document",
    "format_road_alert",
    "translate_place",
]
