# Final Architecture

Create one script only inside `job_search_1`:

```text
job_search_1/jobsearch_part1.py
```

It reuses the working source methods from:

```text
job_source_endpoint_testing/part1/unified_job_source_tester.py
```

No other folder edits.

## Command Interface

```bash
python3 jobsearch_part1.py
```

Dry run. Search, normalize, filter, score, dedupe, print results.

```bash
python3 jobsearch_part1.py --append
```

Re-read ledger, dedupe again, append new jobs.

```bash
python3 jobsearch_part1.py --limit 50 --days 3
```

Configurable source limit and freshness window.

```bash
python3 jobsearch_part1.py --self-test
```

Run internal parser/filter/dedupe tests.

## Inputs

Reads:

```text
jobsearchdocs/job_search_preferences.json
jobsearchdocs/job_search_profile.json
jobsearchdocs/company_search_guide_part_01.md
jobsearchdocs/jobs_found.md
```

## Source Health Check

At startup, each adapter returns:

```text
ok
blocked
failed
schema_changed
parser_failed
missing_playwright
missing_curl_cffi
requires_browser
```

Health check is lightweight and based on the proven tester behavior.

The script continues even if one company fails.

## Working Adapters

| Company | Adapter | Source |
|---|---|---|
| NVIDIA | `PCSAdapter` | `https://jobs.nvidia.com/api/pcsx/search` |
| Apple | `AppleHtmlAdapter` | `https://jobs.apple.com/en-us/search?sort=newest&location=united-states-USA&page={page}` |
| Google | `GoogleHtmlIdAdapter` | `https://www.google.com/about/careers/applications/jobs/results?location=United%20States&sort_by=date&page={page}` |
| Microsoft | `PCSAdapter` | `https://apply.careers.microsoft.com/api/pcsx/search` |
| Meta | `MetaPlaywrightAdapter` | `https://www.metacareers.com/jobsearch/?page={page}` |
| OpenAI | `AshbyAdapter` | `https://api.ashbyhq.com/posting-api/job-board/openai` |
| Amazon | `AmazonJsonAdapter` | `https://www.amazon.jobs/en/search.json?country=USA&sort=recent&result_limit={limit}` |
| Waymo | `GreenhouseAdapter` | `https://boards-api.greenhouse.io/v1/boards/waymo/jobs?content=true` |
| Qualcomm | `PCSAdapter` | `https://careers.qualcomm.com/api/pcsx/search` |
| Tesla | `TeslaCurlCffiVerifier` | seeded official Tesla detail URLs |

## Fetch Strategy

Do not fetch top 50 per keyword.

Fetch most recent/top official results once per company, with location early where supported.

Then use ranked terms only for filtering/scoring.

## Per Company Fetch Details

`NVIDIA / Microsoft / Qualcomm`

Use PCS API:

```text
domain={company_domain}
location=United States
sort_by=timestamp
start=0,10,20,30,40
```

Fetch until `--limit` or no more positions.

`Apple`

Use static HTML:

```text
https://jobs.apple.com/en-us/search?sort=newest&location=united-states-USA&page=1
```

Parse official links:

```text
/en-us/details/...
```

Paginate until `--limit` or no new links.

`Google`

Use static HTML / embedded JS ID parser:

```text
https://www.google.com/about/careers/applications/jobs/results?location=United%20States&sort_by=date&page=1
```

Extract numeric job IDs and build:

```text
https://www.google.com/about/careers/applications/jobs/results/{job_id}
```

Paginate until `--limit` or no new IDs.

`Meta`

Use Playwright:

```text
https://www.metacareers.com/jobsearch/?page=1
```

Wait for render, scroll, parse:

```text
/profile/job_details/{job_id}
```

Official detail URL:

```text
https://www.metacareers.com/profile/job_details/{job_id}
```

`OpenAI`

Use Ashby API:

```text
https://api.ashbyhq.com/posting-api/job-board/openai
```

Sort/filter locally by official fields like `publishedAt`.

`Amazon`

Use JSON endpoint:

```text
https://www.amazon.jobs/en/search.json?country=USA&sort=recent&result_limit={limit}
```

Build official URL from `job_path`.

`Waymo`

Use Greenhouse API:

```text
https://boards-api.greenhouse.io/v1/boards/waymo/jobs?content=true
```

Use `absolute_url`.

Sort/filter locally by `first_published` / `updated_at`.

`Tesla`

Use `curl_cffi` with Chrome impersonation.

Do not use Tesla search page as source.

Use seeded/discovered official detail URLs:

```text
https://www.tesla.com/careers/search/job/{job-slug}-{req_id}
```

Verify:

```text
HTTP 200
official tesla.com careers URL
title parsed from h1 or slug
req_id parsed from page or URL
```

Current seed URLs come from the tester.

## Request Layer

Shared request policy:

```text
timeout: 20s
delay: 0.1-0.5s
retries: 2-3
backoff on: 429, 403, 5xx, timeout
user-agent: Chrome-like
```

`curl_cffi` only for Tesla.

Playwright only for Meta.

## Run Cache

Memory-only per run:

```python
search_cache[url] = raw_response
detail_cache[job_key] = detail_response
normalized_cache[job_key] = Job
```

Avoid fetching same detail twice.

## Normalized Job

Every adapter emits:

```python
Job(
    company,
    title,
    location,
    work_mode,
    posted_date,
    date_status,
    job_id,
    requisition_id,
    url,
    description,
    source_method,
    source_status,
    concerns,
    reject_reasons,
    score,
)
```

## Date Status

```text
confirmed_recent
old
posted_hidden_top_results
```

Rules:

- posted date within `--days`: `confirmed_recent`
- posted date older than `--days`: reject as `old`
- no reliable posted date: `posted_hidden_top_results`

## Filtering

Hard reject:

```text
non_official_source
missing_url
location_mismatch
old_posting
internship
part_time
citizenship_required
clearance_required
no_sponsorship
weak_role_match
duplicate_ledger
```

Do not reject unclear sponsorship.

Add concern:

```text
Concern: sponsorship not visible
```

## Ranked Role Terms

Used for filter/score:

```text
firmware
embedded linux
kernel
device driver
systems software
platform software
networking
connectivity
performance
robotics
operating systems
distributed systems
```

Company guide priority terms are added per company.

## Scoring

Score uses:

```text
title relevance
ranked term hits
profile skill overlap
company guide priority terms
description match
systems/low-level ownership language
location fit
confirmed recency boost
sponsorship concern penalty
```

## Ledger Dedupe

Read `jobs_found.md`.

Dedupe by:

```text
official URL
job ID
requisition ID
normalized company + title + location
```

Before `--append`, re-read `jobs_found.md` and dedupe again.

## Dry Run Output

Print:

```text
source health table
new confirmed_recent jobs
posted_hidden_top_results jobs
concerns
duplicates skipped
compact rejection counts
failed/incomplete companies
```

Example:

```text
Rejected:
- weak_role_match: 42
- old_posting: 18
- location_mismatch: 9
- duplicate_ledger: 6
- no_sponsorship: 3
```

## Append Output

Append timestamped section to:

```text
jobsearchdocs/jobs_found.md
```

Format marks each job clearly:

```text
Status: confirmed_recent
```

or

```text
Status: posted_hidden_top_results
Concern: sponsorship not visible
```

## Self Tests

`--self-test` covers:

```text
PCS parser
Apple link parser
Google ID parser
Meta link parser
Amazon parser
Ashby parser
Greenhouse parser
Tesla URL parser
date classification
sponsorship rejection
citizenship/clearance rejection
ledger dedupe
score sanity
```

This is the implementation source of truth for `jobsearch_part1.py`.

