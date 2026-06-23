# Architecture Design: General Job Site Search Tester Pattern

## Purpose

This file explains the architecture behind [`unified_job_site_tester.py`](unified_job_site_tester.py) and how the same design should be reused by `job_search_general.py`.

The tester is the **source-discovery and source-health layer** for general job platforms — analogous to Part 1 company source testers, but the unit under test is a **site**, not an employer.

```text
For each site, prove keyword search works, location/date params are known,
top-N pagination is documented, list rows parse, and one JD can be read.
```

Read [`site_search_guide.md`](site_search_guide.md) for per-site endpoints and parameters.

---

## Core Idea

General job sites use different backends (HTML search, embedded JSON, public API, RSS, GraphQL, forum comments). The architecture is:

```text
site_search_guide.md
  -> search URL/API discovery
  -> list fetch with keyword + location + sort
  -> pagination to JOB_SOURCE_TEST_LIMIT
  -> parse title, url, location, date, job id
  -> sample detail fetch -> JD text
  -> unified Result output
```

---

## Unified Result Object

```python
@dataclass
class Result:
    site: str
    method: str              # requests | curl_cffi | playwright
    status: str              # list search health
    count: int
    sample_title: str = ""
    sample_url: str = ""     # on-platform URL
    jd_status: str = ""      # detail/JD probe
    sample_jd_chars: int = 0
    search_query: str = ""
```

List `status` and `jd_status` are separate: a site can parse search results but block detail pages.

---

## Status Design

| Status | Meaning |
|---|---|
| `ok` | Parseable records or JD text |
| `blocked` | HTTP 403 / access denied |
| `failed` | Network or request error |
| `parser_failed` | HTTP 200 but parser found nothing |
| `skipped` | JD probe not run (no sample URL) |
| `http_<code>` | Other HTTP response |

---

## Access Method Escalation

Same rule as Part 1 company testers:

```text
1. stdlib urllib GET/POST
2. curl_cffi Chrome impersonation (Indeed, LinkedIn, aggregators)
3. Playwright rendered HTML (Monster, Otta, optional LinkedIn session)
```

`fetch_page(url, prefer_curl=True)` tries `curl_cffi` first when installed, else falls back to stdlib.

---

## Site Adapter Pattern

Each site has one function:

```python
def test_indeed() -> Result:
    # LIST: build search URL with q, l, sort=date, start=N
    # PARSE: data-jk + title -> viewjob URL
    # JD: GET viewjob, extract #jobDescriptionText
    return finish_result(...)
```

Shared helpers:

| Helper | Role |
|---|---|
| `fetch_page` | GET with curl_cffi fallback |
| `query_match` / `query_match_loose` | Local keyword filter |
| `unique_by` | Dedupe to LIMIT |
| `probe_jd` | Detail fetch + `extract_jd_from_html` |
| `finish_result` | Build Result with list + JD probe |

---

## Parameter Testing (by site)

| Site | Keyword | Location | Sort / date | Pagination |
|---|---|---|---|---|
| LinkedIn | `keywords` | `location` | `sortBy=DD` | `start=0,25,...` |
| Indeed | `q` | `l` | `sort=date` | `start=0,10,...` |
| Glassdoor | `keyword` | `locT`, `locId` | default | page scroll / JSON batch |
| ZipRecruiter | `search` | `location` | default | `page` |
| Dice | `q` | `location` | `postedDate` filter | `page`, `pageSize=20` |
| Built In | `search` | optional `remote` | default | single page + scroll |
| RemoteOK | local filter | remote/US text | API `date` field | single feed |
| WWR | local filter | category RSS | `pubDate` | single feed |
| Remotive | local filter | `category` | `publication_date` | single API response |
| SimplyHired | `q` | `l` | `sb=dd` | page links |
| Monster | `q` | `where` | `sort=dt.rv.di` | client pagination |
| Otta | `query` | `location` | default | JS / GraphQL |
| HN | local filter | US/remote in comment | thread month | comment `kids` list |

---

## JD / Detail Fetch Design

Second step after list parse:

```text
1. Take first unique list row (or best title match)
2. If row has inline description (RemoteOK, Remotive, HN) -> use it
3. Else GET sample_url with same method family
4. extract_jd_from_html: #jobDescriptionText, itemprop=description, article/main
5. jd_status ok when cleaned text length >= 200 chars
```

---

## Per-Site Adapter Summary

### LinkedIn Jobs

```text
Method: curl_cffi
Search: /jobs/search/?keywords=&location=&sortBy=DD
Parse: base-search-card__title + jobs/view/{slug}
JD: detail page HTML
Live: ok, count=50, jd ok
```

### Indeed

```text
Method: curl_cffi
Search: /jobs?q=&l=&sort=date&start=
Parse: data-jk + span title
JD: /viewjob?jk=
Live: ok
```

### Glassdoor

```text
Method: curl_cffi
Search: /Job/jobs.htm?keyword=&locT=N&locId=1
Parse: jobTitleText + jobLink JSON
Live: ok (small count after title filter)
```

### ZipRecruiter

```text
Method: curl_cffi
Search: /jobs-search?search=&location=
Parse: embedded name + url JSON
Live: ok
```

### Dice

```text
Method: curl_cffi
Search: /jobs?q=&location=&page=
Parse: job-search-job-detail-link href
Live: ok
```

### Wellfound

```text
Method: curl_cffi -> Playwright (GraphQL + DOM, CF wait)
Live: blocked — Cloudflare in headless; JOB_SITE_HEADED=1 optional
```

### Built In

```text
Method: curl_cffi
Search: /jobs?search=
Parse: /job/{slug}/{id}
Live: ok
```

### RemoteOK

```text
Method: requests
API: GET /api, local filter
JD: inline description
Live: ok
```

### We Work Remotely

```text
Method: requests
Feed: remote-programming-jobs.rss
Live: ok
```

### Remotive

```text
Method: requests
API: /api/remote-jobs?category=software-dev
Live: ok
```

### SimplyHired

```text
Method: curl_cffi
Search: /search?q=&l=&sb=dd
Live: ok
```

### Monster

```text
Method: curl_cffi -> samsearch_api -> Playwright route bootstrap
API: POST appsapi.monster.io/jobs-svx-service/v2/monster/search-jobs/samsearch/{locale}
Live: samsearch_blocked — DataDome captcha on API
```

### Otta

```text
Method: curl_cffi -> Playwright -> WTTJ fallback
Live: http_202 / auth required — app.otta.com redirects to WTTJ login
```

### Hacker News Who's Hiring

```text
Method: requests
API: Algolia story search + Firebase items
JD: comment HTML text
Live: ok, count=50
```

---

## Tester vs `job_search_general.py`

| Tester | Real search script |
|---|---|
| Single default query | Rotate profile queries |
| Broad engineer loose filter on some sites | Strict profile title/skill filter |
| Top 50 health check | Full pagination + date window |
| Sample JD only | JD for every shortlisted row |
| No dedupe / ledger | Dedupe + jobs_found append |

---

## Browser Fallback Tier

Sites that fail on `curl_cffi` alone share a common adapter pattern in `unified_job_site_tester.py`:

```text
curl_cffi fast path
  -> site-specific API (Monster samsearch)
  -> playwright_search_jobs (network capture + DOM + scroll)
  -> optional headed browser (JOB_SITE_HEADED=1)
```

Shared helpers:

| Helper | Role |
|---|---|
| `playwright_search_jobs` | Launch Chromium, capture XHR/fetch, scroll, optional CF wait |
| `parse_jobs_from_json_blobs` | Walk GraphQL/REST JSON for title/url/jobId |
| `decode_otto_apollo` | Decode Otta `window.__APOLLO_STATE__=__b64dec(...)` |
| `fetch_monster_jobs_samsearch` | POST Monster samsearch with bundle-derived api key |
| `fetch_monster_jobs_playwright` | Route-fulfill curl HTML, run in-page samsearch fetch |
| `parse_wttj_jobs` | Parse WTTJ company job URLs after Otta redirect |

---

## Live Verification Summary

Run date: 2026-06-22 (Playwright fallback pass)

```text
11/14 list ok
1/14 blocked (Wellfound — Cloudflare)
1/14 blocked (Monster — DataDome on samsearch)
1/14 auth-gated (Otta — WTTJ login redirect)
Playwright required: pip install playwright && playwright install chromium
Optional: JOB_SITE_HEADED=1 for Wellfound/Monster headed Chromium
```

---

## Future Pipeline Mapping

```text
unified_job_site_tester.py  ->  job_search_general.py site modules
site_search_guide.md        ->  operator + agent reference
README live table           ->  regression baseline after site HTML changes
```

Each site module should export the same operations the tester proves: `search_list(query, location, limit) -> rows` and `fetch_jd(row) -> text`.
