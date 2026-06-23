# Unified Job Source Tester - Part 6

This README explains:

```bash
unified_job_source_tester.py
```

The script is a source-access tester for `job_search_6` companies, ranks 51-60. It proves whether each official source can return parseable recent/top job records before the real script adds profile filtering, detail enrichment, sponsorship checks, dedupe, and ledger append logic.

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
| ok | The official source returned parseable jobs and at least one usable sample URL |
| warn | The source responded, but the result is thin or missing expected fields |
| error | The source could not be reached or parsed |

Counts under 50 mean the official source currently has fewer matching postings after the broad location filter, not that the endpoint failed.

---

## Source Types

| Company | Source type | Top-50 method |
|---|---|---|
| Torc Robotics | Greenhouse API | Fetch all jobs, sort by update time, keep first 50 US/Americas matches |
| Applied Intuition | Ashby API | Fetch Ashby board, sort by `publishedAt`, keep first 50 US matches |
| Aurora | Greenhouse API | Fetch all jobs from `aurorainnovation`, sort by update time, keep first 50 US matches |
| Skydio | Ashby API | Fetch Ashby board, sort by `publishedAt`, keep first 50 US matches |
| Boston Dynamics | Workday CXS | POST pages with `limit=20`, `offset=0,20,40` |
| Symbotic | Workday CXS | POST pages with `limit=20`, `offset=0,20,40` |
| Zipline | Greenhouse API | Fetch all jobs from `flyzipline`, sort by update time, keep first 50 US/Americas matches |
| Figure AI | Greenhouse API | Fetch all jobs, sort by update time, keep first 50 US matches |
| Agility Robotics | Greenhouse API | Fetch all jobs, sort by update time, keep first 50 US matches |
| Waabi | Lever API | GET `/v0/postings/waabi` with `limit=50` |

---

## Company-by-Company Behavior

### Torc Robotics

Source type:

```text
Greenhouse API
```

Endpoint:

```text
https://boards-api.greenhouse.io/v1/boards/torcrobotics/jobs?content=true
```

The script fetches all records, sorts by Greenhouse recency fields, and keeps the first 50 US/Americas matches.

---

### Applied Intuition

Source type:

```text
Ashby API
```

Endpoint:

```text
https://api.ashbyhq.com/posting-api/job-board/applied
```

The script fetches all Ashby records, sorts by:

```text
publishedAt descending
```

Then it keeps up to 50 US records using:

```text
location
address.postalAddress.addressRegion
address.postalAddress.addressCountry
secondaryLocations
```

---

### Aurora

Source type:

```text
Greenhouse API
```

Endpoint:

```text
https://boards-api.greenhouse.io/v1/boards/aurorainnovation/jobs?content=true
```

The script fetches all records, sorts by Greenhouse recency fields, and keeps the first 50 US matches.

---

### Skydio

Source type:

```text
Ashby API
```

Endpoint:

```text
https://api.ashbyhq.com/posting-api/job-board/skydio
```

The script fetches all Ashby records, sorts by `publishedAt`, and keeps up to 50 US records.

---

### Boston Dynamics

Source type:

```text
Workday CXS
```

Endpoint:

```text
https://bostondynamics.wd1.myworkdayjobs.com/wday/cxs/bostondynamics/Boston_Dynamics/jobs
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

---

### Symbotic

Source type:

```text
Workday CXS
```

Endpoint:

```text
https://symbotic.wd504.myworkdayjobs.com/wday/cxs/symbotic/Symbotic/jobs
```

The script uses the same Workday CXS flow:

```text
facet discovery
US/location facet IDs when discoverable
limit=20
offset=0,20,40
sortBy=postedOn
```

---

### Zipline

Source type:

```text
Greenhouse API
```

Endpoint:

```text
https://boards-api.greenhouse.io/v1/boards/flyzipline/jobs?content=true
```

The public URLs returned by Greenhouse point back to Zipline's official careers page:

```text
https://www.zipline.com/careers?gh_jid=<id>#open-roles
```

---

### Figure AI

Source type:

```text
Greenhouse API
```

Endpoint:

```text
https://boards-api.greenhouse.io/v1/boards/figureai/jobs?content=true
```

The script fetches all records, sorts by Greenhouse recency fields, and keeps the first 50 US matches.

---

### Agility Robotics

Source type:

```text
Greenhouse API
```

Endpoint:

```text
https://boards-api.greenhouse.io/v1/boards/agilityrobotics/jobs?content=true
```

The public URLs returned by Greenhouse point back to Agility's official careers page:

```text
https://www.agilityrobotics.com/about/job-post?gh_jid=<id>
```

---

### Waabi

Source type:

```text
Lever API
```

Endpoint:

```text
https://api.lever.co/v0/postings/waabi
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

and prefers records whose `country` or `categories.location` match US/North America/Americas text.
