# Final Architecture — Part 9

Standalone script inside `job_search_9`:

```text
job_search_9/jobsearch_part9.py
```

## Companies (ranks 81–90)

| Company | Adapter | Source |
|---|---|---|
| Infineon | `EightfoldPCSAdapter` | Eightfold PCS API with pagination |
| STMicroelectronics | `STMicroEightfoldAdapter` | PCS API + HTML embed fallback |
| Microchip | `SmartRecruitersAdapter` | SmartRecruiters API |
| Lattice Semiconductor | `ICIMSAdapter` | iCIMS HTML search |
| Synaptics | `SynapticsHTMLAdapter` | Careers HTML job links |
| Teledyne FLIR | `WorkdayCXSAdapter` | Workday CXS |
| Hanwha Vision | `ADPWorkforceAdapter` | ADP job-requisitions API |
| Alarm.com | `GreenhouseAdapter` | Greenhouse API |
| SimpliSafe | `GreenhouseAdapter` | Greenhouse API |
| iRobot | `WorkdayCXSAdapter` | Workday CXS |

Synaptics degrades gracefully with `blocked` health when Cloudflare returns 403.
