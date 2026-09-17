# NOTAM Card Map Zoom and Title Bugfix Design

## Overview

Two defects surface on the rendered NOTAM card, observed on NOTAM A1237/26 — a
SpaceX Starship FLT-14 temporary danger area in the Tahiti FIR (a short curved
polyline near French Polynesia, roughly 19–24°S, 148–150°W):

1. **Map too zoomed out.** For NOTAM geometry located far from any large
   landmass (open ocean), the map image renders a near-global view. The NOTAM
   area occupies a tiny fraction of the frame while the rest shows empty ocean
   and unrelated continents (e.g. South America).

2. **Card title/details not shortened.** For Starship-related NOTAMs whose exact
   wording is not recognized by the summarization step, the card renders the
   full raw NOTAM text verbatim (including the bounding-points coordinate list),
   which overflows the card layout.

The fix strategy is minimal and targeted:

- **Bug 1** lives in `starship_notam/visualization/map_renderer.py`. Two
  cooperating mechanisms shrink the NOTAM's on-screen footprint: the
  `MAP_EXTENT_SCALE = 2` factor doubles both half-spans, and
  `_expand_extent_until_land()` iteratively balloons the extent (up to a
  near-global half-span) hunting for distant land. The fix reduces/neutralizes
  the extent scale so the geometry stays dominant, and constrains the
  land-visibility expansion so it no longer zooms an open-ocean NOTAM out to a
  near-global view.

- **Bug 2** lives in `starship_notam/visualization/image_composer.py`
  (`extract_starship_template`). The flight number is extracted correctly
  (`STARSHIP FLT-14` → `14`), but the "SPACE DEBRIS RETURN OF SPACEX STARSHIP
  FLT-14" / singular "TEMPORARY DANGER AREA" wording matches none of the
  classification keyword lists, so the function returns `None` and the caller
  falls back to the full raw text. The fix extends the debris/hazard
  classification (and adds a safe generic fallback for recognized Starship
  flights) so a concise summarized line is produced.

Neither fix changes behavior for inputs that already work today.

## Glossary

- **Bug_Condition (C)**: The condition that triggers a defect — (1) a NOTAM
  geometry far from large land that gets rendered at a near-global extent, or
  (2) a Starship-flight NOTAM whose wording is unrecognized so the card falls
  back to raw text.
- **Property (P)**: The desired behavior — (1) the map stays fitted to the NOTAM
  geometry so it dominates the frame; (2) the card details are a concise
  summarized line, not the raw NOTAM text.
- **Preservation**: Existing map behavior for land-adjacent NOTAMs, points with
  radius, and no-coordinate fallbacks, plus existing summarization for already
  recognized templates and non-Starship NOTAMs.
- **`render_map`**: The function in `starship_notam/visualization/map_renderer.py`
  that computes the map extent from `coords` and renders the map tile.
- **`MAP_EXTENT_SCALE`**: Module constant in `map_renderer.py` (currently `2`)
  that multiplies both extent half-spans, zooming out.
- **`_expand_extent_until_land`**: Helper in `map_renderer.py` that iteratively
  grows the extent around its center until a large landmass is visible.
- **`extract_starship_template`**: The function in
  `starship_notam/visualization/image_composer.py` that maps a raw NOTAM string
  to a concise Russian-language summary line, or `None` when no template
  matches.
- **`_notam_from_db_row`**: The caller in `image_composer.py` that uses the
  `extract_starship_template` result as `details`, falling back to the raw
  E/D text when the template returns `None`.

## Bug Details

### Bug Condition

**Bug 1 (map extent).** The bug manifests when a NOTAM polygon or point sits far
enough from a large landmass that the land-visibility check fails on the fitted
extent. `render_map` then (a) multiplies both half-spans by `MAP_EXTENT_SCALE`
and (b) calls `_expand_extent_until_land`, which repeatedly grows the extent by
`LAND_ZOOM_OUT_FACTOR` (1.6) up to `MAX_EXTENT_HALF_SPAN` (90°) until distant
land appears. The result is a near-global view in which the NOTAM geometry is a
tiny fraction of the frame.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input = { coords, radius_nm, size }
  OUTPUT: boolean

  fitted := computeFittedExtent(coords, size, radius_nm)   // pre-scale, pre-land-expansion
  RETURN coords is not empty
         AND NOT extentHasVisibleLand(fitted, size)         // open-ocean geometry
         AND renderedExtentSpan(input) >> fittedExtentSpan(fitted)
             // the extent actually used balloons far beyond the fitted geometry
END FUNCTION
```

**Bug 2 (card title/details).** The bug manifests when a NOTAM's text contains a
recognizable Starship flight number but its classification wording matches none
of the keyword lists in `extract_starship_template`. Concretely, "SPACE DEBRIS
RETURN OF SPACEX STARSHIP FLT-14 ... TEMPORARY DANGER AREA" yields `flight = 14`
but no classification branch fires (the debris list contains "TEMPORARY DANGER
AREAS" plural, not the singular form, and lacks "SPACE DEBRIS" / "DEBRIS
RETURN"). The function returns `None`, and `_notam_from_db_row` falls back to the
full raw text.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input = raw NOTAM text (string)
  OUTPUT: boolean

  RETURN containsStarshipFlightNumber(input)          // e.g. STARSHIP FLT-14
         AND extract_starship_template(input) IS None // no classification matched
END FUNCTION
```

### Examples

- **Bug 1:** NOTAM A1237/26 polyline near Tahiti FIR (~19–24°S, 148–150°W).
  Expected: map fitted to the ~5° polyline span with padding. Actual: near-global
  view showing South America, NOTAM barely visible.
- **Bug 1 (scale):** A land-adjacent polygon spanning ~1° gets both half-spans
  doubled by `MAP_EXTENT_SCALE = 2`, so it appears ~4× smaller in area than a
  tight fit would show. Expected: NOTAM remains the dominant feature.
- **Bug 2:** Raw text "TEMPORARY DANGER AREA DUE TO SPACE DEBRIS RETURN OF SPACEX
  STARSHIP FLT-14 IN TAHITI FIR WITHIN AN AREA BOUNDED BY FOLLOWING POINTS: 1951S
  14900W, 1923S 14849W, 2458S ...". Expected: a concise summary line (e.g. the
  debris/hazard template with FLT-14). Actual: the full raw string (with the
  coordinate list) rendered on the card, overflowing.
- **Bug 2 (edge):** A Starship NOTAM whose wording matches an existing template
  (e.g. "REENTRY ... SPLASHDOWN") — expected behavior unchanged (still summarized).

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- Map fitting for NOTAM geometry already near a large landmass — existing
  padding and cos(lat) aspect-ratio correction must be preserved.
- Point-with-radius rendering — the circle fitted to the radius must render as
  it does today.
- No-coordinate fallback — a NOTAM with no parseable coordinates must still fall
  back to the default global extent `[-180, 180, -90, 90]`.
- Existing summarization templates (ascent, reentry, splashdown, debris/launch
  hazard, ground hazard, high-energy testing, Pacific re-entry) must produce the
  same summary line they produce today.
- Non-Starship NOTAMs must still derive their details from the existing E/D
  fields.
- Map cartography — coastlines, land/ocean fill, country/feature labels,
  graticule, and the Starbase, TX marker must still render.

**Scope:**
All inputs that do NOT satisfy a bug condition must be completely unaffected by
this fix. For Bug 1 that means land-adjacent geometries, radius points, and
no-coordinate cases. For Bug 2 that means NOTAMs already matched by a template
and all non-Starship NOTAMs.

**Note:** The expected *correct* behavior for buggy inputs is defined in the
Correctness Properties section (Property 1); this section defines what must NOT
change.

## Hypothesized Root Cause

**Bug 1 — Map extent for ocean NOTAMs**

1. **Extent scale over-zooms every NOTAM.** `MAP_EXTENT_SCALE = 2` multiplies
   both half-spans for both the polygon and point branches, halving the NOTAM's
   linear footprint (quartering its area) even before any land search.

2. **Land-visibility expansion balloons open-ocean extents.** `render_map` calls
   `_expand_extent_until_land(extent, size)` whenever `coords` is truthy. For an
   open-ocean NOTAM the fitted extent has no large land, so the helper grows the
   half-spans by `LAND_ZOOM_OUT_FACTOR = 1.6` per step up to
   `MAX_EXTENT_HALF_SPAN = 90.0`, producing a near-global view to reveal distant
   land (South America). This directly causes the reported symptom.

**Bug 2 — Card title/details for unrecognized Starship NOTAMs**

1. **Classification keyword gap.** The flight number extraction succeeds
   (`STARSHIP\s+FLT[- ]?(\d+)` matches `FLT-14`), but the debris/hazard branch
   keyword list contains `"TEMPORARY DANGER AREAS"` (plural) and omits the
   singular `"TEMPORARY DANGER AREA"`, `"SPACE DEBRIS"`, and `"DEBRIS RETURN"`.
   None of the other branches (ascent, reentry, splashdown, ground hazard)
   match this wording, so the function returns `None`.

2. **No generic fallback for recognized flights.** Even when a Starship flight
   number is recognized, an unclassified wording produces `None` rather than a
   safe generic summary, so the caller emits the full raw text.

## Correctness Properties

Property 1: Bug Condition — Ocean NOTAM stays fitted and Starship title is summarized

_For any_ input where the bug condition holds (isBugCondition returns true):

- **Map (1a):** _For any_ NOTAM geometry far from a large landmass, the fixed
  `render_map` SHALL keep the map fitted to the NOTAM geometry with appropriate
  padding so the geometry is the dominant, legible feature of the frame, rather
  than expanding to a near-global view to reveal distant unrelated land.
- **Title (1b):** _For any_ Starship-related NOTAM whose wording is not matched
  by an existing template, the fixed `extract_starship_template` SHALL return a
  concise, non-empty summary line (not `None`), so the card details are
  shortened rather than falling back to the full raw NOTAM text.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4**

Property 2: Preservation — Unchanged behavior for non-buggy inputs

_For any_ input where the bug condition does NOT hold (isBugCondition returns
false), the fixed code SHALL produce the same result as the original code,
preserving:

- Map fitting, padding, and aspect-ratio correction for land-adjacent geometry.
- Point-with-radius circle rendering.
- The default global extent for NOTAMs with no parseable coordinates.
- The existing summary line for every already-recognized Starship template.
- E/D-derived details for non-Starship NOTAMs.
- Coastlines, land/ocean fill, labels, graticule, and the Starbase marker.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6**

## Fix Implementation

### Changes Required — Bug 1 (map extent)

**File**: `starship_notam/visualization/map_renderer.py`

**Functions / constants**: `MAP_EXTENT_SCALE`, `render_map`, land-visibility
expansion constants (`LAND_ZOOM_OUT_FACTOR`, `LAND_ZOOM_OUT_MAX_STEPS`,
`MAX_EXTENT_HALF_SPAN`), and the `_expand_extent_until_land` call site.

**Specific Changes**:
1. **Neutralize/relax the extent scale.** Change `MAP_EXTENT_SCALE` so it no
   longer doubles the geometry footprint. Set it to `1.0` (no extra zoom-out) or
   a small padding value (e.g. `1.1`) so the NOTAM geometry remains dominant.
   This preserves the existing padding (`lat_pad`/`lon_pad`) and aspect-ratio
   correction already applied before scaling. Applies to both the polygon and
   point branches, which share the constant.

2. **Constrain the land-visibility expansion.** Prevent
   `_expand_extent_until_land` from ballooning open-ocean NOTAMs to a near-global
   view. Preferred approach: cap the expansion so the extent never grows beyond a
   small multiple of the fitted geometry span (i.e. bound the total zoom-out
   relative to the fitted half-spans rather than the absolute
   `MAX_EXTENT_HALF_SPAN = 90°`). When no land can be found within that bounded
   window, return the fitted extent unchanged so the NOTAM stays fitted rather
   than showing distant continents. (An alternative is to skip the land search
   entirely for geometries whose fitted span is small; the bounded-expansion
   approach keeps land visible when it is genuinely nearby.)

3. **Keep the ocean fallback graceful.** Retain the existing default global
   extent path for the no-coordinate case (unchanged), and retain the
   land-visibility helper's exception handling that returns the original extent.

4. **Do not alter cartography.** Leave feature drawing (ocean/land fill,
   coastlines, country/feature labels, graticule, Starbase marker) untouched.

### Changes Required — Bug 2 (card title/details)

**File**: `starship_notam/visualization/image_composer.py`

**Function**: `extract_starship_template`

**Specific Changes**:
1. **Extend the debris/hazard classification keywords.** Add the missing wording
   variants to the debris/launch-hazard branch so the observed NOTAM matches:
   include the singular `"TEMPORARY DANGER AREA"`, plus `"SPACE DEBRIS"` and
   `"DEBRIS RETURN"` (and any close variants such as `"RETURN OF"` debris
   phrasing). This makes "SPACE DEBRIS RETURN OF SPACEX STARSHIP FLT-14 ...
   TEMPORARY DANGER AREA" resolve to the existing debris summary line
   (`ВОЗМОЖНОЕ ПАДЕНИЕ ОБЛОМКОВ В РЕЗУЛЬТАТЕ ЗАПУСКА SPACEX STARSHIP FLT-{flight}`).

2. **Add a safe generic fallback for recognized flights.** After the specific
   classification branches, when a Starship flight number was successfully
   extracted but no specific branch matched, return a concise generic Starship
   summary line (e.g. a flight-referencing line) instead of `None`. This ensures
   any future unrecognized Starship wording still yields a shortened card line
   rather than raw text. The fallback must only apply when a flight number was
   found, so non-Starship text still returns `None`.

3. **Preserve ordering and existing branches.** Do not reorder or weaken the
   existing template branches; the new keywords are additive and the generic
   fallback is reached only after all specific branches fail.

4. **No caller changes required.** `_notam_from_db_row` already uses the template
   result as `details` when non-empty and falls back to E/D otherwise; returning
   a non-empty line is sufficient to fix the overflow.

## Testing Strategy

### Validation Approach

Two phases: first surface counterexamples that demonstrate each bug on the
unfixed code, then verify the fix produces the correct behavior and preserves
existing behavior.

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples that demonstrate the bugs BEFORE implementing
the fix, and confirm or refute the root-cause hypotheses.

**Test Plan**: Exercise `render_map` extent computation and
`extract_starship_template` on the A1237/26 inputs and assert the (currently
wrong) behavior, to lock in the root cause.

**Test Cases**:
1. **Ocean extent test**: Compute the extent used for the Tahiti-FIR polyline
   and assert the rendered half-span is far larger than the fitted geometry span
   (will demonstrate ballooning on unfixed code).
2. **Extent scale test**: For a small land-adjacent polygon, assert the extent
   half-span equals the fitted half-span times `MAP_EXTENT_SCALE` (documents the
   2× zoom-out on unfixed code).
3. **Template miss test**: Call `extract_starship_template` with the observed
   "SPACE DEBRIS RETURN OF SPACEX STARSHIP FLT-14 ... TEMPORARY DANGER AREA" text
   and assert it returns `None` (reproduces Bug 2 on unfixed code).
4. **Overflow fallback test**: Call `_notam_from_db_row` with the raw text and
   assert `details` equals the full raw string including the coordinate list
   (may fail/expose the overflow source on unfixed code).

**Expected Counterexamples**:
- The map extent for the ocean polyline is near-global.
- `extract_starship_template` returns `None` for the FLT-14 debris wording.
- Possible causes: `MAP_EXTENT_SCALE` doubling, `_expand_extent_until_land`
  ballooning, and the debris keyword gap.

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds, the fixed
functions produce the expected behavior.

**Pseudocode:**
```
// Map
FOR ALL input WHERE isBugConditionMap(input) DO
  extent := computeRenderedExtent(input)
  ASSERT extentSpan(extent) <= boundedMultiple * fittedSpan(input.coords)
END FOR

// Title
FOR ALL text WHERE isBugConditionTitle(text) DO
  result := extract_starship_template(text)
  ASSERT result IS NOT None AND length(result) is concise (no coordinate list)
END FOR
```

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold, the
fixed functions produce the same result as the original functions.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT original_render_map_extent(input)        = fixed_render_map_extent(input)
  ASSERT original_extract_template(input)         = fixed_extract_template(input)
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation
checking because it generates many inputs across the domain (varied polygon
spans, latitudes, radii, and NOTAM wordings), catching edge cases manual tests
miss and giving strong assurance that non-buggy behavior is unchanged.

**Test Plan**: Observe behavior on unfixed code for land-adjacent geometries,
radius points, no-coordinate cases, recognized templates, and non-Starship
NOTAMs; capture that behavior in property-based tests that must still pass after
the fix.

**Test Cases**:
1. **Land-adjacent fit preservation**: Observe the fitted extent for a
   land-adjacent polygon on unfixed code (after neutralizing scale it equals the
   padded fit), then assert the fix keeps it fitted with existing padding.
2. **Radius circle preservation**: Assert a point-with-radius still produces the
   radius-fitted extent and circle.
3. **No-coordinate fallback preservation**: Assert `coords=None` still yields the
   default global extent `[-180, 180, -90, 90]`.
4. **Recognized template preservation**: For each existing template (ascent,
   reentry, splashdown, debris-plural, ground hazard, high-energy testing,
   Pacific re-entry), assert the fixed `extract_starship_template` returns the
   same line as today.
5. **Non-Starship preservation**: Assert text with no Starship flight number
   still returns `None` from `extract_starship_template` and the card derives
   details from E/D.

### Unit Tests

- Extent computation for the ocean polyline: assert bounded span after fix.
- `MAP_EXTENT_SCALE` effect: assert the fitted extent is dominated by the NOTAM.
- `extract_starship_template` for the FLT-14 debris wording: assert the debris
  summary line.
- `extract_starship_template` generic fallback: a recognized flight with unknown
  wording returns a concise non-empty line.
- Edge cases: empty/None text returns `None`; no-coordinate map falls back to
  global extent.

### Property-Based Tests

- Generate random small polygons and points at varied latitudes and assert the
  rendered extent stays a bounded multiple of the fitted span (fit correctness).
- Generate random land-adjacent and radius inputs and assert extents match the
  pre-scale fitted extent (preservation).
- Generate random non-Starship strings and assert `extract_starship_template`
  returns `None` (preservation), and random Starship-flight strings and assert a
  non-empty concise line (fix + fallback).

### Integration Tests

- Full `render_notam_image` for the A1237/26 NOTAM: assert the produced card has
  a concise details line (no coordinate list) and a map fitted to the polyline.
- Context/preservation flow: render a recognized-template Starship NOTAM and a
  non-Starship NOTAM and assert the card text is unchanged from today.
- Visual/feature check: assert the map still renders cartographic features and
  the Starbase marker when in view.
