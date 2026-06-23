# Architecture Design: Source Discovery Tester Pattern — Part 8

## Purpose

This file explains the architecture behind Part 8 `unified_job_source_tester.py` and records the source-access design for `job_search_8` companies (ranks 71–80).

The tester is not the final job-search pipeline. It is the **source-discovery and source-health layer**.

Its purpose is:

```text
For each company, find the most reliable official job source, prove that it returns usable jobs, extract basic fields, and record the exact access method that should be reused later.
```

Part 8 repeats the Part 1 pattern documented in `part1/ARCHITECTURE_source_discovery_tester_pattern.md`. Read that file for the full generic decision tree, status design, and future-pipeline mapping. This document scopes those rules to ranks 71–80.

---

## Core Idea

Part 8 is a mixed ATS batch dominated by Workday CXS, with four additional backend families:

```text
5 companies -> Workday CXS
1 company  -> Greenhouse API
1 company  -> Ashby API
1 company  -> Workable markdown
1 company  -> Oracle Candidate Experience API
1 company  -> MediaTek Next.js detail pages
1 company  -> SmartRecruiters API
```

Architecture flow:

```text
company_search_guide_part_08.md
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

## Source Types Used in Part 8

| Source Type | Companies | Count |
|---|---|---|
| Workday CXS | Cognex, Axis Communications, Arlo, Ambarella | 4 |
| Greenhouse API | Ubiquiti | 1 |
| Ashby API | Netgear | 1 |
| Workable markdown | TP-Link | 1 |
| Oracle CE API | ON Semiconductor | 1 |
| Next.js detail crawl | MediaTek | 1 |
| SmartRecruiters API | Renesas | 1 |

All Part 8 adapters use method `requests` (stdlib `urllib`).

---

## Reusable Helpers

### `test_workday(company, endpoint, public_base)`

```text
Step 1: POST facet discovery
  {"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""}
  -> discover US country/location facet IDs

Step 2: POST paginated search
  {"appliedFacets": {<facet>: [<us ids>]}, "limit": 20, "offset": N, "searchText": "", "sortBy": "postedOn"}

Parser: jobPostings[].title, jobPostings[].externalPath
URL: public_base + externalPath
```

Used by: Cognex, Axis Communications, Arlo, Ambarella.

### `test_greenhouse(company, board)`

```text
GET https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true
Sort: updated_at descending
US filter: location.name + offices[].name
URL: absolute_url
```

Used by: Ubiquiti (`ubiquiti`).

### `test_ashby(company, board)`

```text
GET https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true
Sort: publishedAt descending
US filter: location + address.postalAddress + secondaryLocations
URL: jobUrl
```

Used by: Netgear (`netgear`).

### `test_workable(company, board_slug)`

```text
GET https://apply.workable.com/{board_slug}/jobs.md?location[0][country]=United States
Parse markdown table rows:
  Title | Department | Location | Type | Salary | Posted | Details
Build URL: https://apply.workable.com/{board_slug}/j/{shortcode}/
Sort: Posted descending
US filter: Location column
```

Used by: TP-Link (`tp-link-usa-corp`).

Important: bare `jobs.md` without filters returns only board metadata. Always pass a US country filter for health checks.

### `test_oracle(company, host, site, public_base)`

```text
GET /hcmRestApi/resources/latest/recruitingCEJobRequisitions
finder=findReqs;siteNumber={site},...;sortBy=POSTING_DATES_DESC
Parser: items[0].requisitionList[].Title, .Id
URL: {public_base}/job/{Id}
US filter: PrimaryLocationCountry, PrimaryLocation
```

Used by: ON Semiconductor (`hctz.fa.us2.oraclecloud.com`, site `CX_1001`).

### `test_mediatek()`

MediaTek's public list page is client-rendered. The tester uses a cookie-warmed detail crawl:

```text
1. Open https://careers.mediatek.com/en/jobs with CookieJar (avoids redirect loop)
2. Seed from official detail ID MUS120260610002
3. For each detail page:
   - parse <title> for job title
   - collect related MUS IDs from page HTML
4. BFS related IDs until JOB_SOURCE_TEST_LIMIT unique titles are collected
5. URL: https://careers.mediatek.com/en/jobs/{id}
```

The real script should still open the same detail URLs for full description, location, category, and publishedDate fields.

### `test_smartrecruiters(company, company_slug, public_company)`

```text
GET https://api.smartrecruiters.com/v1/companies/{company_slug}/postings?limit=20&offset=N
Sort: releasedDate descending
US filter: location.fullLocation, location.country
URL: https://jobs.smartrecruiters.com/{public_company}/{id}
```

Used by: Renesas (`renesaselectronics`, public `RenesasElectronics`).

---

## Part 8 Adapter Summary

### Cognex (rank 71)

```text
Source: Workday CXS
Method: requests
Endpoint: https://cognex.wd1.myworkdayjobs.com/wday/cxs/cognex/External_Career_Site/jobs
Public base: https://cognex.wd1.myworkdayjobs.com/External_Career_Site
Sort: sortBy=postedOn
Date field: postedOn
URL: externalPath
```

### Axis Communications (rank 72)

```text
Source: Workday CXS
Method: requests
Endpoint: https://axis.wd3.myworkdayjobs.com/wday/cxs/axis/External_Career_Site/jobs
Public base: https://axis.wd3.myworkdayjobs.com/External_Career_Site
Caveat: many embedded/Linux roles are in Sweden; US count may be low
```

### Arlo (rank 73)

```text
Source: Workday CXS
Method: requests
Endpoint: https://arlo.wd12.myworkdayjobs.com/wday/cxs/arlo/External_Careers/jobs
Public base: https://arlo.wd12.myworkdayjobs.com/External_Careers
Caveat: CA in locationsText may mean Canada, not California; use detail country fields
```

### Ubiquiti (rank 74)

```text
Source: Greenhouse API
Method: requests
Board: ubiquiti
Endpoint: https://boards-api.greenhouse.io/v1/boards/ubiquiti/jobs?content=true
Date fields: first_published, updated_at
URL: absolute_url -> https://job-boards.greenhouse.io/ubiquiti/jobs/{id}
Caveat: shared updated_at across many rows; use Team metadata for firmware fit
```

### Netgear (rank 75)

```text
Source: Ashby API
Method: requests
Board: netgear
Endpoint: https://api.ashbyhq.com/posting-api/job-board/netgear?includeCompensation=true
Date field: publishedAt
URL: jobUrl
```

### TP-Link (rank 76)

```text
Source: Workable markdown
Method: requests
Board: tp-link-usa-corp
List endpoint: https://apply.workable.com/tp-link-usa-corp/jobs.md?location[0][country]=United States
Detail markdown: https://apply.workable.com/tp-link-usa-corp/jobs/view/{shortcode}.md
URL: https://apply.workable.com/tp-link-usa-corp/j/{shortcode}/
Date field: Posted column in jobs.md
Caveat: sponsorship limitations may appear in detail markdown
```

### Ambarella (rank 77)

```text
Source: Workday CXS
Method: requests
Endpoint: https://ambarella.wd108.myworkdayjobs.com/wday/cxs/ambarella/Ambarella/jobs
Public base: https://ambarella.wd108.myworkdayjobs.com/Ambarella
Caveat: use externalPath exactly as returned; unusual slugs are valid
```

### ON Semiconductor (rank 78)

```text
Source: Oracle Candidate Experience API
Method: requests
Host: https://hctz.fa.us2.oraclecloud.com
Site: CX_1001
Public base: https://hctz.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001
Date field: PostedDate
URL: /job/{Id}
Fallback: browser detail page when REST description fields are empty
```

### MediaTek (rank 79)

```text
Source: Next.js careers detail pages
Method: requests with CookieJar
List page: https://careers.mediatek.com/en/jobs (client-rendered)
Detail URL: https://careers.mediatek.com/en/jobs/{id}
Tester method: detail-page BFS from seed posting
Fields visible on detail: title, related job IDs; full description/location in page body
Caveat: public tRPC list API returned HTTP 400 without browser session contract
```

### Renesas (rank 80)

```text
Source: SmartRecruiters API
Method: requests
Company slug: renesaselectronics
Public company: RenesasElectronics
Endpoint: https://api.smartrecruiters.com/v1/companies/renesaselectronics/postings
Date field: releasedDate
URL: https://jobs.smartrecruiters.com/RenesasElectronics/{id}
Caveat: mixed Renesas/Altium/Transphorm feed; export-control and no-sponsorship wording in detail
```

---

## Location and Date Field Notes

### Workday CXS

```text
locationsText (search rows)
postedOn
jobPostingInfo.location (detail rows)
```

### Greenhouse

```text
location.name
offices[].name
first_published
updated_at
```

### Ashby

```text
location
address.postalAddress
secondaryLocations
publishedAt
```

### Workable

```text
Location column in jobs.md
Posted column in jobs.md
Full location/workplace in jobs/view/{shortcode}.md
```

### Oracle CE

```text
PrimaryLocation
PrimaryLocationCountry
PostedDate
WorkplaceType
```

### MediaTek

```text
Location/category/publishedDate are on detail pages and in client-loaded payloads
Tester currently proves title + official URL from detail HTML
```

### SmartRecruiters

```text
location.fullLocation
location.country
location.remote
location.hybrid
releasedDate
customField (Employment Type, Country/Region, Brands)
```

---

## Known Caveats (Tester vs Real Script)

| Topic | Tester behavior | Real job_search_8 behavior |
|---|---|---|
| Keyword search | Not performed | Use profile terms from company guide |
| Role relevance | Any parseable job counts as success | Filter by title + detail content |
| Sponsorship | Not checked | Reject per preferences and detail wording |
| Sample titles | May be non-technical | Expected; tester only proves source access |
| Count < 50 | Valid `ok` if count > 0 | Reflects US-filtered or discoverable postings |
| MediaTek list API | Detail crawl instead of unstable public list API | Same detail URLs; add full field extraction |
| Arlo location | Not deeply checked | Use detail country, not locationsText abbreviations |
| Renesas brands | Not filtered | Reject Altium-only or non-Renesas rows in detail |

---

## Future Full Pipeline Mapping

```text
company_search_guide_part_08.md
   |
   v
Part 8 Source Tester (this repo)
   |
   v
Working Adapter (Workday / Greenhouse / Ashby / Workable / Oracle / MediaTek detail / SmartRecruiters)
   |
   v
Raw Jobs
   |
   v
Normalized Jobs
   |
   v
Preference/Profile Filters
   |
   v
Official Detail Verification
   |
   v
Scoring + Concerns
   |
   v
Ledger Deduplication (jobs_found.md)
   |
   v
Output / Append
```

---

## Design Principle

The Part 8 source tester is boring and repeatable.

For each company:

```text
Find the official ATS endpoint from the company guide.
Fetch broad recent/top records when the API supports it.
Prefer US location when visible.
Extract title, ID, URL, and note where date/location live.
Return the same Result object.
Move to the next company.
```

When a list API is not reliably available (MediaTek), use the next official method: detail URL verification with related-job discovery.

---

## Live Verification Summary

Date: 2026-06-22

```text
All 10 companies: status = ok

Cognex              count = 15
Axis Communications count = 23
Arlo                count = 22
Ubiquiti            count = 4
Netgear             count = 6
TP-Link             count = 30
Ambarella           count = 22
ON Semiconductor    count = 29
MediaTek            count = 13
Renesas             count = 20
```

Source-access layer for `job_search_8` is ready.
