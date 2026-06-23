# Unified Job Site Source Tester

This README explains:

```bash
unified_job_site_tester.py
```

The script is a **source-access reference tester** for general US job search platforms (LinkedIn, Indeed, Dice, etc.). It proves how each site can be searched and how a sample job description can be read — the same contract a future `job_search_general.py` will reuse.

It does **not** run profile keyword scoring, sponsorship filtering, dedupe, or ledger append.

---

## Purpose

For each job site, the tester verifies:

```text
Site | Method | Status | Count | JD | JD chars | Sample title | Sample URL
```

A site is considered working when:

```text
Status = ok
Count > 0
JD = ok (sample JD chars >= 200 when detail is reachable)
Sample URL is on that platform
```

Technical details for each site live in [`site_search_guide.md`](site_search_guide.md).

---

## Core Rule

```text
platform search first
keyword + location + date sort when supported
paginate to JOB_SOURCE_TEST_LIMIT (default 50)
open one sample posting and read JD text
profile filtering later in job_search_general.py
```

Default inputs:

```bash
JOB_SITE_TEST_QUERY="firmware engineer"
JOB_SITE_TEST_LOCATION="United States"
JOB_SOURCE_TEST_LIMIT=50
JOB_SITE_HEADED=0   # set to 1 for headed Chromium on Wellfound/Monster
```

---

## Install Requirements

Most sites need browser-like HTTP:

```bash
pip install curl_cffi
```

Optional for JS-heavy sites (Monster, Otta, LinkedIn session):

```bash
pip install playwright
playwright install chromium
```

Stdlib-only sites: RemoteOK, Remotive, We Work Remotely RSS, Hacker News.

---

## Run

From this folder:

```bash
python3 unified_job_site_tester.py
```

---

## Status Meanings

| Status | Meaning |
|---|---|
| `ok` | List search returned parseable job rows. |
| `blocked` | HTTP 403 or access denied. |
| `failed` | Network/request error. |
| `parser_failed` | Page loaded but no job rows parsed. |
| `http_<code>` | Non-200 HTTP response. |

JD column uses the same status vocabulary for the sample detail fetch.

---

## Sites (main order)

| # | Site | Adapter |
|---:|---|---|
| 1 | LinkedIn Jobs | `test_linkedin()` |
| 2 | Indeed | `test_indeed()` |
| 3 | Glassdoor | `test_glassdoor()` |
| 4 | ZipRecruiter | `test_ziprecruiter()` |
| 5 | Dice | `test_dice()` |
| 6 | Wellfound | `test_wellfound()` |
| 7 | Built In | `test_builtin()` |
| 8 | RemoteOK | `test_remoteok()` |
| 9 | We Work Remotely | `test_weworkremotely()` |
| 10 | Remotive | `test_remotive()` |
| 11 | SimplyHired | `test_simplyhired()` |
| 12 | Monster | `test_monster()` |
| 13 | Otta | `test_otto()` |
| 14 | Hacker News Who's Hiring | `test_hn_whos_hiring()` |

---

## Site-by-Site Summary

### LinkedIn Jobs

Method: `curl_cffi`. Search: `keywords`, `location`, `sortBy=DD`. Parses view URLs + titles. JD from detail page HTML.

### Indeed

Method: `curl_cffi`. Search: `q`, `l`, `sort=date`, `start=0,10,...`. Parses `data-jk` + title. JD from `#jobDescriptionText`.

### Glassdoor

Method: `curl_cffi`. Search: `keyword`, `locT=N`, `locId=1`. Parses embedded JSON jobTitleText/jobLink. JD from listing page.

### ZipRecruiter

Method: `curl_cffi`. Search: `search`, `location`. Parses embedded JSON `name` + `url`. JD from job page.

### Dice

Method: `curl_cffi`. Search: `q`, `location`, `page`, `pageSize=20`. Parses `job-search-job-detail-link` hrefs. JD from detail page.

### Wellfound

Method: `curl_cffi` first, then Playwright (GraphQL intercept + DOM). Often `blocked` (Cloudflare 403). Set `JOB_SITE_HEADED=1` for headed Chromium if headless fails.

### Built In

Method: `curl_cffi`. Search: `https://builtin.com/jobs?search=`. Parses `/job/{slug}/{id}` paths. JD from job page.

### RemoteOK

Method: `requests`. `GET /api`, local filter on position/tags/description. JD often inline in API `description`.

### We Work Remotely

Method: `requests`. RSS programming category; filter titles locally. JD from item link page.

### Remotive

Method: `requests`. `GET /api/remote-jobs?category=software-dev`, local filter. JD inline in `description`.

### SimplyHired

Method: `curl_cffi`. Search: `q`, `l`, `sb=dd`. Parses `/job/` links. JD from detail page.

### Monster

Method: `curl_cffi` → `samsearch_api` (`POST /jobs-svx-service/v2/monster/search-jobs/samsearch/{locale}` on `appsapi.monster.io`) → Playwright route bootstrap. Often `samsearch_blocked` (DataDome). Set `JOB_SITE_HEADED=1` if needed.

### Otta

Method: `curl_cffi` → Playwright (GraphQL + Apollo `__b64dec` + WTTJ redirect fallback). `app.otta.com` redirects to Welcome to the Jungle login; unauthenticated search returns `parser_failed` / `http_202`.

### Hacker News Who's Hiring

Method: `requests`. Algolia + Firebase APIs. Comment body is the JD. Filter by engineer keywords + US/remote text.

---

## What This Tester Does Not Do

```text
- Resume/profile scoring
- Sponsorship filtering
- Dedupe or jobs_found.md append
- Multi-query rotation in one run
- Employer official-URL resolution
```

---

## Current Live Verification

Run date: 2026-06-22 (after Playwright fallback pass)

```text
Site                     | Method            | Status        | Count | JD      | JD chars | Sample title                                  | Sample URL
-------------------------+-------------------+---------------+-------+---------+----------+-----------------------------------------------+---------------------------------------------------------------------------------
LinkedIn Jobs            | curl_cffi         | ok            | 50    | ok      | 14629    | Engineer, Embedded Software (new graduate)    | https://www.linkedin.com/jobs/view/junior-embedded-software-development-engineer
Indeed                   | curl_cffi         | ok            | 24    | ok      | 8494     | Lead Firmware Engineer                        | https://www.indeed.com/viewjob?jk=23f678ad1cba7a4c
Glassdoor                | curl_cffi         | parser_failed | 0     | skipped | 0        |                                               |
ZipRecruiter             | curl_cffi         | ok            | 20    | ok      | 7263     | Staff Engineer, Electronics & Embedded Firmwa | https://www.ziprecruiter.com/c/Kohler/Job/Staff-Engineer,-Electronics-&-Embedded
Dice                     | curl_cffi         | ok            | 20    | ok      | 11301    | ab2e1066 639b 4beb b8f9 c422e2e26eb8          | https://www.dice.com/job-detail/ab2e1066-639b-4beb-b8f9-c422e2e26eb8
Wellfound                | playwright        | blocked       | 0     | skipped | 0        |                                               |
Built In                 | curl_cffi         | ok            | 25    | ok      | 23935    | Modem Firmware Engineer                       | https://builtin.com/job/modem-firmware-engineer/9583495
RemoteOK                 | requests          | ok            | 33    | ok      | 1476     | Operations Roles                              | https://remoteOK.com/remote-jobs/remote-operations-roles-edirq-1133825
We Work Remotely         | requests          | ok            | 20    | ok      | 463      | InterContinental Recruiting: Front End Web De | https://weworkremotely.com/remote-jobs/intercontinental-recruiting-front-end-web
Remotive                 | requests          | ok            | 26    | ok      | 7512     | Mid/Senior AI Cinematic Video Editor          | https://remotive.com/remote-jobs/artificial-intelligence/mid-senior-ai-cinematic
SimplyHired              | curl_cffi         | ok            | 20    | ok      | 9327     | Lead Firmware Engineer                        | https://www.simplyhired.com/job/qgxNzhqwnI1iNVNe5BGb7qbxSVHeTbEj2AKFYSsX5ODM2GL-
Monster                  | samsearch_blocked | blocked       | 0     | skipped | 0        |                                               |
Otta                     | playwright        | http_202      | 0     | skipped | 0        |                                               |
Hacker News Who's Hiring | requests          | ok            | 50    | ok      | 730      | y, using media to educate, inspire, entertain | https://news.ycombinator.com/item?id=22666455
```

11 of 14 sites returned list `ok`. Wellfound (Cloudflare), Monster (DataDome on samsearch API), and Otta (WTTJ login redirect) remain blocked or auth-gated. Playwright + samsearch API paths are wired; use `JOB_SITE_HEADED=1` where noted. Glassdoor may vary by run.

---

## Intended Next Step

Reuse these adapters in `job_search_general.py`:

```text
LinkedIn Jobs            -> curl_cffi search + detail JD
Indeed                   -> curl_cffi paginated search + viewjob JD
Glassdoor                -> curl_cffi JSON/HTML search + listing JD
ZipRecruiter             -> curl_cffi embedded JSON + job page JD
Dice                     -> curl_cffi search + job-detail JD
Wellfound                -> Playwright GraphQL/DOM fallback (Cloudflare blocked in headless)
Built In                 -> curl_cffi /jobs search + job page JD
RemoteOK                 -> requests API + inline/filtered JD
We Work Remotely         -> requests RSS + detail JD
Remotive                 -> requests API + inline JD
SimplyHired              -> curl_cffi search + job page JD
Monster                  -> samsearch API + Playwright bootstrap (DataDome blocked)
Otta                     -> Playwright + WTTJ fallback (login/auth required)
Hacker News Who's Hiring -> Algolia/Firebase + comment text JD
```

Then add profile filtering, posting date window, dedupe, scoring, and ledger append.

---

## Simple Success Target

Reference layer is usable when every site is documented in `site_search_guide.md` and the tester shows `ok` or a documented `blocked`/`parser_failed` with mitigation notes. Production search can proceed on the 11 working list sources while Monster/Otta/Wellfound paths are hardened.
