# Unified Job Source Tester - Part 8

This README explains:

```bash
unified_job_source_tester.py
```

The script is a source-access tester for `job_search_8` companies, ranks 71-80. It proves whether each official source can return parseable recent/top job records before the real script adds profile filtering, detail enrichment, sponsorship checks, dedupe, and ledger append logic.

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

## Install Requirements

The script uses Python standard libraries only. No extra packages are required for Part 8.

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
| `failed` | Request failed because of timeout, network error, or missing response. |
| `parser_failed` | Page/API loaded, but parser found no records. |
| `http_<code>` | Source returned a non-200 HTTP response. |

Counts under 50 mean the official source currently has fewer matching postings after the broad US location filter, not that the endpoint failed.

---

## Source Types

| Company | Source type | Top-50 method |
|---|---|---|
| Cognex | Workday CXS | POST pages with US facet discovery, `limit=20`, `offset=0,20,40` |
| Axis Communications | Workday CXS | POST pages with US facet discovery, `limit=20`, `offset=0,20,40` |
| Arlo | Workday CXS | POST pages with US facet discovery, `limit=20`, `offset=0,20,40` |
| Ubiquiti | Greenhouse API | Fetch all jobs from `ubiquiti`, sort by update time, keep first 50 US matches |
| Netgear | Ashby API | Fetch Ashby board `netgear`, sort by `publishedAt`, keep first 50 US matches |
| TP-Link | Workable markdown | GET `jobs.md` with US country filter, parse table rows |
| Ambarella | Workday CXS | POST pages with US facet discovery, `limit=20`, `offset=0,20,40` |
| ON Semiconductor | Oracle CE API | GET Oracle `recruitingCEJobRequisitions`, sort by `POSTING_DATES_DESC` |
| MediaTek | Next.js detail pages | Cookie-warm session, crawl official detail pages via related-job links |
| Renesas | SmartRecruiters API | GET `renesaselectronics` postings, sort by `releasedDate` |

---

## Company-by-Company Behavior

### Cognex

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
https://cognex.wd1.myworkdayjobs.com/wday/cxs/cognex/External_Career_Site/jobs
```

Public base:

```text
https://cognex.wd1.myworkdayjobs.com/External_Career_Site
```

What it validates:

```text
- Workday CXS returns HTTP 200
- jobPostings array contains title and externalPath
- Public URL can be built from externalPath
```

Main script use:

```text
Use as a Workday CXS adapter.
Strong machine-vision and industrial automation software roles may be mixed with sales and field roles.
```

---

### Axis Communications

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
https://axis.wd3.myworkdayjobs.com/wday/cxs/axis/External_Career_Site/jobs
```

Public base:

```text
https://axis.wd3.myworkdayjobs.com/External_Career_Site
```

Important note:

```text
Many embedded/Linux/camera roles are in Sweden.
US rows may be sparse; count below 50 is normal.
```

---

### Arlo

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
https://arlo.wd12.myworkdayjobs.com/wday/cxs/arlo/External_Careers/jobs
```

Public base:

```text
https://arlo.wd12.myworkdayjobs.com/External_Careers
```

Important note:

```text
Do not infer country from abbreviations in locationsText alone.
An Arlo detail can show CA - Remote while country.descriptor is Canada.
Use detail country fields in the real script.
```

---

### Ubiquiti

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
https://boards-api.greenhouse.io/v1/boards/ubiquiti/jobs?content=true
```

Canonical public URL:

```text
https://job-boards.greenhouse.io/ubiquiti/jobs/{id}
```

Important note:

```text
Many Ubiquiti rows share the same updated_at timestamp.
Label dates by the exact field exposed.
Prefer R&D rows and Team metadata such as Firmware for technical fit in the real script.
```

---

### Netgear

Method:

```text
requests
```

Source type:

```text
Ashby API
```

Endpoint:

```text
https://api.ashbyhq.com/posting-api/job-board/netgear?includeCompensation=true
```

Canonical public URL:

```text
https://jobs.ashbyhq.com/netgear/{id}
```

What it validates:

```text
- API returns HTTP 200
- JSON contains jobs
- At least one job has title and jobUrl
```

---

### TP-Link

Method:

```text
requests
```

Source type:

```text
Workable markdown
```

Endpoint:

```text
https://apply.workable.com/tp-link-usa-corp/jobs.md?location[0][country]=United States
```

Canonical public URL:

```text
https://apply.workable.com/tp-link-usa-corp/j/{shortcode}/
```

What it validates:

```text
- jobs.md returns a markdown table
- Rows contain title, location, posted date, and Details link
- Shortcode builds an official Workable detail URL
```

Important note:

```text
The bare jobs.md index without filters only returns board metadata.
The tester always applies a US country filter.
Detail markdown can include explicit sponsorship limitations.
```

---

### Ambarella

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
https://ambarella.wd108.myworkdayjobs.com/wday/cxs/ambarella/Ambarella/jobs
```

Public base:

```text
https://ambarella.wd108.myworkdayjobs.com/Ambarella
```

Important note:

```text
Use externalPath exactly as returned; do not repair unusual slugs.
Downrank MIS, application engineering, and hardware-only rows in the real script unless software ownership is explicit.
```

---

### ON Semiconductor

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
GET https://hctz.fa.us2.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions
finder=findReqs;siteNumber=CX_1001,...;sortBy=POSTING_DATES_DESC
```

Canonical public URL:

```text
https://hctz.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/job/{Id}
```

What it validates:

```text
- Oracle REST returns HTTP 200
- requisitionList contains Title and Id
- Public detail URL can be built from Id
```

Main script use:

```text
Use Oracle CE for search rows, then fetch browser detail when REST description fields are empty.
```

---

### MediaTek

Method:

```text
requests
```

Source type:

```text
Next.js careers detail pages
```

Entry page:

```text
https://careers.mediatek.com/en/jobs
```

Detail URL pattern:

```text
https://careers.mediatek.com/en/jobs/{id}
```

What it validates:

```text
- Cookie-warmed session can open official detail pages
- Page title parses to a job title
- Related job IDs on detail pages expose additional official postings
```

Important note:

```text
The public list page is client-rendered and does not expose a stable unauthenticated list API.
The tester uses a detail-page crawl seeded from a known official posting.
The real script should use the same detail URLs and inspect full page content for location, category, and publishedDate.
```

---

### Renesas

Method:

```text
requests
```

Source type:

```text
SmartRecruiters API
```

Endpoint:

```text
https://api.smartrecruiters.com/v1/companies/renesaselectronics/postings?limit=20&offset=0
```

Canonical public URL:

```text
https://jobs.smartrecruiters.com/RenesasElectronics/{id}
```

What it validates:

```text
- API returns HTTP 200
- content array contains name and id
- Public SmartRecruiters URL can be built from id
```

Important note:

```text
The feed mixes Renesas, Altium, and Transphorm rows plus many global manufacturing roles.
Detail text can include no-sponsorship and export-control wording.
```

---

## What This Tester Does Not Do

This tester does not:

```text
- filter jobs by your resume
- reject jobs by years of experience
- reject sponsorship-unfriendly jobs
- check posted date deeply
- append to jobs_found.md
- deduplicate against your ledger
- score jobs
- generate final job-search output
```

Those belong in the real job-search script.

This tester only answers:

```text
Can the source be accessed and parsed using the intended method?
```

---

## Current Live Verification

Run date: 2026-06-22

```text
Company             | Method   | Status | Count | Sample title                                       | Sample URL / Note
--------------------+----------+--------+-------+----------------------------------------------------+------------------------------------------------------------------------------------------------
Cognex              | requests | ok     | 15    | Director, Global Demand Generation                 | https://cognex.wd1.myworkdayjobs.com/External_Career_Site/job/Natick-Massachusetts/Director--Gl
Axis Communications | requests | ok     | 23    | Strategic Alliance Manager                         | https://axis.wd3.myworkdayjobs.com/External_Career_Site/job/USA---MA---Chelmsford/Business-Deve
Arlo                | requests | ok     | 22    | Sr. Wireless System Test Engineer (Contractor)     | https://arlo.wd12.myworkdayjobs.com/External_Careers/job/Carlsbad-CA/Sr-Wireless-System-Test-En
Ubiquiti            | requests | ok     | 4     | Rapid Response Support Specialist                  | https://job-boards.greenhouse.io/ubiquiti/jobs/4290512009
Netgear             | requests | ok     | 6     | Senior Global IT Service Desk Manager              | https://jobs.ashbyhq.com/netgear/13674b7d-cf70-4e38-98e7-208f1db8b993
TP-Link             | requests | ok     | 30    | Senior Manager, Embedded Systems Software (Omada N | https://apply.workable.com/tp-link-usa-corp/j/94F209DFB4/
Ambarella           | requests | ok     | 22    | Director, MIS – Software Applications              | https://ambarella.wd108.myworkdayjobs.com/Ambarella/job/US-Headquarters/Director--MIS---Softwar
ON Semiconductor    | requests | ok     | 29    | Manufacturing Equipment Technician - Backend       | https://hctz.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/job/2504506
MediaTek            | requests | ok     | 13    | Sr. Staff/Principal Engineer — GPU Driver & System | https://careers.mediatek.com/en/jobs/MUS120260610002
Renesas             | requests | ok     | 20    | AI Automation Architect                            | https://jobs.smartrecruiters.com/RenesasElectronics/744000133440862
```

All ten companies returned `ok`. Counts below 50 reflect fewer US-filtered or discoverable postings from the official source, not endpoint failure.

---

## Intended Next Step

After this tester works, the real job-search script should reuse these adapters:

```text
Cognex              -> requests Workday CXS
Axis Communications -> requests Workday CXS
Arlo                -> requests Workday CXS
Ubiquiti            -> requests Greenhouse (ubiquiti)
Netgear             -> requests Ashby (netgear)
TP-Link             -> requests Workable markdown (tp-link-usa-corp)
Ambarella           -> requests Workday CXS
ON Semiconductor    -> requests Oracle CE (CX_1001)
MediaTek            -> requests detail pages + related-job discovery
Renesas             -> requests SmartRecruiters (renesaselectronics)
```

Then the real script should add:

```text
- normalized job object
- date filtering
- role relevance filtering
- sponsorship rejection
- duplicate ledger check
- scoring
- dry-run output
- optional append mode
```

---

## Simple Success Target

Before building the real job-search script, this tester should show:

```text
Cognex              ok
Axis Communications ok
Arlo                ok
Ubiquiti            ok
Netgear             ok
TP-Link             ok
Ambarella           ok
ON Semiconductor    ok
MediaTek            ok
Renesas             ok
```

If all show `ok`, the source-access layer is ready.
