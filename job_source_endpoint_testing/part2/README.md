# Unified Job Source Tester - Part 2

This README explains:

```bash
unified_job_source_tester.py
```

The script is a source-access tester for `job_search_2` companies. It proves the official company source can return parseable recent/top job records before the real script adds profile filtering, detail enrichment, sponsorship checks, dedupe, and ledger append logic.

It does **not** run role keyword searches.

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

A source is working when:

```text
Status = ok
Count > 0
Sample URL is official or source-backed
```

---

## Status Meanings

| Status | Meaning |
|---|---|
| `ok` | Source returned parseable job records. |
| `blocked` | Source returned HTTP 403 or access was denied. |
| `failed` | Request failed because of timeout, DNS/network issue, or missing response. |
| `parser_failed` | Page/API loaded, but parser did not find job records. |
| `http_<code>` | Source returned a non-200 HTTP response. |

---

## Core Rule

The tester follows the Part 1 pattern:

```text
official source first
recent/top broad results
location early when the source supports it
keywords later in the real script
```

For Workday CXS sources, location is not a normal URL query string. The tester uses the official two-step CXS flow:

```text
1. POST empty search to discover facets
2. Find the US country/location facet IDs
3. POST again with appliedFacets using the exact returned facetParameter
```

---

## Company-by-Company Behavior

### Cisco / Meraki

Method:

```text
requests
```

Source type:

```text
Cisco Phenom rendered HTML with embedded page data
```

Endpoint pattern:

```text
https://careers.cisco.com/global/en/search-results
```

The script queries Cisco with:

```text
from=0,10,20,30,40
s=1
country=United States of America
```

Example URL:

```text
https://careers.cisco.com/global/en/search-results?from=0&s=1&country=United+States+of+America
```

What it validates:

```text
- Search page returns HTTP 200
- Embedded Phenom records are parseable
- Record country is United States / United States of America when present
- jobSeqNo can build an official careers.cisco.com detail URL
```

Main script use:

```text
Use Cisco Phenom as a normal official listing adapter.
Use jobSeqNo as the durable job key.
Fetch detail pages before scoring/appending.
```

---

### AMD / Xilinx

Method:

```text
requests
```

Source type:

```text
Jibe API
```

Endpoint pattern:

```text
https://careers.amd.com/api/jobs
```

The script queries AMD with:

```text
page=1
sortBy=posted_date
descending=true
country=United States
```

Exact URL:

```text
https://careers.amd.com/api/jobs?page=1&sortBy=posted_date&descending=true&country=United+States
```

What it validates:

```text
- API returns HTTP 200
- JSON contains jobs
- Jobs have titles and canonical official URLs
```

Main script use:

```text
Use as a Jibe API adapter.
Fetch recent US jobs first, then apply embedded/Linux/systems filters.
```

---

### Broadcom

Method:

```text
requests
```

Source type:

```text
Workday CXS API
```

Endpoint:

```text
https://broadcom.wd1.myworkdayjobs.com/wday/cxs/broadcom/External_Career/jobs
```

Facet discovery request:

```json
{"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""}
```

The script discovers:

```text
facetParameter=locations
US location IDs discovered live from nested locationMainGroup
```

Then it queries Broadcom with:

```json
{
  "appliedFacets": {"locations": ["<US location ids>"]},
  "limit": 20,
  "offset": 0,20,40,
  "searchText": ""
}
```

What it validates:

```text
- CXS API returns HTTP 200
- US location facet IDs are accepted
- jobPostings contain title, externalPath, locationsText
```

Main script use:

```text
Use Workday CXS with live US facet discovery.
Use externalPath as the durable source URL/key.
```

---

### Intel

Method:

```text
requests
```

Source type:

```text
Workday CXS API
```

Endpoint:

```text
https://intel.wd1.myworkdayjobs.com/wday/cxs/intel/External/jobs
```

The script discovers:

```text
facetParameter=locations
US location IDs discovered live from nested locationMainGroup
```

Then it queries Intel with:

```json
{
  "appliedFacets": {"locations": ["<US location ids>"]},
  "limit": 20,
  "offset": 0,20,40,
  "searchText": ""
}
```

What it validates:

```text
- CXS API returns HTTP 200
- Filtered response returns US Intel postings
- externalPath can build an official Workday URL
```

Main script use:

```text
Use Workday CXS with location facet discovery.
Filter noisy roles after the source adapter succeeds.
```

---

### Arm

Method:

```text
requests
```

Source type:

```text
TalentBrew rendered HTML
```

Endpoint pattern:

```text
https://careers.arm.com/search-jobs/?sort=posted_date
```

The Arm page exposes:

```text
United States country facet id = 6252001
Date Posted sort option = value 7 in rendered HTML
```

Important note:

```text
The static GET page exposes the US facet but did not reliably honor a simple Country=6252001 URL during testing.
The tester therefore fetches the official date-sort page and keeps obvious US rows from rendered job cards.
Unknown/multiple-location rows should be marked incomplete in the real script unless the detail page confirms US eligibility.
```

What it validates:

```text
- Search page returns HTTP 200
- Rendered HTML contains job-card__title links
- Job links resolve to official careers.arm.com URLs
```

Main script use:

```text
Use Arm rendered HTML as a source adapter.
Fetch detail pages for location confirmation before appending.
```

---

### Marvell

Method:

```text
requests
```

Source type:

```text
Workday CXS API
```

Endpoint:

```text
https://marvell.wd1.myworkdayjobs.com/wday/cxs/marvell/MarvellCareers/jobs
```

The script discovers:

```text
facetParameter=Country
United States of America facet ID discovered live
```

Then it queries Marvell with:

```json
{
  "appliedFacets": {"Country": ["<United States of America id>"]},
  "limit": 20,
  "offset": 0,20,40,
  "searchText": ""
}
```

What it validates:

```text
- CXS API accepts the Country facet
- US-filtered jobPostings are parseable
- externalPath builds official Workday URLs
```

---

### Texas Instruments

Method:

```text
requests
```

Source type:

```text
Oracle Candidate Experience API
```

Endpoint pattern:

```text
https://edbz.fa.us2.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions
```

The script queries TI with:

```text
onlyData=true
expand=requisitionList.secondaryLocations,flexFieldsFacet.values,requisitionList.requisitionFlexFields
finder=findReqs;siteNumber=CX,facetsList=LOCATIONS%3BWORK_LOCATIONS%3BTITLES%3BCATEGORIES%3BORGANIZATIONS%3BPOSTING_DATES%3BFLEX_FIELDS,limit=50,sortBy=POSTING_DATES_DESC
```

What it validates:

```text
- API returns HTTP 200
- requisitionList is parseable
- Results are sorted by posting date descending
- US rows are selected from returned country/location fields when available
```

Main script use:

```text
Use Oracle CE with POSTING_DATES_DESC.
Fetch details for exact location and sponsorship concerns.
```

---

### NXP

Method:

```text
requests
```

Source type:

```text
Workday CXS API
```

Endpoint:

```text
https://nxp.wd3.myworkdayjobs.com/wday/cxs/nxp/careers/jobs
```

The script discovers:

```text
facetParameter=Location_Country
United States of America facet ID discovered live
```

Then it queries NXP with:

```json
{
  "appliedFacets": {"Location_Country": ["<United States of America id>"]},
  "limit": 20,
  "offset": 0,20,40,
  "searchText": ""
}
```

What it validates:

```text
- CXS API accepts the Location_Country facet
- US-filtered jobPostings are parseable
- externalPath builds official Workday URLs
```

---

### Garmin

Method:

```text
requests
```

Source type:

```text
Jibe API
```

Endpoint pattern:

```text
https://careers.garmin.com/api/jobs
```

The script queries Garmin with:

```text
page=1
sortBy=posted_date
descending=true
country=United States
```

Exact URL:

```text
https://careers.garmin.com/api/jobs?page=1&sortBy=posted_date&descending=true&country=United+States
```

What it validates:

```text
- API returns HTTP 200
- JSON contains jobs
- Jobs have titles and canonical official URLs
```

---

### Sony / PlayStation

Method:

```text
requests
```

Source types:

```text
Sony Global Workday CXS
PlayStation Careers rendered HTML
```

Sony Global endpoint:

```text
https://sonyglobal.wd1.myworkdayjobs.com/wday/cxs/sonyglobal/SonyGlobalCareers/jobs
```

The script discovers:

```text
facetParameter=locationCountry
United States of America facet ID discovered live
```

Then it queries Sony Global with:

```json
{
  "appliedFacets": {"locationCountry": ["<United States of America id>"]},
  "limit": 20,
  "offset": 0,
  "searchText": ""
}
```

PlayStation endpoint:

```text
https://careers.playstation.com/jobs?sortBy=posted_date
```

What it validates:

```text
- Sony Workday CXS returns parseable postings
- PlayStation page returns parseable official job links when present
- Combined Sony records dedupe by URL
```

Main script use:

```text
Use Sony Workday first for structured data.
Use PlayStation as an additional official rendered source.
Fetch details before deciding location, sponsorship concern, and role fit.
```

---

## Current Live Verification

The revised tester was run successfully against live official sources on June 19, 2026.

Observed successful statuses:

```text
Cisco             ok
AMD               ok
Broadcom          ok
Intel             ok
Arm               ok
Marvell           ok
Texas Instruments ok
NXP               ok
Garmin            ok
Sony              ok
```

---

## What The Real job_search_2 Script Should Add

The real script should add:

```text
- endpoint health checks: ok, blocked, schema_changed, requires_browser
- per-run cache by job ID/detail URL
- configurable top result limit, default 50
- recent date filtering where posted dates are visible
- detail-page fetch before final decisions
- role/profile scoring after source fetch
- sponsorship handling as Concern: sponsorship not visible
- compact reject reason counts
- final ledger re-read immediately before append
```

Do not invent missing fields. If location, posted date, sponsorship, or job detail evidence is not visible, mark that field incomplete or as a concern in the real script.
