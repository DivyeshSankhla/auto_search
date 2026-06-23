# Unified Job Source Tester

This README explains the file:

```bash
unified_job_source_tester.py
```

The script is a simple test utility for checking whether each company job source can be accessed and parsed using the same method intended for the real job-search automation.

It does **not** filter jobs for relevance, append to `jobs_found.md`, score jobs, or apply resume matching. It only checks whether each company source returns parseable job records.

---

## Purpose

The script verifies that the job-search automation can pull job records from official company sources.

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

## Install Requirements

The script uses Python standard libraries for most companies.

Two companies need extra packages:

```bash
pip install playwright curl_cffi
playwright install chromium
```

Why these are needed:

```text
Meta   -> needs Playwright because the page is JavaScript-rendered
Tesla  -> needs curl_cffi because normal Python requests get blocked
```

---

## Run

From the folder where the script exists:

```bash
python3 unified_job_source_tester.py
```

Expected output format:

```text
Company   | Method     | Status | Count | Sample title | Sample URL / Note
----------+------------+--------+-------+--------------+------------------
NVIDIA    | requests   | ok     | 50    | ...          | ...
Apple     | requests   | ok     | 21    | ...          | ...
Google    | requests   | ok     | ...   |              | ...
Microsoft | requests   | ok     | 50    | ...          | ...
Meta      | playwright | ok     | ...   | ...          | ...
OpenAI    | requests   | ok     | ...   | ...          | ...
Amazon    | requests   | ok     | 50    | ...          | ...
Waymo     | requests   | ok     | ...   | ...          | ...
Qualcomm  | requests   | ok     | 50    | ...          | ...
Tesla     | curl_cffi  | ok     | ...   | ...          | ...
```

---

## Status Meanings

| Status | Meaning |
|---|---|
| `ok` | Source returned parseable job records. |
| `blocked` | Source returned HTTP 403 or access was denied. |
| `failed` | Request failed because of timeout, network error, or missing response. |
| `parser_failed` | Page loaded, but parser did not find job records. |
| `missing_playwright` | Playwright is not installed, so Meta cannot be tested. |
| `missing_curl_cffi` | curl_cffi is not installed, so Tesla cannot be tested. |
| `http_<code>` | Source returned a non-200 HTTP response. |

---

## Company-by-Company Behavior

### NVIDIA

Method:

```text
requests
```

Source type:

```text
PCS API
```

Endpoint pattern:

```text
https://jobs.nvidia.com/api/pcsx/search
```

The script queries NVIDIA with:

```text
domain=nvidia.com
location=United States
start=0,10,20,30,40
sort_by=timestamp
```

What it validates:

```text
- API returns HTTP 200
- JSON contains data.positions or positions
- At least one position exists
- First job has a title and public URL
```

Main script use:

```text
Use as a normal API adapter.
Fetch recent/top results first, then apply relevance filtering.
```

---

### Apple

Method:

```text
requests
```

Source type:

```text
static HTML
```

Endpoint pattern:

```text
https://jobs.apple.com/en-us/search?sort=newest&location=united-states-USA&page=1
```

The script parses Apple job detail links from HTML:

```text
/en-us/details/...
```

What it validates:

```text
- Search page returns HTTP 200
- HTML contains Apple job detail URLs
- At least one official jobs.apple.com detail URL is found
```

Important note:

Apple often returns retail or part-time jobs such as:

```text
US Specialist Seasonal Part Time
```

That is okay for this tester. The real job-search script should reject irrelevant jobs later using filters such as:

```text
weak_role_match
part-time / non-target employment
location mismatch
```

Main script use:

```text
Use as a static HTML adapter.
Fetch official Apple jobs first, then filter by title and profile match.
```

---

### Google

Method:

```text
requests
```

Source type:

```text
static HTML / embedded JavaScript job ID parser
```

Endpoint pattern:

```text
https://www.google.com/about/careers/applications/jobs/results?location=United%20States&sort_by=date&page=1
```

Google may not expose clean normal links in the HTML. The script handles this by parsing job IDs from embedded page text and JavaScript blobs.

What it validates:

```text
- Page returns HTTP 200
- Script finds numeric Google Careers job IDs
- It builds official Google Careers detail URLs
```

Generated detail URL format:

```text
https://www.google.com/about/careers/applications/jobs/results/{job_id}
```

Main script use:

```text
Use as a static HTML / ID parser adapter.
After getting job IDs, fetch detail pages if needed.
```

---

### Microsoft

Method:

```text
requests
```

Source type:

```text
PCS API
```

Endpoint pattern:

```text
https://apply.careers.microsoft.com/api/pcsx/search
```

The script queries Microsoft with:

```text
domain=microsoft.com
location=United States
start=0,10,20,30,40
sort_by=timestamp
```

What it validates:

```text
- API returns HTTP 200
- JSON contains data.positions or positions
- At least one position exists
- First job has title and URL
```

Main script use:

```text
Use as a normal API adapter.
Expect broad roles, then filter by embedded/Linux/systems relevance.
```

---

### Meta

Method:

```text
playwright
```

Source type:

```text
rendered HTML
```

Page:

```text
https://www.metacareers.com/jobsearch/?page=1
```

Why Playwright is used:

Meta job cards are rendered by JavaScript. Static requests do not reliably expose the job cards.

The script opens the Meta careers page in headless Chromium, waits for page load, scrolls, then parses job links.

Meta detail URL pattern:

```text
/profile/job_details/{job_id}
```

Example final URL format:

```text
https://www.metacareers.com/profile/job_details/{job_id}
```

What it validates:

```text
- Playwright can open the page
- Rendered HTML contains /profile/job_details/ links
- Job title is parsed from h3 inside the job link
- At least one Meta job card is found
```

Main script use:

```text
Use Playwright for Meta search/listing pages.
Parse /profile/job_details/{job_id}.
Do not use the old /jobs/ pattern.
```

---

### OpenAI

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
https://api.ashbyhq.com/posting-api/job-board/openai
```

What it validates:

```text
- API returns HTTP 200
- JSON contains jobs
- At least one job exists
- First job has title and jobUrl
```

Main script use:

```text
Use as a normal Ashby API adapter.
Sort/filter locally by role relevance and recency fields if available.
```

---

### Amazon

Method:

```text
requests
```

Source type:

```text
Amazon jobs JSON
```

Endpoint pattern:

```text
https://www.amazon.jobs/en/search.json?country=USA&sort=recent&result_limit=50
```

What it validates:

```text
- JSON endpoint returns HTTP 200
- Response contains jobs
- At least one job exists
- Job path can be converted into an official amazon.jobs URL
```

Generated URL format:

```text
https://www.amazon.jobs/en/jobs/{job_id}/...
```

Main script use:

```text
Use as a normal JSON adapter.
Expect broad roles, then filter aggressively by embedded/systems relevance.
```

---

### Waymo

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
https://boards-api.greenhouse.io/v1/boards/waymo/jobs?content=true
```

What it validates:

```text
- API returns HTTP 200
- JSON contains jobs
- At least one job exists
- Job has title and absolute_url
```

Main script use:

```text
Use as a normal Greenhouse API adapter.
Use absolute_url as the official apply/detail URL.
```

---

### Qualcomm

Method:

```text
requests
```

Source type:

```text
PCS API
```

Endpoint pattern:

```text
https://careers.qualcomm.com/api/pcsx/search
```

The script queries Qualcomm with:

```text
domain=qualcomm.com
location=United States
start=0,10,20,30,40
sort_by=timestamp
```

What it validates:

```text
- API returns HTTP 200
- JSON contains data.positions or positions
- At least one position exists
- First job has title and URL
```

Main script use:

```text
Use as a normal API adapter.
Likely strong source for embedded, firmware, camera, wireless, and on-device software roles.
```

---

### Tesla

Method:

```text
curl_cffi
```

Source type:

```text
official Tesla detail URL verification
```

Why Tesla is different:

Tesla search page returns 403 / Access Denied from the local Python environment. Normal `urllib`, `requests`, and Playwright can fail.

Working approach:

```text
Do not use Tesla search page.
Use known/discovered official Tesla detail URLs.
Verify each URL using curl_cffi with Chrome impersonation.
```

Official Tesla detail URL pattern:

```text
https://www.tesla.com/careers/search/job/{job-slug}-{req_id}
```

Example:

```text
https://www.tesla.com/careers/search/job/firmware-engineer-silicon-tesla-ai-263752
```

The script verifies Tesla jobs by checking:

```text
- HTTP 200 from curl_cffi
- URL is an official tesla.com careers detail URL
- Title can be parsed from the page or URL slug
- Req ID can be parsed from page text or URL suffix
```

Tesla Req ID fallback:

```text
firmware-engineer-silicon-tesla-ai-263752
Req ID = 263752
```

Current Tesla seed URLs in the tester:

```text
firmware-engineer-silicon-tesla-ai-263752
embedded-firmware-engineer-battery-management-system-254793
embedded-software-engineer-reliability-test--260562
integration-engineer-drive-inverter-firmware-vehicle-software-239741
sr-embedded-firmware-development-engineer--251119
```

Main script use:

```text
Use Tesla as a detail-url verifier, not as a search adapter.
Tesla needs a discovery/seed list of official detail URLs.
Verify each detail URL with curl_cffi before scoring/filtering.
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

## How to Interpret Results

Good result:

```text
Status = ok
Count > 0
```

Example:

```text
Tesla | curl_cffi | ok | 5 | Firmware Engineer Silicon Tesla Ai | https://www.tesla.com/...
```

Bad result:

```text
Status = missing_playwright
```

Fix:

```bash
pip install playwright
playwright install chromium
```

Bad result:

```text
Status = missing_curl_cffi
```

Fix:

```bash
pip install curl_cffi
```

Bad result:

```text
Status = parser_failed
```

Meaning:

```text
The page loaded, but the parser did not find job records.
The source may still be accessible, but parsing logic needs to be updated.
```

Bad result:

```text
Status = blocked
```

Meaning:

```text
The source denied access from the current environment.
Use a different source method or skip that company.
```

---

## Intended Next Step

After this tester works, the real job-search script should reuse these adapters:

```text
NVIDIA      -> requests PCS
Apple       -> requests static HTML
Google      -> requests static HTML / ID parser
Microsoft   -> requests PCS
Meta        -> Playwright rendered HTML
OpenAI      -> requests Ashby
Amazon      -> requests JSON
Waymo       -> requests Greenhouse
Qualcomm    -> requests PCS
Tesla       -> curl_cffi detail URL verifier
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
NVIDIA      ok
Apple       ok
Google      ok
Microsoft   ok
Meta        ok
OpenAI      ok
Amazon      ok
Waymo       ok
Qualcomm    ok
Tesla       ok
```

If all show `ok`, the source-access layer is ready.
