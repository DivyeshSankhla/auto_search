# Final Architecture — Part 3

Standalone script inside `job_search_3`:

```text
job_search_3/jobsearch_part3.py
```

Reuses proven source methods from:

```text
job_source_endpoint_testing/part3/unified_job_source_tester.py
```

Shared docs at repo root:

```text
auto_search/jobsearchdocs/
```

## Command Interface

```bash
python3 jobsearch_part3.py
python3 jobsearch_part3.py --append
python3 jobsearch_part3.py --limit 50 --days 4
python3 jobsearch_part3.py --company Ciena
python3 jobsearch_part3.py --self-test
```

## Companies (ranks 21–30)

| Company | Adapter | Source |
|---|---|---|
| Bosch | `BoschCaaSAdapter` | CaaS API with Bearer token from jobs.bosch.com config |
| Siemens | `SiemensAvatureAdapter` | Avature HTML search pagination |
| Honeywell | `OracleCEAdapter` | Oracle HCM REST |
| HPE Aruba Networking | `HPEBrandAdapter` | HPE Phenom `phApp.ddo`, keyword Aruba |
| Juniper Networks | `HPEBrandAdapter` | HPE Phenom `phApp.ddo`, keyword Juniper |
| Arista Networks | `AristaSmartRecruitersAdapter` | SmartRecruiters API |
| Fortinet | `OracleCEAdapter` | Oracle HCM REST |
| Ciena | `WorkdayCXSAdapter` | Workday CXS + US facet |
| Nokia | `OracleCEAdapter` | Oracle HCM REST (may return http_503) |
| Ericsson | `PCSAdapter` | PCS search + position_details |

## Fetch Strategy

Official source first, recent/top broad results, location early when supported, keywords for scoring only, detail fetch before accept/reject.

HPE brand adapters report `requires_browser` when `phApp.ddo` yields zero jobs. Nokia failures are reported as `http_503` without inventing listings.

## Pipeline

Same contract as Parts 1–2: filter, score ≥70, dedupe against shared `jobs_found.md`, dry run by default.

`location_ok` accepts `US, State, City` Oracle/Workday location strings.

This is the implementation source of truth for `jobsearch_part3.py`.
