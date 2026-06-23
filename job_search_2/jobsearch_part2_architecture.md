# Final Architecture — Part 2

Standalone script inside `job_search_2`:

```text
job_search_2/jobsearch_part2.py
```

Reuses proven source methods from:

```text
job_source_endpoint_testing/part2/unified_job_source_tester.py
```

Shared docs live at repo root:

```text
auto_search/jobsearchdocs/
  job_search_preferences.json
  job_search_profile.json
  jobs_found.md
```

Both Part 1 and Part 2 scripts read/write the same shared `jobsearchdocs/` folder via `../jobsearchdocs`.

## Command Interface

```bash
python3 jobsearch_part2.py
```

Dry run. Search, normalize, filter, score, dedupe, print results.

```bash
python3 jobsearch_part2.py --append
```

Re-read ledger, dedupe again, append new jobs.

```bash
python3 jobsearch_part2.py --limit 50 --days 4
```

Configurable source limit and freshness window.

```bash
python3 jobsearch_part2.py --company AMD
python3 jobsearch_part2.py --self-test
```

## Companies (ranks 11–20)

| Company | Adapter | Source |
|---|---|---|
| Cisco | `CiscoAdapter` | Phenom HTML search with US country filter |
| AMD | `JibeAdapter` | `https://careers.amd.com/api/jobs` |
| Broadcom | `WorkdayCXSAdapter` | Workday CXS + live US facet discovery |
| Intel | `WorkdayCXSAdapter` | Workday CXS + live US facet discovery |
| Arm | `ArmAdapter` | TalentBrew HTML cards + detail confirmation |
| Marvell | `WorkdayCXSAdapter` | Workday CXS, `Country` facet |
| Texas Instruments | `OracleCEAdapter` | Oracle HCM REST API, date-sorted |
| NXP | `WorkdayCXSAdapter` | Workday CXS, `Location_Country` facet |
| Garmin | `JibeAdapter` | `https://careers.garmin.com/api/jobs` |
| Sony | `SonyAdapter` | Workday global + PlayStation careers merge |

## Fetch Strategy

```text
official source first
recent/top broad results
location early when supported
keywords later for filtering/scoring only
detail fetch before final accept/reject
```

Do not fetch top 50 per keyword. Fetch once per company, then score.

## Detail Enrichment

- **Workday CXS**: GET `{cxs_base}{externalPath}` for `jobPostingInfo`, fallback to public HTML
- **Jibe (AMD, Garmin)**: API detail by req ID, fallback to canonical URL HTML
- **Cisco / TI / PlayStation**: official job page HTML
- **Arm**: required detail fetch; list page US facet is unreliable — reject non-US after detail

## Pipeline

Same contract as Part 1:

1. Fetch via adapters
2. Normalize to `RawJob`
3. Hard reject: location, age, sponsorship/clearance/citizenship, role family
4. Weak role match if fewer than 3 term hits (unless strong title)
5. Score ≥ 70 to accept
6. Dedupe against shared `jobs_found.md`
7. Dry run by default; `--append` writes timestamped `## Run:` section

## Self Tests

`--self-test` covers Part 2 parsers (Cisco, Jibe, Workday facets, Arm, TI URL), date parse, sponsorship reject, dedupe, and scoring sanity. No network required.

This is the implementation source of truth for `jobsearch_part2.py`.
