# Unified Job Source Tester - Part 4

This README explains:

```bash
unified_job_source_tester.py
```

The script is a source-access tester for `job_search_4` companies, ranks 31-40. It proves whether each official source can return parseable recent/top job records before the real script adds profile filtering, detail enrichment, sponsorship checks, dedupe, and ledger append logic.

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
| Medtronic | Workday CXS | POST pages with `limit=20`, `offset=0,20,40` |
| Intuitive Surgical | Workday CXS | POST pages with `limit=20`, `offset=0,20,40` |
| GE HealthCare | Workday CXS | POST pages with `limit=20`, `offset=0,20,40` |
| Siemens Healthineers | SearchJobs static HTML | GET pages with `folderRecordsPerPage=6`, `folderOffset=0,6,12,...,48` |
| Dexcom | Workday CXS | POST pages with `limit=20`, `offset=0,20,40` |
| Rockwell Automation | Workday CXS | POST pages with `limit=20`, `offset=0,20,40` |
| Schneider Electric | Jibe API | GET first API page with `limit=50` |
| Eaton | Eightfold PCS API | GET `/api/pcsx/search` with `num=50` |
| Caterpillar | Official XML feed | Parse first 50 US jobs from official XML |
| John Deere | SuccessFactors/J2W static HTML | GET pages with `startrow=0,25` |

---

## Company-by-Company Behavior

### Medtronic

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
https://medtronic.wd1.myworkdayjobs.com/wday/cxs/medtronic/MedtronicCareers/jobs
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

Main script use:

```text
Use as a normal Workday CXS adapter.
Fetch recent US/top postings first, then apply relevance filtering later.
```

---

### Intuitive Surgical

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
https://intuitive.wd1.myworkdayjobs.com/wday/cxs/intuitive/irtc_careers/jobs
```

The script uses the same Workday flow:

```text
1. Discover facets with an empty POST.
2. Find US/location facet IDs when Workday exposes them.
3. POST recent/top pages with limit=20 and offset=0,20,40.
```

Payload:

```text
appliedFacets=<US facet IDs when discoverable>
limit=20
offset=0,20,40
searchText=""
sortBy=postedOn
```

What it validates:

```text
- jobPostings exist
- title is parseable
- externalPath builds an official intuitive.wd1.myworkdayjobs.com URL
```

Main script use:

```text
Use as a Workday CXS source.
Expect the source to return only the postings currently available for this board.
```

---

### GE HealthCare

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
https://gehc.wd5.myworkdayjobs.com/wday/cxs/gehc/GEHC_ExternalSite/jobs
```

The script queries with:

```text
appliedFacets=<US facet IDs when discoverable>
limit=20
offset=0,20,40
searchText=""
sortBy=postedOn
```

What it validates:

```text
- API returns HTTP 200
- jobPostings contains records
- title and externalPath are available
- generated URL is on gehc.wd5.myworkdayjobs.com
```

Main script use:

```text
Use as a Workday CXS adapter.
Remote US postings may appear as Remote when Workday location facets allow it.
```

---

### Siemens Healthineers

Method:

```text
requests
```

Source type:

```text
SearchJobs static HTML
```

Endpoint pattern:

```text
https://jobs.siemens-healthineers.com/en_US/searchjobs/SearchJobs
```

The script queries with:

```text
folderRecordsPerPage=6
folderOffset=0,6,12,18,24,30,36,42,48
folderSort=postedDate
folderSortDirection=desc
```

Important location note:

```text
The tested SearchJobs location parameters did not change the result set.
For this tester, Siemens Healthineers is fetched as official recent/top broad results.
The real script should apply location filtering after detail enrichment when needed.
```

What it validates:

```text
- Search page returns HTTP 200
- HTML contains /JobDetail/<id> links
- title can be parsed from article cards
- official jobs.siemens-healthineers.com URLs can be reused
```

Main script use:

```text
Use as a SearchJobs static HTML adapter.
Sort by posted date descending at source.
Filter by location and relevance later if the listing page does not expose enough structure.
```

---

### Dexcom

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
https://dexcom.wd1.myworkdayjobs.com/wday/cxs/dexcom/Dexcom/jobs
```

Dexcom exposes location facets mostly as city/state values, not a simple country facet.

The script identifies US facet values by:

```text
United States / US text
US state names such as California, Arizona, Utah, Virginia, etc.
```

Then it queries:

```text
appliedFacets=<US location IDs>
limit=20
offset=0,20,40
searchText=""
sortBy=postedOn
```

What it validates:

```text
- Workday CXS API works
- US location facets can be applied
- title and externalPath build an official Dexcom Workday URL
```

Main script use:

```text
Use as a Workday CXS adapter.
Keep the state-name facet matcher because country-only matching misses Dexcom US jobs.
```

---

### Rockwell Automation

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
https://rockwellautomation.wd1.myworkdayjobs.com/wday/cxs/rockwellautomation/External_Rockwell_Automation/jobs
```

The script queries with:

```text
appliedFacets=<US facet IDs when discoverable>
limit=20
offset=0,20,40
searchText=""
sortBy=postedOn
```

What it validates:

```text
- jobPostings exist
- title is parseable
- externalPath builds an official Rockwell Workday URL
```

Main script use:

```text
Use as a Workday CXS adapter.
Expect a mix of automation, software, firmware, operations, and business roles before profile filtering.
```

---

### Schneider Electric

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
https://careers.se.com/api/jobs
```

The script queries Schneider with:

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
- canonical URL is available in meta_data.canonical_url
```

Generated URL example:

```text
https://careers.se.com/jobs/<req_id>?lang=en-us
```

Main script use:

```text
Use as a normal Jibe API adapter.
The source handles US country filtering and posted-date descending sort.
```

---

### Eaton

Method:

```text
requests
```

Source type:

```text
Eightfold PCS API
```

Endpoint:

```text
https://eaton.eightfold.ai/api/pcsx/search
```

The script queries Eaton with:

```text
domain=eaton.com
query=
location=United States
start=0
num=50
```

What it validates:

```text
- API returns HTTP 200
- JSON contains data.positions
- test-only postings are removed
- positionUrl builds an official eaton.eightfold.ai URL
```

Generated URL format:

```text
https://eaton.eightfold.ai/careers/job/<position_id>
```

Main script use:

```text
Use as an Eightfold PCS adapter.
Source supports location=United States and num=50 directly.
```

---

### Caterpillar

Method:

```text
requests
```

Source type:

```text
official Caterpillar XML job feed
```

Endpoint:

```text
https://careers.caterpillar.com/en/jobs/xml/?rss=true
```

Why XML is used:

```text
The public /en/jobs/ HTML page exposes 20 visible job links.
The official XML feed exposes the full source-backed job list with title, date, requisition ID, URL, city, state, and country.
```

The script parses up to 50 US jobs by reading:

```text
<job>
  <title>
  <date>
  <requisitionid>
  <url>
  <country>
</job>
```

Location filtering:

```text
country must match United States / US.
```

Sort/recency behavior:

```text
The feed is consumed in source order, which is the same newest-first order shown by the jobs page.
The tester keeps the first 50 matching US postings.
```

Main script use:

```text
Use the XML feed for broad source collection.
Use <requisitionid> or URL as the stable job key.
```

---

### John Deere

Method:

```text
requests
```

Source type:

```text
SuccessFactors/J2W static HTML
```

Endpoint pattern:

```text
https://jobs.deere.com/search/
```

The script queries John Deere with:

```text
q=
locationsearch=United States
sortColumn=referencedate
sortDirection=desc
startrow=0,25
```

What it validates:

```text
- Search pages return HTTP 200
- HTML contains /eightfold/job/... or /successfactors/job/... links
- title text is parseable from the anchor
- official jobs.deere.com URLs can be reused
```

Top-50 behavior:

```text
startrow=0 returns the first page.
startrow=25 returns the next page.
Duplicates from repeated desktop/mobile anchors are deduped by URL.
```

Main script use:

```text
Use as an official static HTML adapter.
Use URL as the stable key unless a detail fetch later exposes a cleaner requisition ID.
```
