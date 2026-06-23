# Architecture Design: Source Discovery Tester Pattern — Part 9

## Purpose

This file explains the architecture behind Part 9 `unified_job_source_tester.py` and records the source-access design for `job_search_9` companies (ranks 81–90).

The tester is not the final job-search pipeline. It is the **source-discovery and source-health layer**.

Its purpose is:

```text
For each company, find the most reliable official job source, prove that it returns usable jobs, extract basic fields, and record the exact access method that should be reused later.
```

Part 9 repeats the Part 1 pattern documented in `part1/ARCHITECTURE_source_discovery_tester_pattern.md`. Read that file for the full generic decision tree, status design, and future-pipeline mapping. This document scopes those rules to ranks 81–90.

---

## Core Idea

Part 9 is a mixed ATS batch with five new adapter families:

```text
1 company  -> Eightfold PCS API
1 company  -> Eightfold HTML embed
1 company  -> SmartRecruiters API
1 company  -> iCIMS HTML
1 company  -> Custom careers HTML (Cloudflare risk)
2 companies -> Workday CXS
1 company  -> ADP Workforce Now API
2 companies -> Greenhouse API
```

Architecture flow:

```text
company_search_guide_part_09.md
  -> official endpoint discovery
  -> broad recent/top fetch (up to 50)
  -> US location prefilter when fields exist
  -> basic parser (title, count, official URL)
  -> unified Result output
```

---

## Unified Result Object

Every company adapter returns:

```python
@dataclass
class Result:
    company: str
    method: str
    status: str
    count: int
    sample_title: str = ""
    sample_url: str = ""
```

---

## Status Design

| Status | Meaning |
|---|---|
| `ok` | Source returned parseable jobs |
| `blocked` | Source returned access denied or HTTP 403 |
| `failed` | Network/request failed |
| `parser_failed` | Page/API loaded but parser found no jobs |
| `http_<code>` | Source returned another HTTP response |

---

## Source Types Used in Part 9

| Source Type | Companies | Count |
|---|---|---|
| Eightfold PCS API | Infineon | 1 |
| Eightfold HTML embed | STMicroelectronics | 1 |
| SmartRecruiters API | Microchip | 1 |
| iCIMS HTML | Lattice Semiconductor | 1 |
| Custom careers HTML | Synaptics | 1 |
| Workday CXS | Teledyne FLIR, iRobot | 2 |
| ADP Workforce Now API | Hanwha Vision | 1 |
| Greenhouse API | Alarm.com, SimpliSafe | 2 |

All Part 9 adapters use method `requests` (stdlib `urllib`).

---

## Reusable Helpers

### `test_eightfold_pcs(company, base, domain)`

```text
GET {base}/api/pcsx/search?domain={domain}&location=United States&start={offset}&num=10
Headers: Referer: {base}/careers
Parser: data.positions[].name, .id, .positionUrl, .publicUrl
URL: absolute(positionUrl|publicUrl, base) or {base}/careers/job/{id}
Paginate: start += 10
```

Used by: Infineon (`jobs.infineon.com`, `infineon.com`).

### `test_stmicro()`

```text
Step 1: Try PCS API at stmicroelectronics.eightfold.ai/api/pcsx/search
Step 2: If empty, GET careers page HTML
Step 3: extract_json_array(body, "positions") after html.unescape
US filter: locations[] or location
Sort: t_update descending
URL: canonicalPositionUrl or {base}/careers/job/{id}
```

Used by: STMicroelectronics.

Important: direct PCS API may return PCSX disabled; HTML embed is the reliable fallback.

### `test_icims_lattice()`

```text
GET https://careers-latticesemi.icims.com/jobs/search?ss=1&in_iframe=1
Regex: iCIMS_JobCardItem anchor + h3 title
URL: strip ?in_iframe=1 from detail link
```

Used by: Lattice Semiconductor.

### `test_synaptics()`

```text
Try US country URL, then engineering URL
Regex: /jobs/{jobId}-{slug} links
Status blocked when Cloudflare returns HTTP 403
```

Used by: Synaptics.

### `test_adp_hanwha()`

```text
GET ADP job-requisitions with cid, client, ccId, $skip, $top, timeStamp
Required headers: Accept-Language, locale, X-Requested-With, x-forwarded-host
Parser: jobRequisitions[].requisitionTitle, .itemID, .requisitionLocations
US filter: requisitionLocations address fields
Sort: postDate descending
```

Used by: Hanwha Vision.

### `test_workday(company, endpoint, public_base)`

Same as Part 7/8:

```text
POST facet discovery -> US facet IDs
POST paginated search with sortBy=postedOn
Parser: jobPostings[].title, .externalPath
URL: public_base + externalPath
```

Used by: Teledyne FLIR, iRobot.

### `test_greenhouse(company, board)`

Same as Part 7/8:

```text
GET boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true
Sort: updated_at descending
US filter: location.name + offices[].name
URL: absolute_url
```

Used by: Alarm.com (`alarmcom`), SimpliSafe (`simplisafe`).

### `test_smartrecruiters(company, company_slug, public_company)`

Same as Part 8:

```text
GET api.smartrecruiters.com/v1/companies/{slug}/postings
Sort: releasedDate descending
US filter: location.fullLocation, location.country
URL: https://jobs.smartrecruiters.com/{public_company}/{id}
```

Used by: Microchip (`Microchip`).

### Shared utilities

```text
extract_json_array(text, key)  -> bracket-match JSON array after "key":
eightfold_job_url(job, base)   -> resolve publicUrl/positionUrl/canonicalPositionUrl
is_us_text(value)              -> US state/country heuristics
unique_by(items, key_func)     -> dedupe up to JOB_SOURCE_TEST_LIMIT
status_from(code, count)       -> ok | blocked | failed | parser_failed | http_*
```

---

## Part 9 Adapter Summary

### Infineon (rank 81)

```text
Source: Eightfold PCS
Method: requests
Base: https://jobs.infineon.com
Domain: infineon.com
Date field: postedTs, creationTs
URL: /careers/job/{id}
Live: ok, count=50
```

### STMicroelectronics (rank 82)

```text
Source: Eightfold HTML embed
Method: requests
Fallback page: stmicroelectronics.eightfold.ai/careers?domain=stmicroelectronics.com&location=United States
Date field: t_update, t_create
URL: canonicalPositionUrl
Live: ok, count=10 (US-filtered first-page embed)
```

### Microchip (rank 83)

```text
Source: SmartRecruiters API
Method: requests
Slug: Microchip
Date field: releasedDate
URL: jobs.smartrecruiters.com/Microchip/{id}
Live: ok, count=5
```

### Lattice Semiconductor (rank 84)

```text
Source: iCIMS HTML
Method: requests
Search: careers-latticesemi.icims.com/jobs/search?ss=1&in_iframe=1
Date field: optional schema.org on detail (not required for tester)
URL: /jobs/{id}/{slug}/job
Live: ok, count=50
```

### Synaptics (rank 85)

```text
Source: Custom careers HTML
Method: requests
Risk: Cloudflare HTTP 403 from CLI
URL: careers.synaptics.com/jobs/{jobId}-{slug}
Live: blocked, count=0
```

### Teledyne FLIR (rank 86)

```text
Source: Workday CXS
Method: requests
Endpoint: flir.wd1.myworkdayjobs.com/wday/cxs/flir/flircareers/jobs
Public base: https://flir.wd1.myworkdayjobs.com/flircareers
Live: ok, count=50
```

### Hanwha Vision (rank 87)

```text
Source: ADP Workforce Now API
Method: requests
CID: 787e0fab-b518-411a-9af8-dd168e00705a
Date field: postDate
URL: itemID-backed ADP requisition URL
Live: ok, count=13
```

### Alarm.com (rank 88)

```text
Source: Greenhouse API
Method: requests
Board: alarmcom
Live: ok, count=50
```

### SimpliSafe (rank 89)

```text
Source: Greenhouse API
Method: requests
Board: simplisafe
Live: ok, count=32
```

### iRobot (rank 90)

```text
Source: Workday CXS
Method: requests
Endpoint: irobot.wd503.myworkdayjobs.com/wday/cxs/irobot/iRobot/jobs
Public base: https://irobot.wd503.myworkdayjobs.com/iRobot
Live: ok, count=7
```

---

## Location and Date Field Notes

| Company | Location fields used by tester | Date fields in source |
|---|---|---|
| Infineon | locations[], standardizedLocations | postedTs, creationTs |
| STMicro | locations[], location | t_update, t_create |
| Microchip | location.fullLocation, location.country | releasedDate |
| Lattice | not filtered (search page is global list) | datePosted on detail optional |
| Synaptics | not reached when blocked | Date Posted on search row |
| Teledyne FLIR | Workday US facet | postedOn |
| Hanwha Vision | requisitionLocations address | postDate |
| Alarm.com | location.name, offices[] | updated_at |
| SimpliSafe | location.name, offices[] | updated_at |
| iRobot | Workday US facet | postedOn |

The tester applies only a broad US location prefilter. The real script should re-check location, work mode, and posting date on detail pages.

---

## Known Caveats (Tester vs Real Script)

```text
STMicro: HTML embed may expose fewer than 50 US rows on first page; real script should paginate careers?start=N if needed.
Lattice: iCIMS search returns global cards; real script should filter on Job Locations from detail.
Synaptics: CLI blocked by Cloudflare; real script needs browser session or manual verification path.
Hanwha ADP: per-job public URLs may be unstable; preserve itemID and clientRequisitionID.
Infineon: PCS pages return 10 rows per request; tester paginates to 50.
Microchip / iRobot: low active US counts are normal, not endpoint failure.
```

---

## Live Verification Summary

Run date: 2026-06-22

```text
9/10 ok
1/10 blocked (Synaptics — Cloudflare)
```

All parseable official sources returned count > 0 with official or source-backed sample URLs.

---

## Future Pipeline Mapping

```text
Tester adapter  ->  Real script module
test_eightfold_pcs   -> Infineon PCS search + position_details
test_stmicro         -> ST HTML/PCS hybrid with pagination
test_smartrecruiters -> Microchip SR list + detail API
test_icims_lattice   -> Lattice iCIMS search + detail schema.org
test_synaptics       -> Browser-backed Synaptics search (blocked in CLI)
test_workday         -> FLIR + iRobot Workday CXS
test_adp_hanwha      -> Hanwha ADP list + detail
test_greenhouse      -> Alarm.com + SimpliSafe GH list + detail
```

The real `job_search_9` script should normalize each adapter output into a shared job object before profile filtering.
