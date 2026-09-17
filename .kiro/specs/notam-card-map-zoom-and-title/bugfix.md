# Bugfix Requirements Document

## Introduction

Two related defects appear on the rendered NOTAM card, observed on NOTAM
A1237/26 — a SpaceX Starship FLT-14 temporary danger area in the Tahiti FIR
(a short curved polyline near French Polynesia, roughly 19–24°S, 148–150°W):

1. **Map too zoomed out.** For NOTAM geometry located far from any large
   landmass (open ocean), the generated map image renders a near-global view.
   The NOTAM area occupies a tiny fraction of the frame while most of the map
   shows empty ocean and unrelated continents (e.g. South America). The map
   should fit to the NOTAM geometry with appropriate padding.

2. **Card title/details not shortened.** For Starship-related NOTAMs whose
   wording is not recognized by the summarization step, the full raw NOTAM
   text is rendered verbatim on the card (e.g. "TEMPORARY DANGER AREA DUE TO
   SPACE DEBRIS RETURN OF SPACEX STARSHIP FLT-14 IN TAHITI FIR WITHIN AN AREA
   BOUNDED BY FOLLOWING POINTS: 1951S 14900W, 1923S 14849W, 2458S...") and
   overflows the card. It should be shortened/summarized to a concise line.

Both defects surface on the NOTAM image card. The map behavior originates in
`starship_notam/visualization/map_renderer.py`; the title/details behavior
originates in `starship_notam/visualization/image_composer.py`
(`extract_starship_template`, which feeds the card `details`).

## Bug Analysis

### Current Behavior (Defect)

Bug 1 — Map extent for ocean NOTAMs:

1.1 WHEN a NOTAM polygon or point sits far from any landmass large enough to satisfy the land-visibility check THEN the map renderer progressively expands the extent (up to a near-global half-span) until distant, unrelated land becomes visible, so the NOTAM geometry occupies only a tiny fraction of the frame.

1.2 WHEN a NOTAM extent is computed from the geometry bounds THEN the renderer multiplies both half-spans by the global extent scale factor (currently `MAP_EXTENT_SCALE = 2`), further shrinking the on-screen footprint of the NOTAM geometry.

Bug 2 — Card title/details for unrecognized Starship NOTAMs:

1.3 WHEN a Starship-related NOTAM's text does not match any known summarization template (e.g. the wording "TEMPORARY DANGER AREA DUE TO SPACE DEBRIS RETURN OF SPACEX STARSHIP FLT-14") THEN the summarization step returns no summary and the card falls back to rendering the full raw NOTAM text.

1.4 WHEN the full raw NOTAM text is used as the card details THEN the text (including the bounding-points coordinate list) overflows the card layout instead of being shortened to fit.

### Expected Behavior (Correct)

Bug 1 — Map extent for ocean NOTAMs:

2.1 WHEN a NOTAM polygon or point sits far from any large landmass THEN the system SHALL keep the map fitted to the NOTAM geometry (with appropriate padding) rather than expanding to a near-global view to reveal distant unrelated land, so the NOTAM area occupies a prominent, legible portion of the frame.

2.2 WHEN a NOTAM extent is computed from the geometry bounds THEN the system SHALL apply padding/scaling that keeps the NOTAM geometry as the dominant feature of the rendered frame.

Bug 2 — Card title/details for unrecognized Starship NOTAMs:

2.3 WHEN a Starship-related NOTAM's text does not match a known summarization template THEN the system SHALL still produce a shortened card details line rather than emitting the full raw NOTAM text.

2.4 WHEN card details would otherwise contain the full raw NOTAM text (including a bounding-points coordinate list) THEN the system SHALL shorten/summarize the text so it fits the card layout without overflowing.

### Unchanged Behavior (Regression Prevention)

3.1 WHEN a NOTAM geometry already sits near a large landmass THEN the system SHALL CONTINUE TO fit the map to the geometry with its existing padding and aspect-ratio correction.

3.2 WHEN a NOTAM is a point with a radius THEN the system SHALL CONTINUE TO render the circle fitted to that radius as it does today.

3.3 WHEN a NOTAM has no parseable coordinates THEN the system SHALL CONTINUE TO fall back to the default global map extent.

3.4 WHEN a Starship-related NOTAM's text matches an existing summarization template (ascent, reentry, splashdown, debris/launch hazard, ground hazard, etc.) THEN the system SHALL CONTINUE TO produce the same summarized card details line it produces today.

3.5 WHEN a non-Starship NOTAM is rendered THEN the system SHALL CONTINUE TO derive its card details from the existing E/D fields as it does today.

3.6 WHEN the map is rendered THEN the system SHALL CONTINUE TO draw coastlines, land/ocean fill, country and feature labels, graticule, and the Starbase marker as it does today.
