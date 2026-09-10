"""Unit tests for :mod:`starship_notam.parsers.starbase_parser`.

Covers ``parse_starbase_html`` with sample HTML plus a determinism check
(Requirement 3.6).

Imports only the parsers layer (Requirements 9.1, 9.4).

Note: when a closure date string omits the year, the parser fills it from
``datetime.now().year``. To keep these assertions independent of the system
clock, the absolute year of ``start_utc``/``end_utc`` is not asserted; only
the structure, route, and time-of-day / offset are checked.
"""

from __future__ import annotations

from starship_notam.parsers import parse_starbase_html


# ---------------------------------------------------------------------------
# Beach closure
# ---------------------------------------------------------------------------
def test_parses_beach_closure(sample_starbase_html):
    result = parse_starbase_html(sample_starbase_html)
    beach = result["beach"]

    assert beach is not None
    assert beach["title"] == "Beach & Boca Chica Blvd Closure"
    assert beach["description"] == "Primary launch window closure."
    # Central 1:00 PM -> 18:00 UTC (CDT, -05:00 in July).
    assert beach["start_utc"] is not None
    assert beach["start_utc"].endswith("T18:00:00+00:00")
    assert beach["end_utc"].endswith("T04:00:00+00:00")
    assert beach["raw_date"] == "July 8 from 1:00 PM to 11:00 PM CT"


def test_beach_periods_structure(sample_starbase_html):
    result = parse_starbase_html(sample_starbase_html)
    periods = result["beach"]["periods"]

    assert len(periods) == 1
    assert periods[0]["label"] == "Primary"
    assert periods[0]["raw_date"] == "July 8 from 1:00 PM to 11:00 PM CT"


# ---------------------------------------------------------------------------
# Road delays
# ---------------------------------------------------------------------------
def test_parses_road_delay(sample_starbase_html):
    result = parse_starbase_html(sample_starbase_html)
    road_delays = result["road_delays"]

    assert len(road_delays) == 1
    delay = road_delays[0]
    assert delay["description"] == "Road delay (from TX-4 to Boca Chica Beach)"
    assert delay["origin"] == "TX-4"
    assert delay["destination"] == "Boca Chica Beach"
    # Central 12:00 PM -> 17:00 UTC; 11:59 PM -> 04:59 UTC next day.
    assert delay["start_utc"].endswith("T17:00:00+00:00")
    assert delay["end_utc"].endswith("T04:59:00+00:00")
    assert delay["raw_date"] == "July 8 from 12:00 PM to 11:59 PM CT"


def test_parses_multiple_road_delays_in_one_notification():
    """A rich-notification with several Description/Date pairs yields one
    road-delay entry per event (regression: only the first was kept)."""
    html = (
        "<html><body>"
        '<div id="road-closure" class="road-updates">'
        '  <div class="collection-list w-dyn-items">'
        '    <div class="cms-item-2 w-dyn-item">'
        '      <div class="notice-container-no-hover road-updates">'
        '        <div class="cms-big-text">Road Delay</div>'
        '        <div class="cms-big-text empty-state w-condition-invisible">'
        "          No road delays."
        "        </div>"
        '        <div id="rich-notification" class="w-richtext">'
        "          Description: Production to Pad<br/>"
        "          Date: September 7 11:59 PM to September 8 4:00 AM<br/><br/>"
        "          Description: Production to Masseys<br/>"
        "          Date: September 7 11:59 PM to September 8 4:00 AM"
        "        </div>"
        "      </div>"
        "    </div>"
        "  </div>"
        "</div>"
        "</body></html>"
    )

    result = parse_starbase_html(html)
    road_delays = result["road_delays"]

    assert len(road_delays) == 2

    first, second = road_delays
    assert first["description"] == "Production to Pad"
    assert first["origin"] == "Production"
    assert first["destination"] == "Pad"
    assert second["description"] == "Production to Masseys"
    assert second["origin"] == "Production"
    assert second["destination"] == "Masseys"


# ---------------------------------------------------------------------------
# Empty / missing sections
# ---------------------------------------------------------------------------
def test_empty_html_returns_default_shape():
    result = parse_starbase_html("<html><body></body></html>")

    assert result == {"beach": None, "road_delays": []}


def test_result_always_has_expected_top_level_keys(sample_starbase_html):
    result = parse_starbase_html(sample_starbase_html)

    assert set(result.keys()) == {"beach", "road_delays"}
    assert isinstance(result["road_delays"], list)


# ---------------------------------------------------------------------------
# Determinism (Requirement 3.6)
# ---------------------------------------------------------------------------
def test_parse_starbase_html_is_deterministic(sample_starbase_html):
    assert parse_starbase_html(sample_starbase_html) == parse_starbase_html(
        sample_starbase_html
    )
