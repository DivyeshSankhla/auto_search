# Final Architecture — Part 7

Standalone script inside `job_search_7`:

```text
job_search_7/jobsearch_part7.py
```

Reuses proven source methods from:

```text
job_source_endpoint_testing/part7/unified_job_source_tester.py
```

## Command Interface

```bash
python3 jobsearch_part7.py
python3 jobsearch_part7.py --append
python3 jobsearch_part7.py --limit 50 --days 4
python3 jobsearch_part7.py --company "Nuro"
python3 jobsearch_part7.py --self-test
```

## Companies (ranks 61–70)

| Company | Adapter | Source |
|---|---|---|
| Nuro | `GreenhouseAdapter` | Greenhouse API |
| Kodiak Robotics | `GreenhouseAdapter` | Greenhouse API |
| Gatik | `GreenhouseAdapter` | Greenhouse API |
| May Mobility | `MayMobilityGreenhouseAdapter` | Greenhouse API, dual-board fallback |
| Avride | `GreenhouseAdapter` | Greenhouse API |
| Serve Robotics | `AshbyAdapter` | Ashby API |
| Gecko Robotics | `AshbyAdapter` | Ashby API |
| Skild AI | `GreenhouseAdapter` | Greenhouse API |
| Motorola Solutions / Avigilon | `WorkdayCXSAdapter` | Workday CXS + US facet |
| Zebra Technologies | `WorkdayCXSAdapter` | Workday CXS + US facet |

## Pipeline

Same contract as Parts 1–6: filter, score ≥70, dedupe against shared `jobs_found.md`, dry run by default.

`MayMobilityGreenhouseAdapter` tries board `maymobility` first, then `maymobilityjobs` if the primary returns zero jobs.
