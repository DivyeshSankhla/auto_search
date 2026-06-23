# Final Architecture — General Job Search

Standalone script inside `job_search_general`:

```text
job_search_general/job_search_general.py
```

Parsing logic ported from:

```text
job_source_endpoint_testing/general_job_source_testing/unified_job_site_tester.py
```

Pipeline, scoring, and dedupe ported from:

```text
job_search_7/jobsearch_part7.py
```

Shared docs (same paths as Part 7):

```text
jobsearchdocs/job_search_preferences.json
jobsearchdocs/job_search_profile.json
jobsearchdocs/jobs_found.md
```

## Command Interface

```bash
python3 job_search_general.py
python3 job_search_general.py --append
python3 job_search_general.py --sites indeed,remoteok
python3 job_search_general.py --query "firmware engineer" --limit 50 --days 4
python3 job_search_general.py --self-test
python3 job_search_general.py --verbose
```

| Flag | Purpose |
|---|---|
| `--sites` | Comma-separated slugs (`indeed`, `linkedin`, `remoteok`, `wwr`, `hn`, …) or `all` |
| `--query` | Override search query; default rotates `PROFILE_QUERIES` by day |
| `--days` | Posting freshness window (default from preferences JSON or 3) |
| `--limit` | Max raw rows per site (default 50) |
| `--append` | Write accepted jobs to `jobs_found.md` after final dedupe |
| `--self-test` | Offline mock checks (no network) |
| `--verbose` | Per-adapter progress |

## Query Rotation

When `--query` is omitted, one query is chosen per run:

```text
embedded software engineer
firmware engineer
systems software engineer
linux kernel engineer
```

Selection: `PROFILE_QUERIES[date.toordinal() % len(PROFILE_QUERIES)]`

## Site Adapters (14)

| Phase | Site | Slug | Method | Notes |
|---|---|---|---|---|
| A | LinkedIn | `linkedin` | curl_cffi | `sortBy=DD`, paginate `start` |
| A | Indeed | `indeed` | curl_cffi | `sort=date`, paginate `start` |
| A | Dice | `dice` | curl_cffi | `postedDate=ONE` filter |
| A | Built In | `builtin` | curl_cffi | `/job/{slug}/{id}` paths |
| A | SimplyHired | `simplyhired` | curl_cffi | `sb=dd` date sort |
| A | RemoteOK | `remoteok` | requests | Public API, inline JD |
| A | We Work Remotely | `wwr` | requests | RSS feed, inline JD |
| A | Remotive | `remotive` | requests | JSON API, inline JD |
| A | HN Who's Hiring | `hn` | requests | Algolia + Firebase, inline JD |
| B | Glassdoor | `glassdoor` | curl_cffi | Embedded JSON job links |
| B | ZipRecruiter | `ziprecruiter` | curl_cffi | Embedded JSON names/urls |
| C | Wellfound | `wellfound` | curl_cffi + playwright | Graceful skip if deps missing |
| C | Monster | `monster` | curl_cffi + playwright | Graceful skip if deps missing |
| C | Otta | `otta` | curl_cffi + playwright | WTTJ fallback; graceful skip |

`build_site_adapters()` returns all 14; `--sites` filters by slug or site name.

## Adapter Contract

```python
class SiteAdapter:
    site_name: str
    method: str
    prefer_curl: bool
    inline_description: bool

    def fetch(ctx, query, location) -> AdapterResult
```

- `RawJob.company` = employer from listing when available, else site name
- `RawJob.raw["source_site"]` tracks originating platform for URL validation
- `Health.company` holds site name for the health table

## Pipeline

```text
for each selected SiteAdapter:
    fetch(ctx, query, location) -> raw jobs
enrich_from_html_page on rows with short descriptions
    (skip inline-description sites: RemoteOK, WWR, Remotive, HN)
classify_jobs:
    dedupe vs jobs_found.md
    hard_reject (platform URL, location, age, sponsorship, role family)
    weak_role_match guard
    score >= 70
dry-run report OR --append
```

### Platform URL Validation

`is_platform_url(url, site)` replaces Part 7's `is_official_url`. External apply URLs are allowed for aggregator sites in `EXTERNAL_URL_OK_SITES`.

## Dependencies

| Tier | Package | Sites |
|---|---|---|
| Required | stdlib only | RemoteOK, WWR, Remotive, HN |
| Phase A/B | `curl_cffi` | LinkedIn, Indeed, Dice, Built In, SimplyHired, Glassdoor, ZipRecruiter |
| Phase C | `playwright` + chromium | Wellfound, Monster, Otta (fallback path) |

Phase C adapters log `skipped` / `blocked` health and return empty results rather than crashing when optional deps are missing.
