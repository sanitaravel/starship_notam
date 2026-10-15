"""Parsers package: pure-function text parsing with no I/O dependencies.

Re-exports the public parser entry points:
    from src.parsers import parse_notam, parse_carf_message, parse_coords_from_text
    from src.parsers import parse_faa_advisory_html
    from src.parsers import parse_starbase_html
"""

from src.parsers.coord_parser import parse_coords_from_text
from src.parsers.faa_parser import parse_faa_advisory_html
from src.parsers.notam_parser import parse_carf_message, parse_notam
from src.parsers.starbase_parser import parse_starbase_html

__all__ = [
    "parse_notam",
    "parse_carf_message",
    "parse_coords_from_text",
    "parse_faa_advisory_html",
    "parse_starbase_html",
]
