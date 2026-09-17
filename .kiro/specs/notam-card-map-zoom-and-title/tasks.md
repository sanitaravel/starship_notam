# Implementation Plan

- [ ] 1. Write bug condition exploration tests
  - **Property 1: Bug Condition** - Ocean NOTAM over-zooms and Starship title not summarized
  - **CRITICAL**: These tests MUST FAIL on unfixed code - failure confirms the bugs exist
  - **DO NOT attempt to fix the tests or the code when they fail**
  - **NOTE**: These tests encode the expected behavior - they will validate the fix when they pass after implementation
  - **GOAL**: Surface counterexamples that demonstrate the two bugs exist
  - **Scoped PBT Approach**: For these deterministic bugs, scope the properties to the concrete failing cases (the A1237/26 Tahiti-FIR polyline and the observed FLT-14 debris wording) to ensure reproducibility
  - Map bug (1a): compute the rendered extent for the Tahiti-FIR polyline (~19–24°S, 148–150°W) and assert the rendered half-span is bounded to a small multiple of the fitted geometry span. On unfixed code the extent balloons near-global via `_expand_extent_until_land` (up to `MAX_EXTENT_HALF_SPAN = 90°`) and is doubled by `MAP_EXTENT_SCALE = 2` (from Bug Condition `isBugCondition` in design)
  - Map bug (scale): for a small land-adjacent polygon, document that the extent half-span equals the fitted half-span times `MAP_EXTENT_SCALE` (2×) on unfixed code
  - Title bug (1b): call `extract_starship_template` with "TEMPORARY DANGER AREA DUE TO SPACE DEBRIS RETURN OF SPACEX STARSHIP FLT-14 IN TAHITI FIR WITHIN AN AREA BOUNDED BY FOLLOWING POINTS: 1951S 14900W, 1923S 14849W, 2458S ..." and assert it returns a concise non-empty line (from `isBugCondition` in design: flight number recognized but classification returns `None`)
  - The test assertions should match the Expected Behavior / Correctness Property 1 from design
  - Run tests on UNFIXED code
  - **EXPECTED OUTCOME**: Tests FAIL (this is correct - map extent is near-global, `extract_starship_template` returns `None`)
  - Document counterexamples found (e.g., "rendered half-span ≫ fitted span for Tahiti polyline"; "`extract_starship_template(FLT-14 debris text)` returns None instead of a summary")
  - Mark task complete when tests are written, run, and failures are documented
  - _Requirements: 1.1, 1.2, 1.3, 1.4_

- [ ] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - Land-adjacent fit, radius circles, no-coord fallback, recognized templates, and non-Starship text unchanged
  - **IMPORTANT**: Follow observation-first methodology
  - Observe on UNFIXED code and capture as property-based tests:
    - Land-adjacent polygon: record the fitted extent (padding + cos(lat) aspect-ratio correction) that the renderer produces today
    - Point-with-radius: record the radius-fitted extent and circle geometry
    - No parseable coordinates (`coords=None`): record the default global extent `[-180, 180, -90, 90]`
    - Each existing summarization template (ascent, reentry, splashdown, debris-plural, ground hazard, high-energy testing, Pacific re-entry): record the exact summary line `extract_starship_template` returns today
    - Non-Starship text (no Starship flight number): record that `extract_starship_template` returns `None` and card details derive from E/D fields
  - Write property-based tests generating varied polygon spans, latitudes, radii, and NOTAM wordings, asserting the observed behavior patterns from the Preservation Requirements in design
  - Property-based testing generates many test cases for stronger guarantees that non-buggy behavior is unchanged
  - Run tests on UNFIXED code
  - **EXPECTED OUTCOME**: Tests PASS (this confirms baseline behavior to preserve)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

- [ ] 3. Fix map over-zoom (Bug 1) and unsummarized Starship title (Bug 2)

  - [ ] 3.1 Fix Bug 1 — keep ocean NOTAMs fitted in `map_renderer.py`
    - Neutralize/relax `MAP_EXTENT_SCALE` so it no longer doubles the geometry footprint (set to `1.0`, or a small padding value like `1.1`); preserve existing `lat_pad`/`lon_pad` and cos(lat) aspect-ratio correction applied before scaling; applies to both the polygon and point branches that share the constant
    - Constrain the land-visibility expansion: bound `_expand_extent_until_land` so the extent never grows beyond a small multiple of the fitted geometry span (rather than the absolute `MAX_EXTENT_HALF_SPAN = 90°`); when no land is found within that bounded window, return the fitted extent unchanged so open-ocean NOTAMs stay fitted
    - Keep the ocean fallback graceful: retain the default global extent path for the no-coordinate case and the land-visibility helper's exception handling that returns the original extent
    - Do not alter cartography (ocean/land fill, coastlines, country/feature labels, graticule, Starbase marker)
    - _Bug_Condition: isBugCondition(input) — coords non-empty, fitted extent has no visible land, rendered span ≫ fitted span (from design)_
    - _Expected_Behavior: Property 1a — map stays fitted to NOTAM geometry with padding so it dominates the frame (from design)_
    - _Preservation: Land-adjacent fit, radius circle, no-coordinate global fallback, cartography (from design)_
    - _Requirements: 2.1, 2.2_

  - [ ] 3.2 Fix Bug 2 — summarize unrecognized Starship titles in `image_composer.py`
    - Extend the debris/launch-hazard classification keywords in `extract_starship_template` to include the singular `"TEMPORARY DANGER AREA"`, plus `"SPACE DEBRIS"` and `"DEBRIS RETURN"` (and close variants) so the observed FLT-14 text resolves to the existing debris summary line (`ВОЗМОЖНОЕ ПАДЕНИЕ ОБЛОМКОВ В РЕЗУЛЬТАТЕ ЗАПУСКА SPACEX STARSHIP FLT-{flight}`)
    - Add a safe generic fallback: after all specific classification branches, when a Starship flight number was successfully extracted but no branch matched, return a concise generic flight-referencing summary line instead of `None`; the fallback must apply only when a flight number was found, so non-Starship text still returns `None`
    - Preserve ordering and existing branches: keywords are additive and the generic fallback is reached only after all specific branches fail
    - No caller changes required: `_notam_from_db_row` already uses a non-empty template result as `details`
    - _Bug_Condition: isBugCondition(text) — containsStarshipFlightNumber(text) AND extract_starship_template(text) IS None (from design)_
    - _Expected_Behavior: Property 1b — return a concise, non-empty summary line (no coordinate list) instead of None (from design)_
    - _Preservation: Existing template lines unchanged; non-Starship text still returns None (from design)_
    - _Requirements: 2.3, 2.4_

  - [ ] 3.3 Verify bug condition exploration tests now pass
    - **Property 1: Expected Behavior** - Ocean NOTAM stays fitted and Starship title is summarized
    - **IMPORTANT**: Re-run the SAME tests from task 1 - do NOT write new tests
    - The tests from task 1 encode the expected behavior; when they pass, they confirm the expected behavior is satisfied
    - Run the bug condition exploration tests from step 1
    - **EXPECTED OUTCOME**: Tests PASS (map extent bounded to a small multiple of the fitted span; `extract_starship_template` returns a concise non-empty line for the FLT-14 debris wording)
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [ ] 3.4 Verify preservation tests still pass
    - **Property 2: Preservation** - Non-buggy inputs unchanged
    - **IMPORTANT**: Re-run the SAME tests from task 2 - do NOT write new tests
    - Run the preservation property tests from step 2
    - **EXPECTED OUTCOME**: Tests PASS (land-adjacent fit, radius circles, no-coordinate global fallback, recognized templates, and non-Starship None all unchanged; cartography intact)
    - Confirm all tests still pass after fix (no regressions)
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

- [ ] 4. Checkpoint - Ensure all tests pass
  - Run the full test suite (exploration, preservation, unit, property-based, and integration tests from the design's Testing Strategy)
  - Integration: full `render_notam_image` for A1237/26 yields a concise details line (no coordinate list) and a map fitted to the polyline; recognized-template and non-Starship cards unchanged; cartography and Starbase marker still render
  - Ensure all tests pass, ask the user if questions arise
