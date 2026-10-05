"""One unparseable Starbase date must not break the whole page.

Regression test for fix-plan step 8: ``parse_rich_notification`` let the
``ValueError`` from ``parse_datetime_range`` escape, so a single malformed
date dropped every beach and road alert on the page.
"""

from __future__ import annotations

from starship_notam.parsers.starbase_parser import parse_starbase_html

PAGE = """
<html><body>
  <div id="road-closure">
    <div id="rich-notification">
      <p>Description: Pad to Production</p>
      <p>Date: July 8, 2026 from 8:00 AM to 5:00 PM</p>
      <p>Description: Masseys to Port</p>
      <p>Date: sometime next week, TBD</p>
    </div>
  </div>
</body></html>
"""


def test_bad_date_keeps_other_events():
    delays = parse_starbase_html(PAGE)["road_delays"]

    assert [(d["origin"], d["destination"]) for d in delays] == [
        ("Pad", "Production"),
        ("Masseys", "Port"),
    ]


def test_bad_date_event_keeps_raw_date_only():
    good, bad = parse_starbase_html(PAGE)["road_delays"]

    assert good["start_utc"] and good["end_utc"]
    assert bad["start_utc"] is None and bad["end_utc"] is None
    assert bad["raw_date"] == "sometime next week, TBD"
