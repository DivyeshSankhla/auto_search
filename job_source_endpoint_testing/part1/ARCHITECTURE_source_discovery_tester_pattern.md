# Architecture Design: Source Discovery Tester Pattern

## Purpose

This file explains the architecture behind `unified_job_source_tester.py` and how the same design pattern should be used to build future job-search tester parts.

The tester is not the final job-search pipeline. It is the **source-discovery and source-health layer**.

Its purpose is:

```text
For each company, find the most reliable official job source, prove that it returns usable jobs, extract basic fields, and record the exact access method that should be reused later.
```

The same process should be repeated for other company-search parts.

---

## Core Idea

Every company has a different careers backend.

Some companies expose clean APIs. Some expose job data inside static HTML. Some need a browser because the page is JavaScript-rendered. Some block normal Python requests and need an alternate HTTP method. Some search pages fail, but detail pages still work.

The architecture is:

```text
Company guide
  -> official source discovery
  -> endpoint/page testing
  -> fallback method testing
  -> basic parser
  -> location/date/link field check
  -> unified Result output
```

The tester proves the access path first. The real job-search script can later use that access path for filtering, scoring, dedupe, and append.

---

## Design Rule

For every company, follow this order:

```text
1. Start with official source listed in the company guide.
2. Try the cleanest endpoint first.
3. If endpoint works, parse job records.
4. If endpoint fails, try official public HTML.
5. If HTML is JavaScript-rendered, use Playwright.
6. If normal Python HTTP is blocked, try curl_cffi or browser-like access.
7. If search page is blocked but detail pages work, use detail URL verification.
8. Extract title, job ID, location, timestamp, and official URL when visible.
9. Return one consistent Result object.
```

This is the architecture pattern used in Part 1.

---

## Source Testing Flow

```text
For each company:
    read official guide entry
    identify source type
    test primary endpoint
    inspect response shape
    parse count/title/url
    inspect location/date fields
    if primary fails:
        test official fallback
    return Result
```

The tester should not try to be smart before source access is proven. First prove the source works.

---

## Unified Result Object

Every company adapter must return the same structure:

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

This keeps all companies comparable even when their backends are different.

Example:

```text
NVIDIA | requests   | ok | 50 | Senior Software Architect - Data Center Systems | https://jobs.nvidia.com/...
Meta   | playwright | ok | 11 | Critical Facility Engineer                      | https://www.metacareers.com/...
Tesla  | curl_cffi  | ok | 5  | Firmware Engineer Silicon Tesla Ai              | https://www.tesla.com/...
```

---

## Status Design

Use simple statuses:

| Status | Meaning |
|---|---|
| `ok` | Source returned parseable jobs |
| `blocked` | Source returned access denied or HTTP 403 |
| `failed` | Network/request failed |
| `parser_failed` | Page loaded but parser found no jobs |
| `missing_playwright` | Browser-rendered source needs Playwright |
| `missing_curl_cffi` | Source needs curl_cffi |
| `http_<code>` | Source returned another HTTP response |

The status function should stay simple:

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

The important thing is not only HTTP status. A source is useful only if it returns parseable jobs.

---

## Access Method Decision Tree

Use this decision tree for every new company:

```text
Start
 |
 v
Is there a documented or discoverable API?
 |
 +-- yes -> test API with location/sort/date/query params
 |          |
 |          +-- jobs parsed -> use API adapter
 |          |
 |          +-- no jobs / bad schema -> inspect response, update parser
 |
 +-- no
      |
      v
Can static HTML expose job cards or embedded JSON?
 |
 +-- yes -> use requests + HTML/JSON parser
 |
 +-- no
      |
      v
Does browser-rendered page expose jobs?
 |
 +-- yes -> use Playwright rendered HTML parser
 |
 +-- no
      |
      v
Does normal Python get blocked?
 |
 +-- yes -> try curl_cffi / browser-like request
 |
 +-- still blocked
      |
      v
Can official detail URLs be verified directly?
 |
 +-- yes -> use detail URL verifier
 |
 +-- no -> mark blocked/incomplete
```

---

## Source Types Used in Part 1

Part 1 proved these source-access types:

| Source Type | Companies |
|---|---|
| PCS API | NVIDIA, Microsoft, Qualcomm |
| Static HTML | Apple |
| Static HTML / embedded job ID parser | Google |
| Rendered HTML | Meta |
| Ashby API | OpenAI |
| Amazon JSON | Amazon |
| Greenhouse API | Waymo |
| Detail URL verifier with browser-like HTTP | Tesla |

Future parts should reuse these source patterns whenever another company uses the same backend.

---

## Company Adapter Pattern

Each company should have one function:

```python
def test_company_name() -> Result:
    ...
```

For shared backends, use reusable helpers:

```python
test_pcs(...)
test_ashby(...)
test_greenhouse(...)
test_workday(...)
test_smartrecruiters(...)
test_oracle(...)
test_phenom(...)
test_jibe(...)
test_icims(...)
```

The adapter only needs to prove:

```text
- source opens
- records exist
- title can be parsed
- official/source-backed URL can be built
- location/date fields are visible if the source exposes them
```

---

## Endpoint Discovery Strategy

For each company guide section, identify these fields first:

```text
official source
search endpoint
detail endpoint
canonical public URL
priority terms
pagination method
location fields
date/timestamp fields
job ID fields
fallback notes
```

Then test in this order:

```text
1. API search endpoint
2. API detail endpoint
3. public search page
4. public detail page
5. embedded JSON in HTML
6. rendered HTML with Playwright
7. alternate official ATS source
8. browser-like HTTP fallback
9. official detail URL verification
```

Do not start with third-party job boards unless the company guide says they are official ATS surfaces, such as Greenhouse, Ashby, SmartRecruiters, Workday, Oracle, iCIMS, or Lever.

---

## Parameter Testing

When testing a source, check which parameters actually work.

Important parameters:

```text
query / keyword / searchText
location
country
start / offset / page
limit / page size
sort_by / sortBy
posted date sort
domain / board token / site number
```

Examples from Part 1:

```text
NVIDIA:
  domain=nvidia.com
  location=United States
  start=0,10,20,30,40
  sort_by=timestamp

Microsoft:
  domain=microsoft.com
  location=United States
  start=0,10,20,30,40
  sort_by=timestamp

Qualcomm:
  domain=qualcomm.com
  location=United States
  start=0,10,20,30,40
  sort_by=timestamp

Amazon:
  country=USA
  sort=recent
  result_limit=50

Apple:
  sort=newest
  location=united-states-USA
  page=1

Google:
  location=United States
  sort_by=date
  page=1
```

For future parts, do the same: test the parameters, keep the ones that work, and remove noisy or broken parameters.

---

## Location Field Design

Every source should be inspected for location fields.

Common location fields:

```text
location
locations
standardizedLocations
locationsText
location.name
location.fullLocation
PrimaryLocation
PrimaryLocationCountry
city
state
country
country_code
remote
hybrid
workplaceType
workLocationOption
locationFlexibility
```

Architecture rule:

```text
If the source exposes structured location, parse it.
If only visible text exists, parse visible text.
If no location is visible in search results, fetch detail page later.
```

For the tester, it is enough to confirm that location fields exist or that a detail URL is available where location can be checked later.

---

## Date and Timestamp Field Design

Every source should be inspected for posting or update fields.

Common date fields:

```text
posted_date
postedDate
postedOn
postedTs
creationTs
first_published
updated_at
publishedAt
releasedDate
datePosted
ExternalPostedStartDate
update_date
create_date
```

Architecture rule:

```text
Prefer posted date.
Use update date only if clearly labeled as Updated.
If no date exists, mark Posted hidden later in the full script.
```

For the tester, record that the date field exists and confirm the source can expose enough information for later filtering.

---

## Link and ID Design

Every company adapter should identify stable job evidence.

Common ID fields:

```text
id
job_id
jobId
jobSeqNo
req_id
requisition_id
RequisitionId
jobReqId
displayJobId
atsJobId
refNumber
externalPath
position_id
postingUuid
```

Common URL fields:

```text
publicUrl
positionUrl
canonicalPositionUrl
absolute_url
jobUrl
postingUrl
applyUrl
externalUrl
meta_data.canonical_url
```

Architecture rule:

```text
Always prefer canonical official public URL.
Preserve job ID or requisition ID as stable evidence.
If URL is relative, build it from the official base domain.
If URL contains tracking params, later dedupe should strip them.
```

---

## Fallback Method Design

A source can fail in different ways. Use the simplest fallback that works.

### Case 1: API Works

Use API directly.

Example:

```text
OpenAI -> Ashby API
Waymo -> Greenhouse API
Amazon -> Amazon JSON
```

### Case 2: API Not Available, Static HTML Works

Parse official HTML.

Example:

```text
Apple -> jobs.apple.com search page
```

### Case 3: Static HTML Has Hidden IDs

Parse embedded IDs or JavaScript data.

Example:

```text
Google -> static page with job IDs
```

### Case 4: JavaScript Rendering Required

Use Playwright.

Example:

```text
Meta -> rendered page exposes /profile/job_details/{job_id}
```

### Case 5: Normal Python HTTP Blocked

Use browser-like HTTP.

Example:

```text
Tesla -> curl_cffi with Chrome impersonation
```

### Case 6: Search Page Blocked but Detail Works

Use detail URL verification.

Example:

```text
Tesla -> skip search page, verify official detail URLs
```

---

## Backend Pattern Library

When building future parts, classify each company backend.

### PCS / Eightfold

Likely fields:

```text
data.positions
id
name
locations
standardizedLocations
postedTs
creationTs
positionUrl
publicUrl
canonicalPositionUrl
```

Test pattern:

```text
GET /api/pcsx/search?domain=<domain>&query=<query>&location=<location>&start=<offset>&sort_by=<date/timestamp>
```

### Workday CXS

Likely fields:

```text
jobPostings
title
externalPath
locationsText
postedOn
bulletFields
```

Test pattern:

```text
POST /wday/cxs/<tenant>/<site>/jobs
body: {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": "<query>"}
```

### Greenhouse

Likely fields:

```text
jobs
id
internal_job_id
requisition_id
title
absolute_url
location
departments
offices
metadata
first_published
updated_at
content
```

Test pattern:

```text
GET https://boards-api.greenhouse.io/v1/boards/<board>/jobs?content=true
```

### Ashby

Likely fields:

```text
jobs
id
title
department
employmentType
location
secondaryLocations
publishedAt
isRemote
workplaceType
jobUrl
applyUrl
descriptionPlain
```

Test pattern:

```text
GET https://api.ashbyhq.com/posting-api/job-board/<board>
```

### SmartRecruiters

Likely fields:

```text
content
id
name
refNumber
releasedDate
location
location.country
location.remote
location.hybrid
typeOfEmployment
customField
postingUrl
```

Test pattern:

```text
GET https://api.smartrecruiters.com/v1/companies/<company>/postings?limit=20&offset=0&q=<query>
GET https://api.smartrecruiters.com/v1/companies/<company>/postings/{id}
```

### Oracle Candidate Experience

Likely fields:

```text
requisitionList
Id
Title
PostedDate
PrimaryLocation
PrimaryLocationCountry
WorkplaceType
JobSchedule
WorkerType
ShortDescriptionStr
```

Test pattern:

```text
GET /hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true&finder=findReqs;siteNumber=<site>,keyword=<query>,limit=20,offset=0,sortBy=POSTING_DATES_DESC
```

### Phenom

Likely fields:

```text
phApp.ddo
jobs
jobSeqNo
jobId
title
location
postedDate
dateCreated
descriptionTeaser
```

Test pattern:

```text
GET /search-results?keywords=<query>&from=0&s=1
```

### Jibe

Likely fields:

```text
jobs[].data
req_id
title
location_name
country_code
employment_type
posted_date
update_date
description
meta_data.canonical_url
```

Test pattern:

```text
GET /api/jobs?keywords=<query>&page=1&sortBy=posted_date&descending=true
```

### iCIMS

Likely fields:

```text
job title
detail URL
Job Locations
Category
ID
schema.org JobPosting
datePosted
employmentType
jobLocation
```

Test pattern:

```text
GET /jobs/search?ss=1&searchKeyword=<query>
GET /jobs/{id}/{slug}/job
```

---

## Part 1 Adapter Summary

### NVIDIA

```text
Source: PCS API
Method: requests
Pagination: start=0,10,20,30,40
Sort: sort_by=timestamp
Location parameter: location=United States
Parser: data.positions / positions
URL: publicUrl / positionUrl / canonicalPositionUrl
```

### Apple

```text
Source: official search HTML
Method: requests
Sort: sort=newest
Location parameter: location=united-states-USA
Parser: /en-us/details/ links
URL: jobs.apple.com detail URL
```

### Google

```text
Source: official careers page
Method: requests
Location parameter: location=United States
Sort: sort_by=date
Parser: embedded numeric job IDs
URL: /about/careers/applications/jobs/results/{job_id}
```

### Microsoft

```text
Source: PCS API
Method: requests
Pagination: start=0,10,20,30,40
Sort: sort_by=timestamp
Location parameter: location=United States
Parser: data.positions / positions
URL: publicUrl / positionUrl / canonicalPositionUrl
```

### Meta

```text
Source: official jobsearch page
Method: Playwright
Reason: rendered HTML required
Parser: /profile/job_details/{job_id}
Title: h3 inside rendered job card
URL: metacareers.com/profile/job_details/{job_id}
```

### OpenAI

```text
Source: Ashby API
Method: requests
Parser: jobs
Date field: publishedAt
URL: jobUrl
```

### Amazon

```text
Source: Amazon jobs JSON
Method: requests
Sort: sort=recent
Location parameter: country=USA
Limit: result_limit=50
Parser: jobs
URL: amazon.jobs + job_path
```

### Waymo

```text
Source: Greenhouse API
Method: requests
Parser: jobs
Date fields: first_published / updated_at
URL: absolute_url
```

### Qualcomm

```text
Source: PCS API
Method: requests
Pagination: start=0,10,20,30,40
Sort: sort_by=timestamp
Location parameter: location=United States
Parser: data.positions / positions
URL: publicUrl / positionUrl / canonicalPositionUrl
```

### Tesla

```text
Source: official detail URLs
Method: curl_cffi
Reason: normal Python requests to search/detail pages can be blocked
Search page: skip
Verification: HTTP 200 + official Tesla detail URL + title + Req ID
Title fallback: URL slug
Req ID fallback: URL suffix
URL pattern: /careers/search/job/{slug}-{req_id}
```

---

## How to Architect Future Parts

For every new part, the AI should follow this checklist.

### Step 1: Read Company Guide

For each company, collect:

```text
company name
official sources
search endpoint
detail endpoint
canonical public URL
priority terms
pagination method
known caveats
```

### Step 2: Build Minimal Tester

Create one small function per company:

```python
def test_company() -> Result:
    ...
```

Do not build full filtering yet. First prove source access.

### Step 3: Test Endpoint Parameters

Try:

```text
query
location
country
sort by date
offset/page/start
limit
domain/site/board token
```

Keep only parameters that return useful records.

### Step 4: Inspect Response Shape

Print or inspect top-level keys:

```text
jobs
positions
data.positions
jobPostings
requisitionList
items
content
```

Then identify:

```text
title field
job ID field
URL field
location field
posted date field
employment type field
description/detail field
```

### Step 5: Build Basic Parser

Parser should return:

```text
count
sample title
sample URL
```

If count is zero but page is HTTP 200, mark `parser_failed`.

### Step 6: Try Fallbacks

If the primary method fails, test in this order:

```text
API endpoint
static HTML
embedded JSON
rendered HTML with Playwright
alternate official ATS
curl_cffi browser-like HTTP
detail URL verifier
```

### Step 7: Record Final Method

Once working, record the source method:

```text
requests
playwright
curl_cffi
detail_url_verifier
```

Also record source type:

```text
PCS API
Workday CXS
Greenhouse API
Ashby API
SmartRecruiters API
Oracle API
Phenom HTML
Jibe API
iCIMS HTML
Static HTML
Rendered HTML
Custom JSON
Detail URL verifier
```

### Step 8: Confirm Location and Timestamp Possibility

Before calling a company source usable, confirm one of these:

```text
location visible in search row
location visible in detail page
date visible in search row
date visible in detail page
date hidden but official URL/detail available
```

For the tester, the goal is not full filtering. The goal is to know where filtering will come from later.

### Step 9: Keep Output Uniform

Every company must print in the same table:

```text
Company | Method | Status | Count | Sample title | Sample URL / Note
```

This makes it easy to compare source health across a whole part.

---

## Future Full Pipeline Mapping

The tester produces the source-access design.

The full search script should use the tested source method and then add:

```text
source adapter
raw job extraction
normalized job object
location/date/employment filtering
detail fetch
authorization/exclusion scan
score
dedupe
append or dry-run
```

Architecture:

```text
Company Guide
   |
   v
Source Tester
   |
   v
Working Adapter
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
Ledger Deduplication
   |
   v
Output / Append
```

---

## Design Principle

The source tester should be boring and repeatable.

For each company:

```text
Find the official source.
Try the simplest endpoint.
If it works, keep it.
If it does not, try the next official method.
Extract title, ID, location/date possibility, and URL.
Return the same Result object.
Move to the next company.
```

That is the pattern used for Part 1, and that is the pattern an AI should repeat for all other parts.
