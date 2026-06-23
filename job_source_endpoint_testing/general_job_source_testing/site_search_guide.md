# General Job Site Search Guide

This guide is the **source-of-truth reference** for `job_search_general.py`. It documents how to search each general US job platform for engineer roles: keyword input, location filter, date sort, pagination to top 50, list fields, and JD/detail fetch.

Default health-check inputs used by [`unified_job_site_tester.py`](unified_job_site_tester.py):

```text
JOB_SITE_TEST_QUERY=firmware engineer
JOB_SITE_TEST_LOCATION=United States
JOB_SOURCE_TEST_LIMIT=50
```

Engineer query rotation for the real script:

```text
embedded software engineer
firmware engineer
systems software engineer
linux kernel engineer
```

---

## 1. LinkedIn Jobs

Official sources:

- Search UI: `https://www.linkedin.com/jobs/search/`
- Guest search works with browser-like HTTP (`curl_cffi`); logged-in session improves reliability

Search parameters:

| Parameter | Name | Example |
|---|---|---|
| Keywords | `keywords` | `firmware engineer` |
| Location | `location` | `United States` |
| Sort by date | `sortBy` | `DD` (most recent) |
| Pagination | `start` | `0`, `25`, `50` (25 per page typical) |

Example search URL:

```text
https://www.linkedin.com/jobs/search/?keywords=firmware+engineer&location=United+States&sortBy=DD&start=0
```

List record fields:

- Title: `base-search-card__title` text or paired with view slug
- URL: `https://www.linkedin.com/jobs/view/{slug}`
- Job ID: numeric suffix in slug when present

Detail / JD fetch:

- Open the `jobs/view/{slug}` page
- Parse description from rendered HTML (`description__text`, `show-more-less-html`, or main article)
- Prefer `curl_cffi` or Playwright with optional saved session cookies

Canonical URL on platform:

```text
https://www.linkedin.com/jobs/view/{slug}
```

Blockers / fallbacks:

- Guest HTML may omit some fields; auth session recommended for production search
- Rate-limit aggressively; use delays between pages

Repeatable search steps for `job_search_general.py`:

1. Build search URL with `keywords`, `location`, `sortBy=DD`.
2. Fetch pages with `start=0,25,50,...` until 50 unique view URLs or no new cards.
3. Parse title + view URL from each card.
4. Open detail page for shortlisted rows; extract full JD text.

---

## 2. Indeed

Official sources:

- Search UI: `https://www.indeed.com/jobs`
- List HTML embeds `data-jk` job keys

Search parameters:

| Parameter | Name | Example |
|---|---|---|
| Keywords | `q` | `firmware engineer` |
| Location | `l` | `United States` |
| Sort by date | `sort` | `date` |
| Pagination | `start` | `0`, `10`, `20`, ... (10 per page) |

Example:

```text
https://www.indeed.com/jobs?q=firmware+engineer&l=United+States&sort=date&start=0
```

List record fields:

- Title: `<span title="...">` near job card, or jobTitle span
- Job ID: `data-jk` (hex)
- URL: `https://www.indeed.com/viewjob?jk={jk}`

Detail / JD fetch:

- `GET https://www.indeed.com/viewjob?jk={jk}`
- JD container: `#jobDescriptionText`

Blockers:

- Stdlib `urllib` returns HTTP 403; use `curl_cffi` with Chrome impersonation

Repeatable steps:

1. Paginate `start` by 10 with `sort=date`.
2. Pair `data-jk` with title attributes.
3. Fetch viewjob page for JD.

---

## 3. Glassdoor

Official sources:

- Search: `https://www.glassdoor.com/Job/jobs.htm`

Search parameters:

| Parameter | Name | Example |
|---|---|---|
| Keywords | `keyword` | `firmware engineer` |
| Location type | `locT` | `N` (country) |
| Location ID | `locId` | `1` (United States) |

Example:

```text
https://www.glassdoor.com/Job/jobs.htm?keyword=firmware+engineer&locT=N&locId=1
```

List record fields:

- Embedded JSON pairs: `"jobTitleText"`, `"jobLink"`
- URL: `https://www.glassdoor.com/job-listing/...`

Detail / JD fetch:

- Open job-listing URL; parse description section / JSON-LD `JobPosting`

Blockers:

- Use `curl_cffi`; filter list rows locally — API payload may include non-engineering noise

---

## 4. ZipRecruiter

Official sources:

- Search: `https://www.ziprecruiter.com/jobs-search`

Search parameters:

| Parameter | Name | Example |
|---|---|---|
| Keywords | `search` | `firmware engineer` |
| Location | `location` | `United States` |
| Pagination | `page` | `1`, `2`, ... |

Example:

```text
https://www.ziprecruiter.com/jobs-search?search=firmware+engineer&location=United+States
```

List record fields:

- Embedded JSON: `"name"` (title), `"url"` (canonical job URL under `/c/{company}/Job/...`)

Detail / JD fetch:

- Open JSON `url`; parse job description section in HTML

Blockers:

- Use `curl_cffi`

---

## 5. Dice

Official sources:

- Search: `https://www.dice.com/jobs`

Search parameters:

| Parameter | Name | Example |
|---|---|---|
| Keywords | `q` | `firmware engineer` |
| Location | `location` | `United States` |
| Page | `page` | `1`, `2`, `3` |
| Page size | `pageSize` | `20` |
| Posted filter | `filters` | `postedDate=ONE` (optional) |

Example:

```text
https://www.dice.com/jobs?q=firmware+engineer&location=United+States&page=1&pageSize=20
```

List record fields:

- Detail link: `data-testid="job-search-job-detail-link" href="https://www.dice.com/job-detail/{uuid}"`
- Title: card text or detail page `<title>`

Detail / JD fetch:

- Open `/job-detail/{uuid}`; parse main content / job description blocks

Blockers:

- Use `curl_cffi`; page is client-heavy but detail links appear in SSR HTML

---

## 6. Wellfound

Official sources:

- Search: `https://wellfound.com/jobs`
- GraphQL (browser session): `https://wellfound.com/graphql`

Search parameters:

| Parameter | Name | Example |
|---|---|---|
| Keywords | `search` | `firmware engineer` |
| Location | `location` | `United States` |

Fallback chain in tester:

1. `curl_cffi` HTML parse (`/jobs/`, `/jobs/listing/`)
2. Playwright: intercept GraphQL responses + rendered DOM (longer Cloudflare wait)
3. Optional headed mode: `JOB_SITE_HEADED=1`

Blockers:

- Often returns HTTP 403 to automated requests (Cloudflare)
- Headless Playwright may remain `blocked`; try headed Chromium or manual session cookies

---

## 7. Built In

Official sources:

- Search: `https://builtin.com/jobs`

Search parameters:

| Parameter | Name | Example |
|---|---|---|
| Keywords | `search` | `firmware engineer` |
| Remote filter | `remote` | `true` (optional) |

Example:

```text
https://builtin.com/jobs?search=firmware+engineer
```

List record fields:

- Path: `/job/{slug}/{numeric_id}`
- URL: `https://builtin.com/job/{slug}/{id}`

Detail / JD fetch:

- Open job page; parse description section (large HTML body)

Blockers:

- Use `curl_cffi`

---

## 8. RemoteOK

Official sources:

- Public API: `GET https://remoteok.com/api`

Search parameters:

- No server-side keyword param; fetch full feed and filter locally
- Filter on `position`, `tags`, `description`
- US/remote: most rows are remote worldwide

List record fields:

- `id`, `position`, `url`, `description`, `date`, `tags`

Detail / JD fetch:

- `description` field often present in API row (HTML)
- Else open `url`

Pagination:

- Single feed; slice first 50 after local filter

Repeatable steps:

1. `GET /api`
2. Filter rows matching query tokens / engineer terms
3. Sort by `date` descending
4. Use inline `description` or fetch `url` for JD

---

## 9. We Work Remotely

Official sources:

- RSS: `https://weworkremotely.com/categories/remote-programming-jobs.rss`

Search parameters:

- Category feed (programming); filter locally on title/description

List record fields:

- RSS `title`, `link`, `pubDate`

Detail / JD fetch:

- RSS item link → detail page HTML

Pagination:

- Single feed (~25 items per category); combine categories if needed

---

## 10. Remotive

Official sources:

- API: `GET https://remotive.com/api/remote-jobs?category=software-dev`

Search parameters:

| Parameter | Name | Example |
|---|---|---|
| Category | `category` | `software-dev` |

List record fields:

- `id`, `title`, `url`, `description`, `publication_date`, `tags`

Detail / JD fetch:

- Inline `description` (HTML) in API row

Pagination:

- Single JSON response; filter locally; slice to 50

---

## 11. SimplyHired

Official sources:

- Search: `https://www.simplyhired.com/search`

Search parameters:

| Parameter | Name | Example |
|---|---|---|
| Keywords | `q` | `firmware engineer` |
| Location | `l` | `United States` |
| Sort | `sb` | `dd` (date descending) |

Example:

```text
https://www.simplyhired.com/search?q=firmware+engineer&l=United+States&sb=dd
```

List record fields:

- Job path: `/job/{id-token}`
- Title from card anchor text

Detail / JD fetch:

- Open job URL; parse description block

Blockers:

- Use `curl_cffi`

---

## 12. Monster

Official sources:

- Search UI: `https://www.monster.com/jobs/search`
- Search API: `POST https://appsapi.monster.io/jobs-svx-service/v2/monster/search-jobs/samsearch/{locale}?apikey=...`

Search parameters:

| Parameter | Name | Example |
|---|---|---|
| Keywords | `q` | `firmware engineer` |
| Location | `where` | `United States` |
| Sort | `sort` | `dt.rv.di` (recency) |

API body (samsearch):

```json
{
  "jobRequest": {
    "offset": 0,
    "pageSize": 50,
    "jobQuery": {
      "query": "firmware engineer",
      "locations": [{"address": "United States", "country": "us"}]
    }
  },
  "siteId": "<from __NEXT_DATA__>"
}
```

Fallback chain in tester:

1. SSR `__NEXT_DATA__` + href parse (usually empty `jobResults`)
2. `samsearch_api` via `curl_cffi` (api key from Next.js bundle)
3. Playwright route-fulfill + in-page `fetch` to samsearch
4. Playwright network capture on search page

Blockers:

- SSR `__NEXT_DATA__` often has empty `jobResults`; listings are client-rendered
- DataDome protects samsearch API (`samsearch_blocked` in tester)
- Playwright direct navigation often HTTP 403; route-fulfill may still hit captcha
- Try `JOB_SITE_HEADED=1` for production script

---

## 13. Otta

Official sources:

- Search UI (redirects): `https://app.otta.com/search` → Welcome to the Jungle login
- WTTJ fallback: `https://www.welcometothejungle.com/en/jobs`
- GraphQL API: `https://api.otta.com/graphql` (requires authentication for `jobs` query)

Search parameters:

| Parameter | Name | Example |
|---|---|---|
| Query | `query` | `firmware engineer` |
| Location | `location` / `aroundQuery` | `United States` |

Fallback chain in tester:

1. `curl_cffi` HTML + base64 Apollo `__b64dec` decode
2. Playwright: capture `api.otta.com/graphql`, DOM `/jobs/` links, WTTJ company job URLs
3. WTTJ public jobs page via `curl_cffi` / Playwright

Blockers:

- Otta search redirects to `app.welcometothejungle.com/login` (auth required)
- Public GraphQL `jobs` field returns `Unauthenticated`
- WTTJ curl may return HTTP 202 (edge challenge); unauthenticated search yields no job cards
- Production script needs WTTJ/Otta login session or alternate syndicated source

---

## 14. Hacker News Who's Hiring

Official sources:

- Latest thread via Algolia: `https://hn.algolia.com/api/v1/search?query=who+is+hiring+right+now&tags=story`
- Comment API: `https://hacker-news.firebaseio.com/v0/item/{id}.json`

Search parameters:

- No keyword param; fetch monthly thread top-level comments
- Filter locally for query tokens + US/Remote mentions

List record fields:

- Comment `text` (HTML) is both listing and JD
- URL: `https://news.ycombinator.com/item?id={comment_id}`

Detail / JD fetch:

- Comment body IS the JD (strip HTML tags)

Pagination:

- Iterate `kids` array on story item (500+ comments); stop at 50 matches

Repeatable steps:

1. Find latest "Who is hiring" story ID via Algolia.
2. Fetch story; iterate top-level comment IDs.
3. Filter comments by engineer keywords and US/remote location text.
4. Use comment text as JD; optional outbound links inside comment for apply URL.

---

## Shared notes for `job_search_general.py`

```text
- Prefer curl_cffi (Chrome impersonation) for Indeed, LinkedIn, Glassdoor, ZipRecruiter, Dice, Built In, SimplyHired
- Stdlib requests sufficient for RemoteOK, Remotive, WWR RSS, HN Firebase/Algolia
- Playwright fallback for Monster, Otta, and optional LinkedIn session
- This guide documents platform URLs; the real script adds profile filtering, date windows, dedupe, and ledger append
```
