# Final Architecture — Part 8

Standalone script inside `job_search_8`:

```text
job_search_8/jobsearch_part8.py
```

## Companies (ranks 71–80)

| Company | Adapter | Source |
|---|---|---|
| Cognex | `WorkdayCXSAdapter` | Workday CXS |
| Axis Communications | `WorkdayCXSAdapter` | Workday CXS |
| Arlo | `WorkdayCXSAdapter` | Workday CXS |
| Ubiquiti | `GreenhouseAdapter` | Greenhouse API |
| Netgear | `AshbyAdapter` | Ashby API |
| TP-Link | `WorkableAdapter` | Workable markdown jobs list |
| Ambarella | `WorkdayCXSAdapter` | Workday CXS |
| ON Semiconductor | `OracleCEAdapter` | Oracle CE REST API |
| MediaTek | `MediaTekCrawlAdapter` | Next.js careers crawl |
| Renesas | `SmartRecruitersAdapter` | SmartRecruiters API |

## New adapters

- `WorkableAdapter` — parses `jobs.md` markdown from Workable
- `MediaTekCrawlAdapter` — BFS crawl from seed job IDs on careers.mediatek.com
- `OracleCEAdapter` — carried from Part 3
- `SmartRecruitersAdapter` — generic SmartRecruiters with company slug
