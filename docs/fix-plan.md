# Fix plan

Findings from the October 2026 codebase review, ordered by when to do them.
Each step is one small change with its own test, done on a branch. Run the
full test suite (`pytest`) after every step.

Status legend: `[ ]` to do, `[x]` done, `[?]` needs a decision first.

---

## Phase 1 — Wrong maps and wrong posts (do first)

These produce incorrect images or irrelevant posts in production today.
Steps 1 and 2 touch the same map code path, so do them in order. Steps 3 and
4 are independent.

### 1. Multi-area NOTAMs are drawn as one fused polygon `[ ]`

- **Where:** `bot/orchestrator.py:160`, `visualization/image_composer.py:717`
- **Problem:** the orchestrator passes a flat point list from
  `parse_coords_from_text` into `plot_single_notam`, which then overwrites the
  per-area groups that `_notam_from_db_row` computed with
  `parse_coord_groups_from_text`. Verified: the two-area DRA example parses to
  2 groups, but the orchestrator passes 8 points as one ring.
- **Fix:** remove the `coords` parameter from `plot_single_notam`; let
  `_notam_from_db_row` own coordinate extraction. The orchestrator only uses
  `parse_coords_from_text` as a "has any coordinates?" check. While here, drop
  the `.json` suffix that the orchestrator adds and both `_notam_from_db_row`
  and `build_notam_caption` strip again.
- **Test:** call `plot_single_notam` (with `render_map` mocked) on the
  two-area E-field and assert `render_map` receives a list of 2 groups.

### 2. Polygons crossing the 180° meridian are drawn around the whole globe `[ ]`

- **Affected:** `09/338`, `09/339`, `09/342`, `09/343` (Starship FLT 14
  ascent/reentry area, ZAK/ZHN). Same 21-vertex polygon in all four.
- **Where:** `visualization/map_renderer.py` (`render_map`,
  `_normalize_polygon_order`), and the PIL fallback in
  `visualization/image_composer.py`
- **Problem:** the polygon runs 165°E → 179°59'E → 175°W → … → 145°W → back to
  170°E. All longitudes are kept in [-180, 180], so:
  1. the bounding box spans ~357° of longitude, so the map zooms out to the
     whole world;
  2. the edges that cross 180° are drawn the long way round, producing a thin
     red band across the whole map instead of the real area in the Pacific;
  3. those wrap-around edges look like self-intersections, so
     `_normalize_polygon_order` reorders the vertices by centroid angle and
     scrambles a polygon that was valid as listed.

  Reproduced: rendering `09/338` today gives the world map with a band at
  ~25–30°N; log shows "Geometry spans 356.6 deg" and "reordered by centroid
  angle".
- **Fix:** add `_unwrap_longitudes(points)`: when consecutive vertices jump by
  more than 180°, shift the following longitudes by ±360 so the ring is
  continuous (here: 165…215°). Apply it to each polygon group before the
  self-intersection check, extent fitting and drawing. When the unwrapped
  extent leaves [-180, 180], create the axes with
  `ccrs.PlateCarree(central_longitude=<extent centre>)` and keep passing data
  in `ccrs.PlateCarree()`, so Cartopy places it correctly. Apply the same
  unwrapping in the PIL fallback.
- **Test:** for the `09/338` polygon assert that after unwrapping the
  longitude span is < 60°, `_polygon_self_intersects` is False, and the
  vertex order is unchanged. A `render_map` smoke test asserting the extent's
  longitude span is < 90°.
- **Already posted:** the four NOTAMs were posted with the wrong map.
  Decision (2026-10-02): do not re-post them after the fix.

### 3. Short coordinates parsed wrong in CARF messages `[ ]`

- **Where:** `parsers/notam_parser.py` (`_dms_to_decimal`, `_parse_coord_pair`)
- **Problem:** `1700N07140W` becomes `lat=0.28, lon=-1.19`; it should be
  `17.0, -71.67`. The correct converter already exists in
  `parsers/coord_parser._dms_token_to_decimal`.
- **Fix:** delete `_dms_to_decimal`; make `_parse_coord_pair` use
  `_dms_token_to_decimal` for each half. Hoist the coordinate regex (currently
  defined 4 times in this module) to a module constant.
- **Test:** `parse_carf_message` with a `DDMM`/`DDDMM` polygon and a
  `DDMMSS`/`DDDMMSS` polygon; assert decimal values.

### 4. Irrelevant NOTAMs saved and posted (`A6286/26`) `[ ]`

- **Why `A6286/26` was saved:** it is a French VFR notice ("VFR ENTRY WI LA
  ROCHELLE CTR AND TMA…", location LFBH). The log for 2026-09-28 09:02 shows
  it was returned by the `re-entry` free-text search (row 6 of 6). The FAA
  free-text search does not match the phrase `re-entry` exactly; it matched
  "VFR ENTRY". `_persist_notam_results` saves every row the search returns
  with no relevance check, and `_process_notam_images` then rendered and
  posted it because it had a Q-line point.
- **Same cause, also in the DB:** `A6203/26`, `A6228/26`, `A6289/26` (all La
  Rochelle VFR entry). These are the only 4 of 102 saved NOTAMs without any
  space-related wording.
- **Fix:** in `bot/orchestrator.py` (`_refresh_notams_from_source`), filter
  each result before saving: keep it only if its ICAO message matches the
  searched keyword as a whole phrase (e.g. `\bRE-?ENTRY\b` for `re-entry`,
  `\bSTARSHIP\b`, `\bSPACE\s?X\b.*\bBROWNSVILLE\b`). Keep the keyword → regex
  table next to the keyword list so they stay in sync. Log skipped rows.
- **Test:** `_persist_notam_results`-level test: the `A6286/26` text with
  keyword `re-entry` is not saved; a real re-entry NOTAM is.
- `[x]` **Cleanup:** the 4 La Rochelle rows were deleted from `notams.db` on
  2026-10-02. Their Telegram posts must be removed from the channel by hand.
  Until this step ships, the `re-entry` search can save and post them again
  as new NOTAMs if the FAA still returns them.

---

## Phase 2 — Posting reliability

### 5. `send_message` retries forever on timeout `[ ]`

- **Where:** `bot/transport.py:85`
- **Fix:** cap at 3 attempts with backoff (e.g. 2s, 5s, 10s); honour
  `telegram.error.RetryAfter`. Apply the same to `send_photo`, which currently
  has no timeout retry at all.
- **Test:** mock bot raising `TimedOut` repeatedly; assert it returns `None`
  after the cap and sleeps between attempts.

### 6. One posting loop, consistent "mark as posted" `[ ]`

- **Where:** `bot/orchestrator.py` (5 copies of the send/collect/mark loop)
- **Problem:** FAA activities, beach and road alerts are marked posted even
  when every send failed; FCC and license posts correctly wait for a success.
- **Fix:** add `_post_pending(items, format_fn, mark_fn, key_fn, label)` that
  marks posted only when at least one send returned a message id. Replace all
  5 loops with it (~200 lines removed). Depends on step 5.
- **Test:** for each item type, a failed send leaves the item unposted; a
  successful send marks it with the joined message ids.

### 7. Caption trimming can break HTML `[ ]`

- **Where:** `bot/formatting.py:404` (`build_notam_caption`)
- **Problem:** slicing at a fixed length can cut through `&amp;` or a tag, and
  Telegram rejects the caption.
- **Fix:** trim the *unescaped* E-text to fit the budget, then escape it and
  wrap it in the blockquote, instead of slicing the finished HTML.
- **Test:** a very long E-field full of `&` and `<` produces a caption of at
  most 1024 chars with no partial entity and a closed blockquote.

### 8. One bad Starbase date breaks the whole page parse `[ ]`

- **Where:** `parsers/starbase_parser.py` (`parse_rich_notification`)
- **Fix:** catch `ValueError` around `parse_datetime_range`, same as
  `parse_notice_container` does; keep the event with `raw_date` only.
- **Test:** a rich notification with one valid and one malformed date returns
  both events, the malformed one without `start_utc`/`end_utc`.

### 9. Changed beach/road alerts are not re-posted — keep as is `[x]`

- **Where:** `data/starbase_repo.py` (`save_beach_alert`, `save_road_alert`)
- **Behaviour:** unlike every other table, an update does not reset
  `processed = 0`.
- **Decision (2026-10-02):** intended. An updated closure is not posted
  again. Add a one-line comment in both functions saying so, so it is not
  "fixed" later.

---

## Phase 3 — Performance quick wins

### 10. Stop running `init_db()` on every DB call `[ ]`

- **Where:** every `save_*`, `mark_image_generated`,
  `get_notams_needing_images` in `data/`
- **Fix:** remove those calls; `ensure_setup()` already initialises the schema
  at startup. Remove the now-pointless "does the DB file exist" check in
  `get_notams_needing_images`. Tests that use a fresh temp DB must call
  `init_db` in their fixture.

### 11. Fewer Selenium sessions per cycle `[ ]`

- **Where:** `scrapers/notam_scraper.py`, `bot/orchestrator.py:129`
- **Fix:** remove the unconditional `time.sleep(5)` before `driver.quit()`.
  Let `search_notams` accept a list of keywords and reuse one driver for all
  three. Shorten the per-XPath fallback waits (currently 5s each attempt).

### 12. Cache map data and fonts; stop per-render downloads `[ ]`

- **Where:** `visualization/map_renderer.py`, `visualization/image_composer.py`
- **Fix:** cache the country, water and geographic-name shapefile records in
  memory (like `_get_land_geometries`); `@lru_cache` on `load_font` and on
  font-property creation. Load water layers at one resolution only, which
  also fixes likely duplicate lake/ocean labels.
- **Also:** every render tries to download three `geographic_names` layers
  that do not exist on Natural Earth (seen as `DownloadWarning` for
  `ne_10m_geographic_names.zip` and two mangled variants). Remember the
  failure (or remove that labeller) so it is not retried on each image.
- **Optional:** shapely `STRtree` for the land-visibility check.

### 13. Don't block the event loop `[ ]`

- **Where:** `bot/orchestrator.py`
- **Fix:** wrap `fetch_faa_advisory` and `fetch_starbase_status` in
  `asyncio.to_thread`, like the other scrapers.

---

## Phase 4 — Refactors (no behaviour change)

Do these after phases 1–3 so the bug fixes stay small and easy to review.
Existing tests must pass unchanged.

| # | Area | Change |
| --- | --- | --- |
| 14 | `data/*_repo.py` | One `_upsert(table, key_col, fields, reset_col)` helper and a commit/rollback/close context manager (~300 lines) |
| 15 | `data/connection.py` | `_ensure_columns(cur, table, spec)`; single `executescript`; drop the legacy `parsed_json` migration once confirmed no old DBs remain (~150 lines) |
| 16 | `data/notam_repo.py` | One `_row_to_parsed()` and one `Q_COLS` mapping; remove the unreachable "no effective changes" branch in `save_notam` (~80 lines) |
| 17 | `visualization/map_renderer.py` | Split `render_map` into `_fit_extent`, `_add_base_layers`, `_draw_graticule`, `_label_layer`, `_draw_geometry`; treat a single polygon as a list of one (~250 lines) |
| 18 | `scrapers/notam_scraper.py` | `_click_first(driver, xpaths, timeout)` helper; one ICAO XPath constant (~120 lines) |
| 19 | `scrapers/fcc_els_fetcher.py` | `_fill(field, value)` helper; `calendar.monthrange`; drop unused `import time` (~40 lines) |
| 20 | `bot/formatting.py` | `_coerce_json(value, default)` and `_fmt_utc(iso)` helpers (~40 lines) |
| 21 | parsers / visualization / bot | One shared NOTAM time parser replacing the 4 existing ones (~60 lines) |
| 22 | various | Delete dead code: unused `coord_index` and overwritten `alt_token` branch in `parse_carf_message`, step 3 of `_parse_coords`, `MAP_EXTENT_SCALE` try/except, duplicated growth step in `_expand_extent_until_land`, double check in `_restart_argv` (~80 lines) |

---

## Phase 5 — Housekeeping

- `[?]` Remove the legacy flat-module re-export layer in
  `starship_notam/__init__.py` once nothing outside the package needs it
  (and its test, `tests/integration/test_backward_compat.py`).
- `[ ]` Check the `lock` extras in `pyproject.toml` for unused packages
  (`bs4`, `dotenv`, `xdk`, `pydantic`).
- `[ ]` `_emit_cross_month` in `parsers/schedule.py` skips the remaining days
  of the first month (e.g. `28-OCT 02` never emits 29–30). Fix using the year
  from `base` and `calendar.monthrange`.
