# Final Architecture — Part 4

Standalone script inside `job_search_4`:

```text
job_search_4/jobsearch_part4.py
```

Reuses proven source methods from:

```text
job_source_endpoint_testing/part4/unified_job_source_tester.py
```

Shared docs at repo root:

```text
auto_search/jobsearchdocs/
```

## Command Interface

```bash
python3 jobsearch_part4.py
python3 jobsearch_part4.py --append
python3 jobsearch_part4.py --limit 50 --days 4
python3 jobsearch_part4.py --company Schneider
python3 jobsearch_part4.py --self-test
```

## Companies (ranks 31–40)

| Company | Adapter | Source |
|---|---|---|
| Medtronic | `WorkdayCXSAdapter` | Workday CXS + US facet |
| Intuitive Surgical | `WorkdayCXSAdapter` | Workday CXS + US facet |
| GE HealthCare | `WorkdayCXSAdapter` | Workday CXS + US facet |
| Siemens Healthineers | `SearchJobsAdapter` | SearchJobs static HTML pagination |
| Dexcom | `WorkdayCXSAdapter` | Workday CXS + state-name facet matcher |
| Rockwell Automation | `WorkdayCXSAdapter` | Workday CXS + US facet |
| Schneider Electric | `JibeAdapter` | Jibe API, `country=United States` |
| Eaton | `EightfoldPCSAdapter` | Eightfold `/api/pcsx/search` |
| Caterpillar | `CaterpillarXMLAdapter` | Official XML RSS feed |
| John Deere | `JohnDeereAdapter` | SuccessFactors/J2W static HTML |

## Fetch Strategy

Official source first, recent/top broad results, location early when supported, keywords for scoring only, detail fetch before accept/reject.

Siemens Healthineers SearchJobs location params do not narrow results at source; apply `location_ok` after HTML detail enrichment.

Dexcom Workday facets are often state/city values — `is_us_text` includes US state names for facet discovery.

Eaton and Intuitive Surgical boards may return thin inventories; low counts are reported, not treated as parser failure.

## Pipeline

Same contract as Parts 1–3: filter, score ≥70, dedupe against shared `jobs_found.md`, dry run by default.

`location_ok` accepts `US, State, City` Oracle/Workday location strings.

This is the implementation source of truth for `jobsearch_part4.py`.
