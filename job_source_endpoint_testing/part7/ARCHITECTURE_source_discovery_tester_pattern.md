# Architecture Design: Source Discovery Tester Pattern — Part 7

## Purpose

This file explains the architecture behind Part 7 `unified_job_source_tester.py` and records the source-access design for `job_search_7` companies (ranks 61–70).

The tester is not the final job-search pipeline. It is the **source-discovery and source-health layer**.

Its purpose is:

```text
For each company, find the most reliable official job source, prove that it returns usable jobs, extract basic fields, and record the exact access method that should be reused later.
```

Part 7 repeats the Part 1 pattern documented in `part1/ARCHITECTURE_source_discovery_tester_pattern.md`. Read that file for the full generic decision tree, status design, and future-pipeline mapping. This document scopes those rules to ranks 61–70.

---

## Core Idea

Part 7 companies are concentrated in autonomy, robotics, and embedded/device software. Their official ATS backends are predictable:

```text
7 companies -> Greenhouse API
2 companies -> Ashby API
2 companies -> Workday CXS
```

No Part 7 company required Playwright, curl_cffi, PCS, Lever, or detail-URL verification during source testing.

Architecture flow:

```text
company_search_guide_part_07.md
  -> official Greenhouse / Ashby / Workday endpoint
  -> broad recent/top fetch (up to 50)
  -> US location prefilter when fields exist
  -> basic parser (title, count, official URL)
  -> unified Result output
```

---

## Design Rule

For every Part 7 company:

```text
1. Start with the official endpoint listed in company_search_guide_part_07.md.
2. Use the public ATS API (Greenhouse, Ashby, or Workday CXS).
3. Fetch broad recent/top records; do not keyword-search in the tester.
4. Prefer US location rows when location text is visible.
5. Extract title, job ID, and canonical public URL.
6. Return one consistent Result object.
7. Use documented fallback only when primary board is empty (May Mobility).
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

Example from live verification:

```text
Nuro             | requests | ok | 50 | Senior/Staff Software Technical Program Manager | https://nuro.ai/careersitem?gh_jid=6114642
Serve Robotics   | requests | ok | 50 | Service Technician                              | https://jobs.ashbyhq.com/serverobotics/...
Motorola / Avigilon | requests | ok | 50 | Senior Staff Firmware Engineer               | https://motorolasolutions.wd5.myworkdayjobs.com/Careers/...
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

```python
def status_from(code, count):
    if count > 0:
        return "ok"
    if code == 403:
        return "blocked"
    if code is None:
        return "failed"
    if code == 200:
        return "parser_failed"
    return f"http_{code}"
```

---

## Source Types Used in Part 7

| Source Type | Companies | Count |
|---|---|---|
| Greenhouse API | Nuro, Kodiak Robotics, Gatik, May Mobility, Avride, Skild AI | 6 |
| Ashby API | Serve Robotics, Gecko Robotics | 2 |
| Workday CXS | Motorola Solutions / Avigilon, Zebra Technologies | 2 |

All Part 7 adapters use method `requests` (stdlib `urllib`).

---

## Reusable Helpers

### `test_greenhouse(company, board)`

```text
GET https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true
Sort: updated_at / created_at / first_published descending
US filter: location.name + offices[].name
URL field: absolute_url
Dedupe key: id or absolute_url
Limit: JOB_SOURCE_TEST_LIMIT (default 50)
```

Used by: Nuro, Kodiak, Gatik, Avride, Skild AI, and internally by May Mobility.

### `test_may_mobility()`

```text
1. parse_greenhouse_board("May Mobility", "maymobility")
2. if count == 0: parse_greenhouse_board("May Mobility", "maymobilityjobs")
```

Primary board `maymobility` is sufficient in live testing. Secondary board is a documented fallback only.

### `test_ashby(company, board)`

```text
GET https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true
Sort: publishedAt descending
US filter: location, address.postalAddress, secondaryLocations
URL field: jobUrl
Dedupe key: id or jobUrl
```

Used by: Serve Robotics (`serverobotics`), Gecko Robotics (`gecko-robotics`).

### `test_workday(company, endpoint, public_base)`

```text
Step 1: POST facet discovery
  {"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""}
  -> discover US country/location facet IDs

Step 2: POST paginated search
  {"appliedFacets": {<facet>: [<us ids>]}, "limit": 20, "offset": N, "searchText": "", "sortBy": "postedOn"}
  -> offsets 0, 20, 40 up to LIMIT

Parser: jobPostings[].title, jobPostings[].externalPath
URL: public_base + externalPath
```

Used by: Motorola Solutions / Avigilon, Zebra Technologies.

---

## Part 7 Adapter Summary

### Nuro (rank 61)

```text
Source: Greenhouse API
Method: requests
Board: nuro
Endpoint: https://boards-api.greenhouse.io/v1/boards/nuro/jobs?content=true
Sort: updated_at descending
Location fields: location.name, offices[].name
Date fields: first_published, updated_at
URL: absolute_url -> https://nuro.ai/careersitem?gh_jid={id}
Fallback: Nuxt careers payload at nuro.ai (not needed; API sufficient)
```

### Kodiak Robotics (rank 62)

```text
Source: Greenhouse API
Method: requests
Board: kodiak
Endpoint: https://boards-api.greenhouse.io/v1/boards/kodiak/jobs?content=true
Sort: updated_at descending
URL: absolute_url -> https://job-boards.greenhouse.io/kodiak/jobs/{id}
Caveat: Defense/export-control wording in detail text for real script
```

### Gatik (rank 63)

```text
Source: Greenhouse API
Method: requests
Board: gatikaiinc
Endpoint: https://boards-api.greenhouse.io/v1/boards/gatikaiinc/jobs?content=true
Sort: updated_at descending
URL: absolute_url -> https://boards.greenhouse.io/gatikaiinc/jobs/{id}?gh_jid={id}
Caveat: gatik.ai/careers may redirect to archive.gatik.ai; API is authoritative
```

### May Mobility (rank 64)

```text
Source: Greenhouse API
Method: requests
Primary board: maymobility
Fallback board: maymobilityjobs (only if primary count == 0)
Endpoint: https://boards-api.greenhouse.io/v1/boards/maymobility/jobs?content=true
Sort: updated_at descending
URL: absolute_url -> https://job-boards.greenhouse.io/maymobility/jobs/{id}
Live note: primary board returned 42 US-filtered jobs; fallback not needed
```

### Avride (rank 65)

```text
Source: Greenhouse API
Method: requests
Board: avride
Endpoint: https://boards-api.greenhouse.io/v1/boards/avride/jobs?content=true
Sort: updated_at descending
URL: absolute_url -> https://job-boards.greenhouse.io/avride/jobs/{id}
Date caveat: many rows share updated_at; label exact field only
Auth caveat: detail may state U.S. authorization required, no relocation sponsorship
```

### Serve Robotics (rank 66)

```text
Source: Ashby API
Method: requests
Board: serverobotics
Endpoint: https://api.ashbyhq.com/posting-api/job-board/serverobotics?includeCompensation=true
Sort: publishedAt descending
URL: jobUrl -> https://jobs.ashbyhq.com/serverobotics/{id}
Date field: publishedAt (may be hidden on some rows)
```

### Gecko Robotics (rank 67)

```text
Source: Ashby API
Method: requests
Board: gecko-robotics
Endpoint: https://api.ashbyhq.com/posting-api/job-board/gecko-robotics?includeCompensation=true
Sort: publishedAt descending
URL: jobUrl -> https://jobs.ashbyhq.com/gecko-robotics/{id}
Caveat: defense/critical-infrastructure wording in detail for real script
Live note: 18 US-filtered postings available (below 50 limit)
```

### Skild AI (rank 68)

```text
Source: Greenhouse API
Method: requests
Board: skildai-careers
Endpoint: https://boards-api.greenhouse.io/v1/boards/skildai-careers/jobs?content=true
Sort: updated_at descending
URL: absolute_url -> https://job-boards.greenhouse.io/skildai-careers/jobs/{id}
Date caveat: old first_published with newer updated_at; label exact field only
Live note: 16 US-filtered postings available (below 50 limit)
```

### Motorola Solutions / Avigilon (rank 69)

```text
Source: Workday CXS
Method: requests
Endpoint: https://motorolasolutions.wd5.myworkdayjobs.com/wday/cxs/motorolasolutions/Careers/jobs
Public base: https://motorolasolutions.wd5.myworkdayjobs.com/Careers
Pagination: limit=20, offset=0,20,40
Sort: sortBy=postedOn
US filter: Workday facet discovery
Parser: jobPostings[].title, externalPath
URL: public_base + externalPath
Detail: GET .../Careers{externalPath} for jobPostingInfo in real script
Caveat: public-sector, FedRAMP, clearance, export-control wording
```

### Zebra Technologies (rank 70)

```text
Source: Workday CXS
Method: requests
Endpoint: https://zebra.wd501.myworkdayjobs.com/wday/cxs/zebra/Zebra_careers/jobs
Public base: https://zebra.wd501.myworkdayjobs.com/Zebra_careers
Pagination: limit=20, offset=0,20,40
Sort: sortBy=postedOn
US filter: Workday facet discovery
Parser: jobPostings[].title, externalPath
URL: public_base + externalPath
```

---

## Location Field Design

### Greenhouse

```text
location.name
offices[].name
```

US prefilter uses `is_us_text()` on combined location text. If no US rows match, fallback to all jobs (health-check mode).

### Ashby

```text
location
address.postalAddress.addressLocality
address.postalAddress.addressRegion
address.postalAddress.addressCountry
secondaryLocations[]
```

### Workday CXS

```text
locationsText (search rows)
jobPostingInfo.location (detail rows)
appliedFacets country/location facet IDs for US scoping
```

---

## Date and Timestamp Field Design

### Greenhouse (Nuro, Kodiak, Gatik, May Mobility, Avride, Skild AI)

```text
first_published
updated_at
created_at (sort fallback)
```

Rule: prefer `first_published` for posting date when building the real script. Do not treat `updated_at` as a new posting date for Avride or Skild AI without explicit evidence.

### Ashby (Serve Robotics, Gecko Robotics)

```text
publishedAt
```

Some rows may hide posting date in the public UI; API field is still the source of truth when present.

### Workday CXS (Motorola, Zebra)

```text
postedOn (search rows)
jobPostingInfo.postedOn (detail rows)
jobPostingInfo.startDate (when present)
```

---

## Known Caveats (Tester vs Real Script)

| Topic | Tester behavior | Real job_search_7 behavior |
|---|---|---|
| Keyword search | Not performed | Use profile terms and priority terms from company guide |
| Role relevance | Any parseable job counts as success | Filter by title + detail content |
| Sponsorship | Not checked | Reject per preferences and detail wording |
| Sample titles | May be non-technical (e.g. Service Technician) | Expected; tester only proves source access |
| Count < 50 | Valid `ok` if count > 0 | Reflects available US-filtered postings |
| Authorization | Not scanned | Scan for clearance, export control, citizenship, FedRAMP |

---

## Future Full Pipeline Mapping

```text
company_search_guide_part_07.md
   |
   v
Part 7 Source Tester (this repo)
   |
   v
Working Adapter (Greenhouse / Ashby / Workday)
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

The Part 7 source tester is boring and repeatable.

For each company:

```text
Find the official ATS API from the company guide.
Fetch broad recent/top records.
Prefer US location when visible.
Extract title, ID, URL, and note where date/location live.
Return the same Result object.
Move to the next company.
```

That is the pattern used for Part 1, applied here to ranks 61–70.

---

## Live Verification Summary

Date: 2026-06-22

```text
All 10 companies: status = ok
Nuro, Kodiak, Gatik, Serve Robotics, Motorola, Zebra: count = 50
May Mobility: count = 42
Avride: count = 37
Gecko Robotics: count = 18
Skild AI: count = 16
```

Source-access layer for `job_search_7` is ready.
