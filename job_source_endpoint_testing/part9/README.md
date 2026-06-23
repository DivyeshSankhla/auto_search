# Unified Job Source Tester - Part 9

This README explains:

```bash
unified_job_source_tester.py
```

The script is a source-access tester for `job_search_9` companies, ranks 81-90. It proves whether each official source can return parseable recent/top job records before the real script adds profile filtering, detail enrichment, sponsorship checks, dedupe, and ledger append logic.

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

The script uses Python standard libraries only. No extra packages are required for Part 9.

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
| Infineon | Eightfold PCS API | GET `/api/pcsx/search` with `Referer`, paginate `start` by 10 |
| STMicroelectronics | Eightfold HTML embed | Parse embedded `positions` JSON from careers page (PCS API may be disabled) |
| Microchip | SmartRecruiters API | GET `Microchip` postings, sort by `releasedDate` |
| Lattice Semiconductor | iCIMS HTML | Parse `iCIMS_JobCardItem` links from search page |
| Synaptics | Custom careers HTML | GET US country search page; Cloudflare may block CLI |
| Teledyne FLIR | Workday CXS | POST with US facet discovery, `limit=20`, `offset=0,20,40` |
| Hanwha Vision | ADP Workforce Now API | GET job-requisitions with ADP headers + `timeStamp` |
| Alarm.com | Greenhouse API | Fetch `alarmcom` board, sort by update time, US filter |
| SimpliSafe | Greenhouse API | Fetch `simplisafe` board, sort by update time, US filter |
| iRobot | Workday CXS | POST with US facet discovery, `limit=20`, `offset=0,20,40` |

---

## Company-by-Company Behavior

### Infineon

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
GET https://jobs.infineon.com/api/pcsx/search?domain=infineon.com&location=United States&start={offset}&num=10
Referer: https://jobs.infineon.com/careers
```

Canonical public URL:

```text
https://jobs.infineon.com/careers/job/{id}
```

What it validates:

```text
- PCS API returns HTTP 200 with data.positions[]
- name, id, positionUrl parse correctly
- Public URL resolves from positionUrl or /careers/job/{id}
```

---

### STMicroelectronics

Method:

```text
requests
```

Source type:

```text
Eightfold HTML embed (PCS API fallback)
```

Endpoint:

```text
Primary: GET https://stmicroelectronics.eightfold.ai/api/pcsx/search?domain=stmicroelectronics.com&location=United States
Fallback: GET https://stmicroelectronics.eightfold.ai/careers?domain=stmicroelectronics.com&location=United States&start=0
```

Canonical public URL:

```text
https://stmicroelectronics.eightfold.ai/careers/job/{id}
```

What it validates:

```text
- Embedded positions JSON parses from careers HTML when PCS API is disabled
- US rows filter on locations[]
- canonicalPositionUrl or id builds official detail URL
```

Important note:

```text
Direct /api/pcsx/search may return PCSX is not enabled; the HTML careers page still embeds positions data.
Current live count reflects US-filtered embedded rows on the first page (10), not total global inventory.
```

---

### Microchip

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
https://api.smartrecruiters.com/v1/companies/Microchip/postings?limit=20&offset=0
```

Canonical public URL:

```text
https://jobs.smartrecruiters.com/Microchip/{id}
```

What it validates:

```text
- API returns HTTP 200
- content array contains name and id
- Public SmartRecruiters URL can be built from id
```

---

### Lattice Semiconductor

Method:

```text
requests
```

Source type:

```text
iCIMS HTML search page
```

Endpoint:

```text
GET https://careers-latticesemi.icims.com/jobs/search?ss=1&in_iframe=1
```

Canonical public URL:

```text
https://careers-latticesemi.icims.com/jobs/{id}/{slug}/job
```

What it validates:

```text
- Search page returns iCIMS job cards with title and detail link
- ?in_iframe=1 is stripped from canonical URL
```

---

### Synaptics

Method:

```text
requests
```

Source type:

```text
Custom careers HTML
```

Endpoint:

```text
Primary: https://careers.synaptics.com/search/jobs/in/country/united-states
Fallback: https://careers.synaptics.com/search/engineering/jobs
```

Canonical public URL:

```text
https://careers.synaptics.com/jobs/{jobId}-{slug}
```

What it validates:

```text
- Careers search page returns /jobs/{id}-{slug} links when accessible
```

Important note:

```text
Cloudflare blocks unauthenticated CLI requests with HTTP 403.
Status blocked is expected from this tester; the real script may need browser session or alternate official source.
```

---

### Teledyne FLIR

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
POST https://flir.wd1.myworkdayjobs.com/wday/cxs/flir/flircareers/jobs
```

Canonical public URL:

```text
https://flir.wd1.myworkdayjobs.com/flircareers{externalPath}
```

What it validates:

```text
- Workday facet discovery finds US location facet
- jobPostings[] returns title and externalPath
```

---

### Hanwha Vision

Method:

```text
requests
```

Source type:

```text
ADP Workforce Now API
```

Endpoint:

```text
GET https://workforcenow.adp.com/mascsr/default/careercenter/public/events/staffing/v1/job-requisitions
  ?cid=787e0fab-b518-411a-9af8-dd168e00705a&client=samsop&ccId=19000101_000001
  &lang=en_US&locale=en_US&$skip=0&$top=50&timeStamp={ms}&userQuery=
```

Required headers:

```text
Accept-Language: en_US
locale: en_US
X-Requested-With: XMLHttpRequest
x-forwarded-host: workforcenow.adp.com
```

What it validates:

```text
- jobRequisitions[] returns requisitionTitle and itemID
- US filter on requisitionLocations address fields
```

Important note:

```text
Per-job public ADP URLs can be unstable; the tester records itemID-backed API URL as sample evidence.
```

---

### Alarm.com

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
GET https://boards-api.greenhouse.io/v1/boards/alarmcom/jobs?content=true
```

Canonical public URL:

```text
absolute_url from Greenhouse response
```

---

### SimpliSafe

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
GET https://boards-api.greenhouse.io/v1/boards/simplisafe/jobs?content=true
```

Canonical public URL:

```text
absolute_url from Greenhouse response
```

---

### iRobot

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
POST https://irobot.wd503.myworkdayjobs.com/wday/cxs/irobot/iRobot/jobs
```

Canonical public URL:

```text
https://irobot.wd503.myworkdayjobs.com/iRobot{externalPath}
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
Company               | Method   | Status  | Count | Sample title                                       | Sample URL / Note
----------------------+----------+---------+-------+----------------------------------------------------+------------------------------------------------------------------------------------------------
Infineon              | requests | ok      | 50    | Senior Test Engineering - Advantest 93K            | https://jobs.infineon.com/careers/job/563808970485271
STMicroelectronics    | requests | ok      | 10    | Segment Marketing & System Architecture CECP - Vic | https://stmicroelectronics.eightfold.ai/careers/job/563637172462772
Microchip             | requests | ok      | 5     | Senior Engineer I - Systems                        | https://jobs.smartrecruiters.com/Microchip/744000130897639
Lattice Semiconductor | requests | ok      | 50    | SW Technical Publications Intern                   | https://careers-latticesemi.icims.com/jobs/3692/sw-technical-publications-intern/job
Synaptics             | requests | blocked | 0     |                                                    |
Teledyne FLIR         | requests | ok      | 50    | Clean Room Manufacturing Technician - 3rd Shift    | https://flir.wd1.myworkdayjobs.com/flircareers/job/US---Goleta-CA/Clean-Room-Manufacturing-Tech
Hanwha Vision         | requests | ok      | 13    | Supply Chain Management Data Analyst               | https://workforcenow.adp.com/mascsr/default/careercenter/public/events/staffing/v1/job-requisit
Alarm.com             | requests | ok      | 50    | Technical Support Representative                   | https://job-boards.greenhouse.io/alarmcom/jobs/8564854002
SimpliSafe            | requests | ok      | 32    | Senior RF Test & Validation Engineer               | https://job-boards.greenhouse.io/simplisafe/jobs/7261536
iRobot                | requests | ok      | 7     | Principal Robotics Engineer - Innovation (Electric | https://irobot.wd503.myworkdayjobs.com/iRobot/job/US-MA-Bedford/Principal-Robotics-Engineer---I
```

Nine of ten companies returned `ok`. Synaptics returned `blocked` because Cloudflare returns HTTP 403 to CLI requests. Counts below 50 reflect fewer US-filtered or discoverable postings from the official source, not endpoint failure.

---

## Intended Next Step

After this tester works, the real job-search script should reuse these adapters:

```text
Infineon              -> requests Eightfold PCS (jobs.infineon.com)
STMicroelectronics    -> requests Eightfold HTML embed + optional PCS retry
Microchip             -> requests SmartRecruiters (Microchip)
Lattice Semiconductor -> requests iCIMS HTML search
Synaptics             -> browser/session-backed careers HTML or alternate official path
Teledyne FLIR         -> requests Workday CXS
Hanwha Vision         -> requests ADP Workforce Now API
Alarm.com             -> requests Greenhouse (alarmcom)
SimpliSafe            -> requests Greenhouse (simplisafe)
iRobot                -> requests Workday CXS
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
Infineon              ok
STMicroelectronics    ok
Microchip             ok
Lattice Semiconductor ok
Synaptics             blocked (documented Cloudflare limitation)
Teledyne FLIR         ok
Hanwha Vision         ok
Alarm.com             ok
SimpliSafe            ok
iRobot                ok
```

Nine parseable sources are sufficient to proceed; Synaptics needs a browser-backed path in the real script.
