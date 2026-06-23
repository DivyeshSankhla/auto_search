# Unified Job Source Tester - Part 5

This README explains:

```bash
unified_job_source_tester.py
```

The script is a source-access tester for `job_search_5` companies, ranks 41-50. It proves whether each official source can return parseable recent/top job records before the real script adds profile filtering, detail enrichment, sponsorship checks, dedupe, and ledger append logic.

It does **not** run profile keyword searches.

---

## Purpose

The script verifies that job-search automation can pull job records from official company sources.

For each company, it prints:

```text
Company | Method | Status | Count | Sample title | Sample URL / Note
```

A source is considered working when:

```text
Status = ok
Count > 0
Sample URL is official or source-backed
```

---

## Core Rule

The tester follows the Part 1 pattern:

```text
official source first
recent/top broad results first
location early when the source supports it
keywords later in the real job-search script
top 50 postings for health-check coverage
```

Default health-check limit:

```text
JOB_SOURCE_TEST_LIMIT=50
```

Override example:

```bash
JOB_SOURCE_TEST_LIMIT=20 python3 unified_job_source_tester.py
```

---

## Run

From this folder:

```bash
python3 unified_job_source_tester.py
```

Expected output shape:

```text
Company | Method | Status | Count | Sample title | Sample URL / Note
```

---

## Status Meanings

| Status | Meaning |
|---|---|
| `ok` | Source returned parseable official/source-backed job records. |
| `blocked` | Source returned HTTP 403 or access was denied. |
| `failed` | Request failed because of timeout, DNS/network issue, or missing response. |
| `parser_failed` | Page/API loaded, but parser found no records. |
| `http_<code>` | Source returned a non-200 HTTP response. |

---

## Source Types

| Company | Source type | Top-50 method |
|---|---|---|
| Johnson Controls | Workday CXS | POST pages with `limit=20`, `offset=0,20,40` |
| Panasonic | Jibe API | GET first API page with `limit=50` |
| Canonical | Greenhouse API | Fetch all jobs, sort by update time, keep first 50 US/Americas matches |
| Roku | Greenhouse API | Fetch all jobs, sort by update time, keep first 50 US/Americas matches |
| Sonos | Workday CXS | POST pages with `limit=20`, `offset=0,20,40` |
| Bose | Workday CXS | POST pages with `limit=20`, `offset=0,20,40` |
| Verkada | Greenhouse API | Fetch all jobs, sort by update time, keep first 50 US/Americas matches |
| Samsara | Greenhouse API | Fetch all jobs, sort by update time, keep first 50 US/Americas matches |
| Zoox | Lever API | GET `/v0/postings/zoox` with `limit=50` |
| Rivian / Rivian VW | Jibe API + Ashby API | Rivian Jibe top 50 plus Rivian VW Ashby US records |

---

## Company-by-Company Behavior

### Johnson Controls

Method:

```text
requests
```

Source type:

```text
Workday CXS
```

Endpoint:

```text
https://jci.wd5.myworkdayjobs.com/wday/cxs/jci/JCI/jobs
```

The script first discovers the official Workday location facet:

```text
POST appliedFacets={}
limit=1
offset=0
searchText=""
```

Then it queries up to 50 postings with:

```text
appliedFacets=<US facet IDs when discoverable>
limit=20
offset=0,20,40
searchText=""
sortBy=postedOn
```

What it validates:

```text
- CXS API returns HTTP 200
- JSON contains jobPostings
- title and externalPath are present
- public URL can be built from the Workday career site
```

---

### Panasonic

Method:

```text
requests
```

Source type:

```text
Jibe API
```

Endpoint:

```text
https://careers.na.panasonic.com/api/jobs
```

The script queries Panasonic with:

```text
page=1
limit=50
sortBy=posted_date
descending=true
country=United States
```

What it validates:

```text
- API returns HTTP 200
- JSON contains jobs
- records expose data.title and data.req_id
- canonical URL is available or can be built
```

---

### Canonical

Method:

```text
requests
```

Source type:

```text
Greenhouse API
```

Endpoint:

```text
https://boards-api.greenhouse.io/v1/boards/canonical/jobs?content=true
```

The script:

```text
1. Fetches all official Greenhouse jobs.
2. Sorts by updated_at / created_at when present.
3. Keeps the first 50 US, North America, or Americas location matches.
```

Important location note:

```text
Canonical uses many remote/global locations such as Home based - Americas.
Those are accepted as US-region candidates for this source-health check.
```

---

### Roku

Method:

```text
requests
```

Source type:

```text
Greenhouse API
```

Endpoint:

```text
https://boards-api.greenhouse.io/v1/boards/roku/jobs?content=true
```

The script fetches all records, sorts by Greenhouse update time, and keeps the first 50 US/Americas records.

Public URLs use Roku's official careers domain:

```text
https://www.weareroku.com/jobs/<id>?gh_jid=<id>
```

---

### Sonos

Method:

```text
requests
```

Source type:

```text
Workday CXS
```

Endpoint:

```text
https://sonos.wd1.myworkdayjobs.com/wday/cxs/sonos/Sonos/jobs
```

The script queries:

```text
appliedFacets=<US facet IDs when discoverable>
limit=20
offset=0,20,40
searchText=""
sortBy=postedOn
```

If Sonos exposes fewer than 50 current postings, the tester returns the available official count.

---

### Bose

Method:

```text
requests
```

Source type:

```text
Workday CXS
```

Endpoint:

```text
https://boseallaboutme.wd503.myworkdayjobs.com/wday/cxs/boseallaboutme/Bose_Careers/jobs
```

The script queries:

```text
appliedFacets=<US facet IDs when discoverable>
limit=20
offset=0,20,40
searchText=""
sortBy=postedOn
```

---

### Verkada

Method:

```text
requests
```

Source type:

```text
Greenhouse API
```

Endpoint:

```text
https://boards-api.greenhouse.io/v1/boards/verkada/jobs?content=true
```

The script fetches all Greenhouse jobs, sorts by recency fields, and keeps the first 50 US/Americas records.

---

### Samsara

Method:

```text
requests
```

Source type:

```text
Greenhouse API
```

Endpoint:

```text
https://boards-api.greenhouse.io/v1/boards/samsara/jobs?content=true
```

The script fetches all Greenhouse jobs, sorts by recency fields, and keeps the first 50 US/Americas records.

Public URLs use Samsara's official careers domain:

```text
https://www.samsara.com/company/careers/roles/<id>?gh_jid=<id>
```

---

### Zoox

Method:

```text
requests
```

Source type:

```text
Lever API
```

Endpoint:

```text
https://api.lever.co/v0/postings/zoox
```

The script queries:

```text
mode=json
limit=50
```

Then it sorts by:

```text
createdAt descending
```

Location behavior:

```text
The tester prefers US records using country and categories.location.
If the API already returns fewer than 50 filtered records, the current official count is used.
```

---

### Rivian / Rivian VW

Method:

```text
requests
```

Source types:

```text
Rivian main careers -> Jibe API
Rivian and Volkswagen Group Technologies -> Ashby API
```

Rivian main endpoint:

```text
https://careers.rivian.com/api/jobs
```

Rivian main query:

```text
page=1
limit=50
sortBy=posted_date
descending=true
country=United States
```

Rivian VW endpoint:

```text
https://api.ashbyhq.com/posting-api/job-board/rivianvw.tech
```

What it validates:

```text
- Main Rivian Jibe API returns official jobs
- Rivian VW Ashby API returns official jobs
- Combined source-backed URLs can be deduped
```
