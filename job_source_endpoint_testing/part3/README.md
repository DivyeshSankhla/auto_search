# Unified Job Source Tester - Part 3

This README explains:

```bash
unified_job_source_tester.py
```

The script is a source-access tester for `job_search_3` companies, ranks 21-30. It proves whether each official source can return parseable recent/top job records before the real script adds profile filtering, detail enrichment, sponsorship checks, dedupe, and ledger append logic.

It does **not** run profile keyword searches.

---

## Run

From this folder:

```bash
python3 unified_job_source_tester.py
```

Default health-check limit:

```text
JOB_SOURCE_TEST_LIMIT=20
```

Override example:

```bash
JOB_SOURCE_TEST_LIMIT=50 python3 unified_job_source_tester.py
```

Expected output shape:

```text
Company | Method | Status | Count | Sample title | Sample URL / Note
```

---

## Status Meanings

| Status | Meaning |
|---|---|
| `ok` | Source returned parseable official job records. |
| `blocked` | Source returned HTTP 403 or access was denied. |
| `failed` | Request failed because of timeout, DNS/network issue, or missing response. |
| `schema_changed` | Source loaded, but parser found no records. |
| `requires_browser` | Static requests are not enough; browser-rendered page/filtering is required. |
| `http_<code>` | Source returned a non-200 HTTP response. |

---

## Core Rule

The tester follows the same Part 1 / Part 2 rule:

```text
official source first
recent/top broad results
location early when the source supports it
keywords later in the real script
```

For sub-brands inside HPE Careers, `Aruba` and `Juniper` are treated as company/brand discriminators, not profile role keywords.

---

## Company-by-Company Behavior

### Bosch

Method:

```text
requests
```

Source type:

```text
Bosch CaaS jobs aggregation API
```

Config source:

```text
https://jobs.bosch.com/en/
```

The script reads:

```text
window.EXTERNAL_CONFIG.jobsApi
jobAdLinkPrefix
```

Then it queries Bosch with:

```text
GET https://bosch-i3-caas-api.e-spirit.cloud/bosch-i3-prod/bosch-de.jobs.content/_aggrs/get_jobs
Authorization: Bearer <page-provided apiKey>
np
rep=pj
pagesize=<limit>
page=1
avars={"country":["us"],"sort":{"releasedDate":-1}}
```

What it validates:

```text
- Page exposes official API config
- API returns HTTP 200
- data[] contains jobs
- jobUrl builds an official jobs.bosch.com URL
```

---

### Siemens

Method:

```text
requests
```

Source type:

```text
Avature static HTML
```

The script queries Siemens with:

```text
https://jobs.siemens.com/en_US/externaljobs/SearchJobs/
folderRecordsPerPage=6
folderOffset=0,6,12,...
folderSort=postedDate
folderSortDirection=desc
```

What it validates:

```text
- HTML returns HTTP 200
- JobDetail links are parseable
- Card title and official detail URL are captured
```

---

### Honeywell

Method:

```text
requests
```

Source type:

```text
Oracle Candidate Experience API
```

The script queries Honeywell with:

```text
GET https://ibqbjb.fa.ocs.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions
onlyData=true
expand=requisitionList.secondaryLocations,flexFieldsFacet.values,requisitionList.requisitionFlexFields
finder=findReqs;siteNumber=CX_1,facetsList=LOCATIONS%3BWORK_LOCATIONS%3BTITLES%3BCATEGORIES%3BORGANIZATIONS%3BPOSTING_DATES%3BFLEX_FIELDS,limit=25,offset=0,sortBy=POSTING_DATES_DESC
```

What it validates:

```text
- API returns HTTP 200
- requisitionList is parseable
- Rows can build careers.honeywell.com detail URLs
- US rows are preferred when visible
```

---

### HPE Aruba Networking

Method:

```text
requests
```

Source type:

```text
HPE Phenom rendered/static page data
```

The script checks:

```text
https://careers.hpe.com/us/en/search-results?keywords=Aruba&from=0&s=1&country=United+States
```

Current result:

```text
requires_browser
```

Reason:

```text
The static page loads, but it does not expose brand-filtered Aruba job records reliably. Browser-rendered filtering or the HPE widget API is needed before treating Aruba as searchable.
```

---

### Juniper Networks

Method:

```text
requests
```

Source type:

```text
HPE / Juniper Phenom rendered/static page data
```

The script checks:

```text
https://careers.hpe.com/us/en/search-results?keywords=Juniper&from=0&s=1&country=United+States
```

Current result:

```text
requires_browser
```

Reason:

```text
The static page loads, but it does not expose brand-filtered Juniper job records reliably. Browser-rendered filtering or the HPE widget API is needed before treating Juniper as searchable.
```

---

### Arista Networks

Method:

```text
requests
```

Official page:

```text
https://www.arista.com/en/careers/job-openings
```

Current result:

```text
requires_browser
```

Reason:

```text
Terminal requests return an Arista Client Challenge page with _fs-ch assets. Do not use unofficial mirrors. Use a browser-visible official Arista page for discovery and final verification.
```

---

### Fortinet

Method:

```text
requests
```

Source type:

```text
Oracle Candidate Experience API
```

The script queries Fortinet with:

```text
GET https://edel.fa.us2.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions
onlyData=true
finder=findReqs;siteNumber=CX_2001,...,limit=25,offset=0,sortBy=POSTING_DATES_DESC
```

Public detail pattern:

```text
https://edel.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_2001/job/{Id}
```

What it validates:

```text
- API returns HTTP 200
- requisitionList is parseable
- Rows can build official Fortinet Oracle detail URLs
- US rows are preferred when visible
```

---

### Ciena

Method:

```text
requests
```

Source type:

```text
Workday CXS API
```

Facet discovery request:

```json
{"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""}
```

The script discovers the US country facet, currently:

```text
facetParameter=Location_Country
descriptor=United States of America
```

Then it queries Ciena with:

```json
{
  "appliedFacets": {"Location_Country": ["<United States of America id>"]},
  "limit": 20,
  "offset": 0,
  "searchText": ""
}
```

What it validates:

```text
- CXS API accepts the official country facet
- jobPostings are parseable
- externalPath builds official Workday URLs
```

---

### Nokia

Method:

```text
requests
```

Documented source:

```text
https://fa-evmr-saasfaprod1.fa.ocs.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions
```

The script queries Nokia with:

```text
siteNumber=CX_1
limit=25
offset=0
sortBy=POSTING_DATES_DESC
```

Current result:

```text
http_503
```

Reason:

```text
The documented official Oracle host returned HTTP 503 during live testing on June 19, 2026. The public Nokia careers page did not expose a replacement API host through static requests. Do not invent jobs; retry later or use browser verification.
```

---

### Ericsson

Method:

```text
requests
```

Source type:

```text
PCS API
```

The script queries Ericsson with:

```text
https://jobs.ericsson.com/api/pcsx/search
domain=ericsson.com
location=United States
start=0
sort_by=timestamp
```

What it validates:

```text
- API returns HTTP 200
- JSON contains data.positions
- Position has name and official careers URL
```

---

## Current Live Verification

Live run on June 19, 2026:

```text
Bosch                ok
Siemens              ok
Honeywell            ok
HPE Aruba Networking requires_browser
Juniper Networks     requires_browser
Arista Networks      requires_browser
Fortinet             ok
Ciena                ok
Nokia                http_503
Ericsson             ok
```

---

## Real job_search_3 Script Notes

The real script should add:

```text
- endpoint health checks: ok, blocked, schema_changed, requires_browser
- request retry/backoff for 429, 5xx, timeout
- per-run cache by job ID/detail URL
- configurable top result limit, default 50
- posted-date filtering where dates are visible
- detail-page fetch before final decisions
- role/profile scoring after source fetch
- sponsorship handling as Concern: sponsorship not visible
- compact reject reason counts
- final ledger re-read immediately before append
```

Do not invent missing fields. If location, posted date, sponsorship, or job detail evidence is not visible, mark it incomplete or as a concern.
