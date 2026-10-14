# New source research

Candidate sources for the bot beyond the ones it already checks. Every
endpoint below was called live on **2026-10-14**; sample values come from those
responses.

Scope: three sources picked from a wider survey. Launch Library 2 was dropped
(not interesting enough), and the Federal Register is already implemented
(`feat/federal-register`).

| Source | What it adds | Access | Effort |
| --- | --- | --- | --- |
| [Regulations.gov](#1-regulationsgov) | FAA/USCG Starship environmental and safety-zone documents, with PDFs and comment periods | JSON API, free key | Small |
| [USCG Broadcast Notices to Mariners](#2-uscg-broadcast-notices-to-mariners) | Maritime hazard areas for every Starship flight, with coordinates and launch windows | RSS, no key | Medium (coordinate parsing, map card) |
| [SEC EDGAR](#3-sec-edgar-spacex-spcx) | SpaceX's filings as a public company (8-K, 10-Q, 10-K) | JSON / Atom, no key | Small |

---

## 1. Regulations.gov

The docket system behind federal rulemaking and environmental reviews. It
overlaps with the Federal Register (each FR notice is also posted here), but it
also carries what the FR does not print: final EAs, FONSIs/RODs, draft
documents, attachments, docket-level status, and comment periods.

### Access

- **API:** `https://api.regulations.gov/v4` (JSON:API format). Docs:
  <https://open.gsa.gov/api/regulationsgov/>
- **Key:** free api.data.gov key, sign-up form on the docs page, passed as
  `api_key=` or the `X-Api-Key` header. `DEMO_KEY` works but allowed only
  **10 requests per hour** in testing (`X-Ratelimit-Limit: 10`), so it is
  unusable for the bot. A registered key gets the api.data.gov default
  (about 1,000/hour), which is far above what the bot needs (1–2 calls per
  cycle).
- **Paging:** `page[size]` up to 250, `page[number]` up to 20 (5,000 records
  per query window).

### Endpoints

| Call | Use |
| --- | --- |
| `GET /documents?filter[searchTerm]=…&filter[agencyId]=FAA,USCG&filter[lastModifiedDate][ge]=…&sort=lastModifiedDate&page[size]=250` | Poll for new or changed documents |
| `GET /documents/{documentId}?include=attachments` | Attachments (PDF URLs and sizes) and full metadata |
| `GET /dockets/{docketId}` | Docket title, abstract, status (`category`, e.g. `Pending`) |
| `GET /comments?filter[docketId]=…` | Comment count (`meta.totalElements`) |

**`filter[lastModifiedDate]` is in Eastern Time**, written as
`YYYY-MM-DD HH:MM:SS` (`2020-08-10 11:58:52` = `2020-08-10T15:58:52Z`). Use
`[ge]` with the last seen value and dedupe by id, as the docs recommend.
`filter[postedDate]` takes a plain date.

### Relevant content (2026-10-14)

`searchTerm=Starship` matches 209 documents. About 40 are FAA/USCG Starship
items; the rest are EPA noise (heavy-duty truck rules etc.), so filter by
agency. Recent Starship documents:

| Posted | Document | Docket | What |
| --- | --- | --- | --- |
| 2026-10-14 | `FAA-2026-12808-0001` (Notice, FR 2026-20963) | `FAA-2026-12808` | NOI for a Programmatic EIS: Starship launch/landing at Starbase and expansion of landing and expenditure locations. **Comments open until 2026-12-01.** |
| 2026-09-29 | `FAA-2026-10792-0001` (Notice, FR 2026-19897) | `FAA-2026-10792` | NOI for a Supplemental EIS and scoping: Starship-Super Heavy operations at SLC-37, Cape Canaveral SFS |
| 2026-09-15 | `USCG-2026-1159-0001` (Rule) | `USCG-2026-1159` | Safety zone: Rocket Test Site, Rio Grande River, Boca Chica, TX |
| 2026-07-14 → 09-04 | `FAA-2026-6968-0002/-0019/-0042` (Notices) | `FAA-2026-6968` | EA: Starship reentry contingency operations in the Pacific Ocean (36 public comments) |
| 2026-02-13 | `FAA-2025-3124-0030` (Other) | `FAA-2025-3124` | Final tiered EA + FONSI/ROD: additional launch trajectories and Starship RTLS at Boca Chica |

Notes:

- `searchTerm=Starship` alone misses `USCG-2026-1159` (the rule says
  "Rocket Test Site"). Search **`SpaceX`**, **`Starship`** and
  **`Boca Chica`** (or `Starbase`), then merge by document id.
- `FAA-2013-0259` is a long-running commercial-space docket with
  thousands of documents. Matching documents still show up through the
  search terms; don't subscribe to the whole docket.
- Documents of type `Other` / `Supporting & Related Material` (such as
  `FAA-2025-3124-0030`, the actual final EA and FONSI) have no FR number and
  are **not** in the Federal Register. They are the main value this source
  adds.

### Response shape

```json
{
  "id": "FAA-2026-12808-0001",
  "attributes": {
    "agencyId": "FAA", "docketId": "FAA-2026-12808",
    "documentType": "Notice", "subtype": "Request for Comments",
    "frDocNum": "2026-20963",
    "title": "Notice of Intent To Prepare a Programmatic Environmental Impact Statement ...",
    "postedDate": "2026-10-14T04:00:00Z",
    "lastModifiedDate": "2026-10-14T16:53:17Z",
    "commentStartDate": "2026-10-14T04:00:00Z",
    "commentEndDate": "2026-12-01T04:59:59Z",
    "openForComment": true, "withdrawn": false
  }
}
```

Attachments (`include=attachments`) come back in `included[]` with
`attributes.title` and `attributes.fileFormats[] = {fileUrl, format, size}`.
For example, `FAA-2025-3124-0030` has 4 PDFs at
`https://downloads.regulations.gov/FAA-2025-3124-0030/attachment_{1..4}.pdf`
(English and Spanish EA and FONSI/ROD). The public page for any document is
`https://www.regulations.gov/document/{id}`.

### Implementation notes

- **Key:** document `id`. Store `lastModifiedDate` and `commentEndDate` too.
- **Dedupe against the Federal Register:** if `frDocNum` matches a
  `document_number` already in the Federal Register table, skip the post (or
  edit the FR post to add the docket link). Both use the same value:
  `FAA-2026-12808-0001` has `frDocNum` `2026-20963`, which is the FR
  `document_number`.
- **Posts:** new document → title, agency, type, docket, attachment links.
  Optional: a reminder when a Starship comment period closes within 7 days
  (`commentEndDate`).
- **Config:** `REGULATIONS_GOV_API_KEY` in `.env`. Skip the source with a log
  line when it is unset.
- **First run:** seed with `lastModifiedDate[ge]` = now − 30 days, or prefill as
  COMPASS does, to avoid posting the whole archive.

---

## 2. USCG Broadcast Notices to Mariners

The maritime counterpart of the FAA NOTAMs. For every Starship flight the
Coast Guard issues BNMs with **hazard-area polygons and launch-day hazard
periods**, then a cancellation that **states the outcome** (e.g. "STARSHIP
FLIGHT 14, SUCCESSFUL LAUNCH."). The existing NOTAM map cards could draw these
areas.

In 2025 the Coast Guard renamed its districts: District 8 → **Heartland
District (CGD-H)**, District 7 → **Southeast District (CGD-SE)**. Older
bulletins use `CCGD8` / `CCGD7`.

### Access: GovDelivery RSS (no key)

NAVCEN lists per-topic RSS feeds at
<https://www.navcen.uscg.gov/subscribe-email-rss-feeds>. Each feed is
`https://public.govdelivery.com/topics/{TOPIC}/feed.rss` and returns the
**last 100 bulletins**. Each `<item>` has `title`, `pubDate`, `guid`, `link`,
and a `description` holding **the full bulletin text as HTML**, so there's no
need to fetch the bulletin page.

| Topic | Feed | Starship relevance |
| --- | --- | --- |
| `USDHSCG_414` | Heartland District BNMs | **Primary.** Texas/Gulf hazard areas for every Starbase flight (Flights 12, 13, 14 found in the current window, back to 2026-03-17) |
| `USDHSCG_422` | Southeast District BNMs | **Primary.** The downrange Gulf / Florida Straits / Caribbean corridor for Starbase flights (Flights 13, 14), and from now on Cape Canaveral launches, so Florida Starship flights will show up here |
| `USDHSCG_427` | Sector Key West BNMs | Older Starship corridor notices (Flights 10, 11 in 2025); now covered by `422` |
| `USDHSCG_421` / `420` | Sector Corpus Christi / Houston/Galveston BNMs | No space items; local navigation only |
| `USDHSCG_424` | Sector Jacksonville BNMs | No space items (Cape notices come under `422`) |
| `USDHSCG_441` | Sector Honolulu BNMs | No Starship items yet; worth adding if Pacific reentry contingency operations (FAA EA `FAA-2026-6968`) start |

Other options checked and rejected:

- The GovDelivery bulletin index (`content.govdelivery.com/accounts/USDHSCG/bulletins`)
  returns 404; only single bulletin pages are public.
- Email subscription plus IMAP works but is unnecessary now that RSS exists.
- NAVCEN's LNM API is "coming soon" according to its FAQ. The weekly LNM
  PDFs cover the same notices with a delay.
- The NGA MSI API (`msi.nga.mil/api/publications/broadcast-warn`, NAVAREA
  IV/XII, HYDROPAC/HYDROLANT) responds only to a browser User-Agent, and its
  newest warning is from 2024. It looks frozen, so don't use it.

### Filtering

Across the 100-item windows: Heartland had 4 `SPACE OPERATIONS` items, all
Starship. Southeast had 71, of which 8 were Starship; the rest are Falcon 9,
Dragon and Starlink from the Cape. So:

1. Title contains `SPACE OPERATIONS`.
2. Description contains `STARSHIP`. For cancellations, keep them if the
   cancelled BNM number is one we stored (cancellations name it:
   `CANCEL CGD-SE BNM 9076-26`). The text also says `STARSHIP FLIGHT 14,
   SUCCESSFUL LAUNCH`, so a plain `STARSHIP` match catches these too.

### Bulletin format

Title: `{SAFETY|CANCELLATION}/{region}/SPACE OPERATIONS/{CGD-H|CGD-SE} BNM {NNNN-YY}`

Body (Heartland, BNM 0108-26, abridged):

```text
1. SPACE LAUNCH OPERATIONS, WHICH MAY BE HAZARDOUS TO SURFACE VESSELS, WILL BE
CONDUCTED WITHIN PORTIONS OF THE FOLLOWING HAZARD AREAS FOR STARSHIP FLIGHT 14:
A. HIGH RISK HAZARD AREA
25-12-00N 092-58-00W, 25-31-00N 093-52-00W, ... AND 24-45-00N 092-43-00W.
B. HAZARD AREA
25-58-00N 097-13-00W, 26-02-00N 097-13-00W, ...
2. PRIMARY AND BACKUP LAUNCH DAY HAZARD PERIODS INCLUDE:
13/2315Z OCT 25 TO 14/0122Z OCT 25
...
3. NAVIGATION HAZARDS WITHIN THE HAZARD AREAS MAY INCLUDE FREE FALLING DEBRIS ...
CANCEL AT//200222Z OCT 25//
```

Southeast uses a different vertex syntax:
`A. FROM 25-58-00N/097-13-00W TO 26-02-00N/097-13-00W TO ... TO BEGINNING`
(one combined area, closed by `TO BEGINNING`), with windows under
`2. HAZARD PERIODS FOR PRIMARY LAUNCH DAY AND BACKUP LAUNCH DAYS`.

Cancellation:
`1. CANCEL CGD-SE BNM 9076-26 DTG 271742Z SEP 26 2. STARSHIP FLIGHT 14, SUCCESSFUL LAUNCH. BT`

Fields to extract:

| Field | Pattern |
| --- | --- |
| BNM id | `(CGD-H|CGD-SE|CCGD\d+|CCGD-SE) BNM (\d{4}-\d{2})` in the title |
| Kind | title prefix `SAFETY` / `CANCELLATION` |
| Flight | `STARSHIP FLIGHT (\d+)` |
| Areas | blocks `A.`, `B.` … with their label (`HIGH RISK HAZARD AREA`, `HAZARD AREA`) |
| Vertices | `(\d{2})-(\d{2})-(\d{2}(?:\.\d+)?)([NS])[ /](\d{3})-(\d{2})-(\d{2}(?:\.\d+)?)([EW])`; seconds can be non-zero (`25-11-42N 092-57-51W`) |
| Windows | `(\d{2})/(\d{4})Z? (\w{3}) (\d{2}) TO (\d{2})/(\d{4})Z? (\w{3}) (\d{2})`: Heartland writes `13/2315Z OCT 25`, Southeast `28/1215 SEP 26` (no `Z`, still UTC) |
| Expiry | `CANCEL AT//(\d{6})Z (\w{3}) (\d{2})//`; some Southeast notices omit it, so fall back to the end of the last window |
| Outcome (cancellations) | text after the `CANCEL … DTG …` line, e.g. `SUCCESSFUL LAUNCH` |

### Implementation notes

- **Coordinates:** `parsers/coord_parser.py` reads compact DMS tokens
  (`255400N`) but not the dashed BNM style. Normalise
  `25-54-00N` → `255400N` (strip the dashes in each token) and reuse
  `parse_coord_groups_from_text`, one group per lettered area, so the map
  shows high-risk and hazard areas as separate polygons.
- **Key:** BNM id (`CGD-H BNM 0108-26`) plus kind. Re-issued notices
  (new launch date) get a new BNM number, so treat each as new and link it to
  the flight.
- **Posts:** map card (same renderer as NOTAMs) + flight number + windows
  in UTC. Cancellation → short follow-up replying to the original post, with
  the outcome line.
- **Fetching:** plain `requests` (no Selenium). Fetch `414` and `422` every
  cycle; the feeds are small (100 items) and need no key.

---

## 3. SEC EDGAR (SpaceX, SPCX)

SpaceX is a public company now: **Space Exploration Technologies Corp**,
Nasdaq **SPCX**, **CIK 0001181412**, incorporated in Texas, HQ Starbase TX,
fiscal year ending 31 December, non-accelerated filer. S-1 filed 2026-05-20,
IPO priced (424B4) 2026-06-12.

### Access

- **No key.** SEC requires a descriptive `User-Agent` with a contact
  (e.g. `starship_notam bot admin@example.org`); requests without one are
  blocked. The fair-access limit is **10 requests/second**.
- **Submissions (primary):** `https://data.sec.gov/submissions/CIK0001181412.json`.
  It holds `filings.recent` as parallel arrays: `accessionNumber`,
  `filingDate`, `acceptanceDateTime`, `form`, `items` (8-K item codes),
  `primaryDocument`, `primaryDocDescription`, `reportDate`. 85 filings
  as of today.
- **Atom alternative:**
  `https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0001181412&type=8-K&owner=include&count=40&output=atom`
  (works; `type=` filters by form).
- **Document URL:**
  `https://www.sec.gov/Archives/edgar/data/1181412/{accession without dashes}/{primaryDocument}`;
  index page: `…/{accession}-index.htm`.
- **Full-text search:**
  `https://efts.sec.gov/LATEST/search-index?q="Starship"&ciks=0001181412`.
  20 SpaceX filings mention Starship (S-1 and amendments, 424B4, FWPs, the
  10-Q, one 8-K, SEC correspondence).
- **XBRL:** `https://data.sec.gov/api/xbrl/companyfacts/CIK0001181412.json`
  has only standard `us-gaap` concepts (174) and **nothing
  Starship-specific**.

### What SpaceX files (since IPO)

| Date | Form | 8-K items | What |
| --- | --- | --- | --- |
| 2026-08-14 | 8-K | 2.01, 3.02, 9.01 | Completed the acquisition of Anysphere (Cursor) |
| 2026-08-04 | 10-Q | — | Q2 2026 quarterly report |
| 2026-08-04 | 8-K | 2.02, 9.01 | Q2 results release |
| 2026-06-26 | 8-K | 8.01, 9.01 | Senior notes closing (per file name) |
| 2026-06-23 | 8-K | 8.01, 9.01 | Senior notes pricing (per file name) |
| 2026-06-22 | 8-K | 7.01, 8.01, 9.01 | Senior notes offering launch; Reg FD update on cash |
| 2026-06-17 | 8-K | 5.02 | Board elected Roelof Botha as an independent director |
| 2026-06-16 | 8-K | 1.01, 3.02, 9.01 | Cursor merger agreement |
| 2026-06-15 | 8-K | 3.02, 3.03, 5.02, 5.03, 7.01, 8.01, 9.01 | IPO closing: preferred stock conversion, restated charter and bylaws |

Also: Form 3/4/4A/144 (insider holdings and sales), SCHEDULE 13G (5%+
holders), S-8 (employee share plans).

**Starship in the filings.** The 10-Q has a "Starship launches" key-metrics
table (Q2 2026: 1, Q2 2025: 1; H1 2026: 1, H1 2025: 3, next to Falcon
launches 37/45/77/81). It states that all Starship launches so far are
"internal", and says Space-segment R&D "mainly relate[s] to the development,
build, and testing of Starship". Starship numbers are only in the text, not
in XBRL.

### What to post

| Filing | Post? | Why |
| --- | --- | --- |
| 8-K | **Yes**, with the item codes as labels | Material events. Watch items 1.01 (agreements), 2.02 (results), 5.02 (officers), 7.01/8.01 (other events: anomalies or mishaps would usually land here) |
| 10-Q / 10-K | **Yes** | Quarterly Starship launch count and R&D. Q3 2026 10-Q is due by **2026-11-16** (45 days, non-accelerated filer); FY2026 10-K by about 2027-03-31 |
| S-1, S-3, 424B* | Yes, rare | New share or debt offerings |
| Forms 3/4/144, 13G, S-8, D, CORRESP, UPLOAD | No | Volume without Starship relevance |

Optional: run the full-text search for "Starship" on each new 8-K/10-Q and
add a "mentions Starship" tag, or quote the matching sentence.

### Implementation notes

- **Key:** `accessionNumber`.
- **Poll** the submissions JSON once per cycle (one request), filter `form`
  to the allow-list above, and post items not yet in the table.
- **Item labels:** map 8-K codes to names (2.02 "Results of Operations",
  5.02 "Departure/Election of Directors or Officers", 7.01 "Reg FD
  Disclosure", 8.01 "Other Events", …).
- **Config:** `SEC_USER_AGENT` in `.env` (required by SEC; the source is
  disabled when unset).
- **First run:** prefill existing filings as posted, as COMPASS does.
