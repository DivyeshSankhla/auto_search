# Unified Job Source Tester - Part 10

This README explains:

```bash
unified_job_source_tester.py
```

The script is a source-access tester for `job_search_10` companies, ranks 91-95. This is the **final batch** in the ranked company list. It proves whether each official source can return parseable recent/top job records before the real script adds profile filtering, detail enrichment, sponsorship checks, dedupe, and ledger append logic.

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

The script uses Python standard libraries only. No extra packages are required for Part 10.

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

Counts under 50 mean the official source currently has fewer matching postings after the broad US location filter, not that the endpoint failed. GoPro may return only 1–3 active roles and still be `ok`.

---

## Source Types

| Company | Source type | Top-50 method |
|---|---|---|
| Wabtec | SmartRecruiters API | GET `Wabtec` postings, sort by `releasedDate` |
| Resideo | Oracle CE API | GET `recruitingCEJobRequisitions`, site `CX`, sort by `POSTING_DATES_DESC` |
| Brivo | Pinpoint `postings.json` | GET full JSON array, US filter on `location` |
| Wyze | Gem public GraphQL | POST `JobBoardList` with `boardId=wyzecam-com` |
| GoPro | Greenhouse API | Fetch `goprocareers` board, sort by update time |

---

## Company-by-Company Behavior

### Wabtec

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
https://api.smartrecruiters.com/v1/companies/Wabtec/postings?limit=20&offset=0
```

Canonical public URL:

```text
https://jobs.smartrecruiters.com/Wabtec/{id}
```

What it validates:

```text
- API returns HTTP 200
- content array contains name and id
- Public SmartRecruiters URL can be built from id
```

---

### Resideo

Method:

```text
requests
```

Source type:

```text
Oracle Candidate Experience API
```

Endpoint:

```text
GET https://ehtl.fa.us6.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions
finder=findReqs;siteNumber=CX,...;sortBy=POSTING_DATES_DESC
```

Canonical public URL:

```text
https://ehtl.fa.us6.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX/job/{Id}
```

What it validates:

```text
- Oracle CE API returns requisitionList[]
- Title and Id parse correctly
- Public CX job URL builds from Id
```

---

### Brivo

Method:

```text
requests
```

Source type:

```text
Pinpoint postings.json
```

Endpoint:

```text
GET https://careers.brivo.com/postings.json
```

Canonical public URL:

```text
item["url"] -> https://careers.brivo.com/en/postings/{uuid}
```

What it validates:

```text
- JSON returns data[] with title and url
- US filter on location object
- job.requisition_id available for ID evidence
```

Important note:

```text
postings.json does not expose posted date; real script should read schema.org datePosted from detail page.
```

---

### Wyze

Method:

```text
requests
```

Source type:

```text
Gem public GraphQL
```

Endpoint:

```text
POST https://jobs.gem.com/api/public/graphql
operationName: JobBoardList
variables: {"boardId": "wyzecam-com"}
```

Canonical public URL:

```text
https://jobs.gem.com/wyzecam-com/{extId}
```

What it validates:

```text
- GraphQL returns oatsExternalJobPostings.jobPostings[]
- title, extId, locations[].name parse correctly
```

---

### GoPro

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
GET https://boards-api.greenhouse.io/v1/boards/goprocareers/jobs?content=true
```

Canonical public URL:

```text
absolute_url (often https://jobs.gopro.com/jobs/?gh_jid={id})
```

What it validates:

```text
- Greenhouse API returns jobs[] even when count is very small
- count > 0 is sufficient for ok status
```

Important note:

```text
GoPro currently has very few active US roles; count=1 is expected and valid.
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
Company | Method   | Status | Count | Sample title                                       | Sample URL / Note
--------+----------+--------+-------+----------------------------------------------------+------------------------------------------------------------------------------------
Wabtec  | requests | ok     | 36    | Lead Systems Engineer, MCA – Fleet Innovation & Tr | https://jobs.smartrecruiters.com/Wabtec/3743990013733336
Resideo | requests | ok     | 24    | Senior Tax Analyst                                 | https://ehtl.fa.us6.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX/job/18634
Brivo   | requests | ok     | 13    | Sales Engineer, Midwest                            | https://careers.brivo.com/en/postings/5ae816fb-e25e-4487-a440-d4aca706ea54
Wyze    | requests | ok     | 9     | AI Scientist Internship                            | https://jobs.gem.com/wyzecam-com/am9icG9zdDraGA2pjbmRtxZpA_ZHVASR
GoPro   | requests | ok     | 1     | Senior Engineer, Process                           | https://jobs.gopro.com/jobs/?gh_jid=7930572&gh_jid=7930572
```

All five companies returned `ok`. Counts below 50 reflect fewer US-filtered or discoverable postings from the official source, not endpoint failure.

---

## Intended Next Step

After this tester works, the real job-search script should reuse these adapters:

```text
Wabtec  -> requests SmartRecruiters (Wabtec)
Resideo -> requests Oracle CE (ehtl.fa.us6, site CX)
Brivo   -> requests Pinpoint postings.json + detail schema.org
Wyze    -> requests Gem GraphQL JobBoardList + ExternalJobPostingQuery
GoPro   -> requests Greenhouse (goprocareers)
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
Wabtec  ok
Resideo ok
Brivo   ok
Wyze    ok
GoPro   ok (count may be 1–3)
```

All five targets are met.
