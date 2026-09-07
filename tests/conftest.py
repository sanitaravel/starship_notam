"""Shared pytest fixtures for the starship_notam test suite.

Provides:
    - ``db_path``      : a temporary, isolated SQLite database wired to the data
                          layer via the ``NOTAM_DB_PATH`` environment variable.
    - ``initialized_db``: the same temporary database with the schema created.
    - ``sample_notam_text``      : a realistic raw ICAO NOTAM string.
    - ``sample_carf_text``       : a realistic CARF/TFR-style NOTAM string.
    - ``sample_faa_advisory_html``: sample FAA advisory HTML.
    - ``sample_starbase_html``    : sample Starbase closures HTML.

Notes
-----
The data layer (``starship_notam.data.connection``) opens a *new* SQLite
connection for every call and resolves the database path from the
``NOTAM_DB_PATH`` environment variable when no explicit ``db_path`` is passed.
A single ``:memory:`` database cannot be shared across those independent
connections, so the ``db_path`` fixture uses a temporary file instead. This
keeps every test fully isolated while exercising the real connection factory
and schema-creation logic.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def db_path(tmp_path, monkeypatch) -> str:
    """Return a path to an isolated, temporary SQLite database.

    The path is also exported via the ``NOTAM_DB_PATH`` environment variable so
    that data-layer functions called without an explicit ``db_path`` argument
    resolve to this temporary database rather than the project's real
    ``notams.db``.
    """
    path = tmp_path / "test_notams.db"
    monkeypatch.setenv("NOTAM_DB_PATH", str(path))
    return str(path)


@pytest.fixture
def initialized_db(db_path) -> str:
    """Return the path to a temporary database with the schema created.

    Uses the real :func:`starship_notam.data.connection.init_db` so that tests
    exercise the production schema-creation and migration logic.
    """
    from starship_notam.data.connection import init_db

    init_db(db_path)
    return db_path


# ---------------------------------------------------------------------------
# Sample NOTAM text fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def sample_notam_text() -> str:
    """A realistic ICAO-style NOTAM with Q, A-G labelled fields."""
    return (
        "Q) KZHU/QRTCA/IV/BO/W/000/180/2559N09709W025\n"
        "A) KZHU\n"
        "B) 2607081350\n"
        "C) 2607160500\n"
        "E) STARSHIP SUPER HEAVY LAUNCH OPERATIONS. TEMPORARY FLIGHT "
        "RESTRICTION WITHIN AN AREA DEFINED AS 2.5NM RADIUS OF "
        "255950N0970921W SFC-18000FT.\n"
        "F) SFC\n"
        "G) 18000FT"
    )


@pytest.fixture
def sample_carf_text() -> str:
    """A realistic CARF/TFR-style NOTAM message beginning with '!CARF'."""
    return (
        "!CARF 06/123 ZHU STARSHIP LAUNCH OPERATIONS AREA "
        "255950N0970921W TO 260500N0970500W TO 255400N0964800W "
        "SFC-18000FT 2607081350-2607160500"
    )


# ---------------------------------------------------------------------------
# Sample HTML fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def sample_faa_advisory_html() -> str:
    """Sample FAA System Operations advisory HTML with a planned launch."""
    return (
        "<html><body><pre>"
        "PLANNED LAUNCH/REENTRY:\n"
        "STARSHIP FLIGHT TEST, BOCA CHICA, TX\n"
        "PRIMARY: 08 JUL 25 1350-2359Z\n"
        "BACKUP: 09 JUL 25 1350-2359Z\n"
        "FLIGHT CHECK(S): NONE\n"
        "VIP MOVEMENT(S): NONE\n"
        "</pre></body></html>"
    )


@pytest.fixture
def sample_starbase_html() -> str:
    """Sample Starbase status page HTML with beach and road closure notices."""
    return (
        "<html><body>"
        # --- Beach closure notice ---
        '<div class="beach-public-notice">'
        '  <div class="notice-container">'
        "    <h3>Beach &amp; Boca Chica Blvd Closure</h3>"
        '    <div class="w-richtext"><p>Primary launch window closure.</p></div>'
        '    <div class="closure-dates">'
        '      <div class="cms-big-text">Primary</div>'
        '      <div class="cms-small-text">July 8 from 1:00 PM to 11:00 PM CT</div>'
        "    </div>"
        "  </div>"
        "</div>"
        # --- Road closure notice ---
        '<div id="road-closure">'
        '  <div class="notice-container-no-hover road-updates">'
        '    <div id="rich-notification">'
        "      <p>Description: Road delay (from TX-4 to Boca Chica Beach)</p>"
        "      <p>Date: July 8 from 12:00 PM to 11:59 PM CT</p>"
        "    </div>"
        "  </div>"
        "</div>"
        "</body></html>"
    )


@pytest.fixture
def sample_parsed_notam() -> dict:
    """A parsed-NOTAM dictionary shaped like :func:`parse_notam` output.

    Useful for data-layer tests that call ``save_notam`` without re-running the
    parser.
    """
    return {
        "A": "KZHU",
        "B": "2026-07-08T13:50:00Z",
        "C": "2026-07-16T05:00:00Z",
        "E": "STARSHIP SUPER HEAVY LAUNCH OPERATIONS.",
        "F": "SFC",
        "G": "18000FT",
        "Q": {
            "location": "KZHU",
            "q_code": "QRTCA",
            "traffic": "IV",
            "traffic_rule": "BO",
            "lower": "000",
            "upper": "180",
            "coordinates": "2559N09709W",
            "radius_nm": "025",
        },
    }
