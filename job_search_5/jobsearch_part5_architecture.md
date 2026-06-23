# Final Architecture — Part 5

Standalone script inside `job_search_5`:

```text
job_search_5/jobsearch_part5.py
```

Reuses proven source methods from:

```text
job_source_endpoint_testing/part5/unified_job_source_tester.py
```

Shared docs at repo root:

```text
auto_search/jobsearchdocs/
```

## Command Interface

```bash
python3 jobsearch_part5.py
python3 jobsearch_part5.py --append
python3 jobsearch_part5.py --limit 50 --days 4
python3 jobsearch_part5.py --company Zoox
python3 jobsearch_part5.py --self-test
```

## Companies (ranks 41–50)

| Company | Adapter | Source |
|---|---|---|
| Johnson Controls | `WorkdayCXSAdapter` | Workday CXS + US facet |
| Panasonic | `JibeAdapter` | Jibe API, `country=United States` |
| Canonical | `GreenhouseAdapter` | Greenhouse API, US/Americas filter |
| Roku | `GreenhouseAdapter` | Greenhouse API + weareroku.com URLs |
| Sonos | `WorkdayCXSAdapter` | Workday CXS + US facet |
| Bose | `WorkdayCXSAdapter` | Workday CXS + US facet |
| Verkada | `GreenhouseAdapter` | Greenhouse API, US/Americas filter |
| Samsara | `GreenhouseAdapter` | Greenhouse API + samsara.com URLs |
| Zoox | `LeverAdapter` | Lever API |
| Rivian / Rivian VW | `RivianCombinedAdapter` | Jibe (Rivian) + Ashby (Rivian VW) |

## Fetch Strategy

Official source first, recent/top broad results, location early when supported, keywords for scoring only, detail fetch before accept/reject.

Greenhouse adapters pre-filter US/Americas locations (`north america`, `americas`, US states) before applying `ctx.limit`.

Canonical accepts Americas-remote postings (e.g. Home based - Americas) via extended `is_us_text`.

Sonos may return fewer than 50 postings; thin boards are reported, not treated as parser failure.

Rivian combined adapter merges Jibe and Ashby sources under one company name with URL dedupe.

## Pipeline

Same contract as Parts 1–4: filter, score ≥70, dedupe against shared `jobs_found.md`, dry run by default.

`location_ok` accepts `US, State, City` Workday location strings.

This is the implementation source of truth for `jobsearch_part5.py`.
