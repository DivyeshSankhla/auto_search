# Unified Job Source Tester - Part 7

This README explains:

```bash
unified_job_source_tester.py
```

The script is a source-access tester for `job_search_7` companies, ranks 61-70. It proves whether each official source can return parseable recent/top job records before the real script adds profile filtering, detail enrichment, sponsorship checks, dedupe, and ledger append logic.

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

The script uses Python standard libraries only. No extra packages are required for Part 7.

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
| Nuro | Greenhouse API | Fetch all jobs from `nuro`, sort by update time, keep first 50 US matches |
| Kodiak Robotics | Greenhouse API | Fetch all jobs from `kodiak`, sort by update time, keep first 50 US matches |
| Gatik | Greenhouse API | Fetch all jobs from `gatikaiinc`, sort by update time, keep first 50 US matches |
| May Mobility | Greenhouse API | Primary board `maymobility`; fallback `maymobilityjobs` only if primary is empty |
| Avride | Greenhouse API | Fetch all jobs from `avride`, sort by update time, keep first 50 US matches |
| Serve Robotics | Ashby API | Fetch Ashby board `serverobotics`, sort by `publishedAt`, keep first 50 US matches |
| Gecko Robotics | Ashby API | Fetch Ashby board `gecko-robotics`, sort by `publishedAt`, keep first 50 US matches |
| Skild AI | Greenhouse API | Fetch all jobs from `skildai-careers`, sort by update time, keep first 50 US matches |
| Motorola Solutions / Avigilon | Workday CXS | POST pages with US facet discovery, `limit=20`, `offset=0,20,40` |
| Zebra Technologies | Workday CXS | POST pages with US facet discovery, `limit=20`, `offset=0,20,40` |

---

## Company-by-Company Behavior

### Nuro

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
https://boards-api.greenhouse.io/v1/boards/nuro/jobs?content=true
```

Canonical public URL:

```text
https://nuro.ai/careersitem?gh_jid={id}
```

What it validates:

```text
- API returns HTTP 200
- JSON contains jobs
- At least one job has title and absolute_url
- US location filter prefers United States rows when visible
```

Main script use:

```text
Use as a normal Greenhouse API adapter.
Use absolute_url as the official detail URL.
Greenhouse also exposes first_published and updated_at for date filtering.
```

---

### Kodiak Robotics

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
https://boards-api.greenhouse.io/v1/boards/kodiak/jobs?content=true
```

Canonical public URL:

```text
https://job-boards.greenhouse.io/kodiak/jobs/{id}
```

What it validates:

```text
- API returns HTTP 200
- JSON contains jobs
- At least one job has title and absolute_url
```

Main script use:

```text
Use as a normal Greenhouse API adapter.
Apply authorization/exclusion rules carefully to Defense and export-control wording in detail text.
```

---

### Gatik

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
https://boards-api.greenhouse.io/v1/boards/gatikaiinc/jobs?content=true
```

Canonical public URL:

```text
https://boards.greenhouse.io/gatikaiinc/jobs/{id}?gh_jid={id}
```

Note:

```text
The public careers page at gatik.ai/careers/ may redirect to archive.gatik.ai/careers/.
The Greenhouse API board token gatikaiinc is the reliable source.
```

What it validates:

```text
- API returns HTTP 200
- JSON contains jobs
- At least one job has title and absolute_url
```

---

### May Mobility

Method:

```text
requests
```

Source type:

```text
Greenhouse API
```

Primary endpoint:

```text
https://boards-api.greenhouse.io/v1/boards/maymobility/jobs?content=true
```

Fallback endpoint (only if primary returns zero jobs):

```text
https://boards-api.greenhouse.io/v1/boards/maymobilityjobs/jobs?content=true
```

Canonical public URL:

```text
https://job-boards.greenhouse.io/maymobility/jobs/{id}
```

What it validates:

```text
- Primary Greenhouse board returns parseable jobs
- Falls back to maymobilityjobs only when primary count is zero
```

---

### Avride

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
https://boards-api.greenhouse.io/v1/boards/avride/jobs?content=true
```

Canonical public URL:

```text
https://job-boards.greenhouse.io/avride/jobs/{id}
```

What it validates:

```text
- API returns HTTP 200
- JSON contains jobs
- At least one job has title and absolute_url
```

Important note:

```text
Many Avride rows share the same updated_at timestamp.
Label dates by the exact field exposed; do not infer a new posting date from updated_at alone.
Employer detail text may state U.S. work authorization requirements and no relocation sponsorship.
```

---

### Serve Robotics

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
https://api.ashbyhq.com/posting-api/job-board/serverobotics?includeCompensation=true
```

Canonical public URL:

```text
https://jobs.ashbyhq.com/serverobotics/{id}
```

What it validates:

```text
- API returns HTTP 200
- JSON contains jobs
- At least one job has title and jobUrl
- Records sorted by publishedAt descending
```

---

### Gecko Robotics

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
https://api.ashbyhq.com/posting-api/job-board/gecko-robotics?includeCompensation=true
```

Canonical public URL:

```text
https://jobs.ashbyhq.com/gecko-robotics/{id}
```

What it validates:

```text
- API returns HTTP 200
- JSON contains jobs
- At least one job has title and jobUrl
```

Main script use:

```text
Use as a normal Ashby API adapter.
Apply authorization/exclusion rules to defense, critical-infrastructure, and government wording when present.
```

---

### Skild AI

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
https://boards-api.greenhouse.io/v1/boards/skildai-careers/jobs?content=true
```

Canonical public URL:

```text
https://job-boards.greenhouse.io/skildai-careers/jobs/{id}
```

What it validates:

```text
- API returns HTTP 200
- JSON contains jobs
- At least one job has title and absolute_url
```

Important note:

```text
Many Skild rows have old first_published values with newer updated_at values.
Label dates by the exact field exposed.
```

---

### Motorola Solutions / Avigilon

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
https://motorolasolutions.wd5.myworkdayjobs.com/wday/cxs/motorolasolutions/Careers/jobs
```

Public base:

```text
https://motorolasolutions.wd5.myworkdayjobs.com/Careers
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
- Workday CXS returns HTTP 200
- jobPostings array contains title and externalPath
- Public URL can be built from externalPath
```

Main script use:

```text
Use as a Workday CXS adapter.
Apply authorization/exclusion rules to public-sector, FedRAMP, clearance, and export-control wording.
```

---

### Zebra Technologies

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
https://zebra.wd501.myworkdayjobs.com/wday/cxs/zebra/Zebra_careers/jobs
```

Public base:

```text
https://zebra.wd501.myworkdayjobs.com/Zebra_careers
```

The script uses the same Workday CXS flow as Motorola:

```text
facet discovery
US/location facet IDs when discoverable
limit=20
offset=0,20,40
sortBy=postedOn
```

What it validates:

```text
- Workday CXS returns HTTP 200
- jobPostings array contains title and externalPath
- Public URL can be built from externalPath
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
Company                       | Method   | Status | Count | Sample title                                       | Sample URL / Note
------------------------------+----------+--------+-------+----------------------------------------------------+------------------------------------------------------------------------------------------------
Nuro                          | requests | ok     | 50    | Senior/Staff Software Technical Program Manager, S | https://nuro.ai/careersitem?gh_jid=6114642
Kodiak Robotics               | requests | ok     | 50    | Senior Software Engineer, Behavior Prediction- Pla | https://job-boards.greenhouse.io/kodiak/jobs/4288973009
Gatik                         | requests | ok     | 50    | Verification & Validation (V&V) Engineer – HIL, Si | https://boards.greenhouse.io/gatikaiinc/jobs/4690731006?gh_jid=4690731006
May Mobility                  | requests | ok     | 42    | Machine Learning Engineer II - Autonomous Driving  | https://job-boards.greenhouse.io/maymobility/jobs/8580411002
Avride                        | requests | ok     | 37    | Robot Service Technician – Full Time/Contract      | https://job-boards.greenhouse.io/avride/jobs/4267500009
Serve Robotics                | requests | ok     | 50    | Service Technician                                 | https://jobs.ashbyhq.com/serverobotics/e5e28d52-fea5-4acd-bf54-698af1bcb32d
Gecko Robotics                | requests | ok     | 18    | Compensation and Mobility Partner                  | https://jobs.ashbyhq.com/gecko-robotics/ff91dd57-1adb-41f1-86ed-22bbe458db53
Skild AI                      | requests | ok     | 16    | Technical Recruiting Coordinator                   | https://job-boards.greenhouse.io/skildai-careers/jobs/5162961008
Motorola Solutions / Avigilon | requests | ok     | 50    | Senior Staff Firmware Engineer                     | https://motorolasolutions.wd5.myworkdayjobs.com/Careers/job/Illinois-US-Offsite/Senior-Staff-Fi
Zebra Technologies            | requests | ok     | 50    | Enterprise Systems Analyst, Advisor                | https://zebra.wd501.myworkdayjobs.com/Zebra_careers/job/Lincolnshire-Illinois/PLM-Systems-Analy
```

All ten companies returned `ok`. Counts below 50 reflect fewer US-filtered postings available from the official source, not endpoint failure.

---

## Intended Next Step

After this tester works, the real job-search script should reuse these adapters:

```text
Nuro                          -> requests Greenhouse (nuro)
Kodiak Robotics               -> requests Greenhouse (kodiak)
Gatik                         -> requests Greenhouse (gatikaiinc)
May Mobility                  -> requests Greenhouse (maymobility, maymobilityjobs fallback)
Avride                        -> requests Greenhouse (avride)
Serve Robotics                -> requests Ashby (serverobotics)
Gecko Robotics                -> requests Ashby (gecko-robotics)
Skild AI                      -> requests Greenhouse (skildai-careers)
Motorola Solutions / Avigilon -> requests Workday CXS
Zebra Technologies            -> requests Workday CXS
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
Nuro                          ok
Kodiak Robotics               ok
Gatik                         ok
May Mobility                  ok
Avride                        ok
Serve Robotics                ok
Gecko Robotics                ok
Skild AI                      ok
Motorola Solutions / Avigilon ok
Zebra Technologies            ok
```

If all show `ok`, the source-access layer is ready.
