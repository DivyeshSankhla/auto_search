# Final Architecture — Part 6

Standalone script inside `job_search_6`:

```text
job_search_6/jobsearch_part6.py
```

Reuses proven source methods from:

```text
job_source_endpoint_testing/part6/unified_job_source_tester.py
```

Shared docs at repo root:

```text
auto_search/jobsearchdocs/
```

## Command Interface

```bash
python3 jobsearch_part6.py
python3 jobsearch_part6.py --append
python3 jobsearch_part6.py --limit 50 --days 4
python3 jobsearch_part6.py --company "Boston Dynamics"
python3 jobsearch_part6.py --self-test
```

## Companies (ranks 51–60)

| Company | Adapter | Source |
|---|---|---|
| Torc Robotics | `GreenhouseAdapter` | Greenhouse API, US/Americas filter |
| Applied Intuition | `AshbyAdapter` | Ashby API, US location filter |
| Aurora | `GreenhouseAdapter` | Greenhouse API, US filter |
| Skydio | `AshbyAdapter` | Ashby API, US location filter |
| Boston Dynamics | `WorkdayCXSAdapter` | Workday CXS + US facet |
| Symbotic | `WorkdayCXSAdapter` | Workday CXS + US facet |
| Zipline | `GreenhouseAdapter` | Greenhouse API + zipline.com URLs |
| Figure AI | `GreenhouseAdapter` | Greenhouse API, US filter |
| Agility Robotics | `GreenhouseAdapter` | Greenhouse API + agilityrobotics.com URLs |
| Waabi | `LeverAdapter` | Lever API |

## Fetch Strategy

Official source first, recent/top broad results, location early when supported, keywords for scoring only, detail fetch before accept/reject.

Ashby adapters use `ashby_location_text()` to aggregate `location`, `address.postalAddress`, and `secondaryLocations` before US filtering.

Greenhouse adapters pre-filter US/Americas; Zipline and Agility Robotics use custom `public_url_template` for official careers domains.

`is_us_text` includes US state abbreviations for Ashby `addressRegion` fields.

## Pipeline

Same contract as Parts 1–5: filter, score ≥70, dedupe against shared `jobs_found.md`, dry run by default.

`location_ok` accepts `US, State, City` Workday location strings.

This is the implementation source of truth for `jobsearch_part6.py`.
