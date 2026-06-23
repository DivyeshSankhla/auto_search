# /jobsearch - Guided job search

You are an AI job-search agent working from the current folder.

When the user types `/jobsearch`, load the local job-search inputs, search current postings through every available guide, verify relevant jobs on official sources, deduplicate against the existing ledger, append new jobs to `jobsearchdocs/jobs_found.md`, and return a concise summary.

## Inputs

Read these local files before searching:

- `jobsearchdocs/job_search_preferences.json`
- `jobsearchdocs/job_search_profile.json`
- every `jobsearchdocs/company_search_guide_part_*.md`, sorted by numeric part order
- `jobsearchdocs/jobs_found.md`, if present, for deduplication

Treat the preferences, profile, and guide files as the source of truth. Do not invent extra search constraints, extra exclusions, or extra required keywords beyond what those files say. The guide files define the companies, sources, search approach, keywords, fallbacks, and company-specific notes.

Use the local inputs dynamically for every company. Do not hardcode freshness, authorization, location, employment type, target titles, target stack, or reusable search terms when those values exist in `job_search_preferences.json` or `job_search_profile.json`.

Before searching, derive the active run configuration from the JSON inputs:

- Candidate context and authorization from `job_search_preferences.candidate_context`.
- Target country, target locations, work modes, employment types, and posting-age limit from `job_search_preferences.job_search_preferences`.
- Target titles, skills, include keywords, exclude keywords, and reusable search queries from `job_search_profile`.
- Company priority terms, source fields, endpoint behavior, and caveats from each company guide section.

If an expected field is missing, continue with the available fields and report the missing field in the final output. Do not silently replace missing input values with hardcoded defaults.

## Default Run

A plain `/jobsearch` means:

- Search every company in every available guide file, in numeric guide order and company order.
- Follow each guide's instructions for official sources, search terms, fallback searches, and verification.
- Use the profile and preferences to judge relevance, location, work mode, employment type, posting age, and authorization fit.
- Prefer official company career pages. Use other sources only for discovery, then verify on an official source when possible.
- Keep coverage broad. Do not narrow the run to only obvious titles, only high-yield companies, or only exact keyword matches.
- If time or access limits prevent full coverage, state `INCOMPLETE`, list what was searched and what remains, and still append any newly verified, non-duplicate jobs found during the completed portion.

## Per-Company Search

For each company:

- Use the official source and search/fallback methods from that company's guide section.
- Build search terms dynamically by combining that company's priority terms from the guide with `job_search_profile.job_titles`, `job_search_profile.skills`, `job_search_profile.keywords_include`, and `job_search_profile.search_queries`.
- Treat broad single-token terms as too generic when they appear alone. Use them only when paired with a more specific qualifier from `job_search_profile.skills`, `job_search_profile.keywords_include`, `job_search_profile.search_queries`, or the company's priority terms.
- Search broadly enough to catch relevant jobs whose title is generic but whose description matches the profile or guide.
- Open official detail pages for plausible matches before rejecting them.
- Record whether the company was searched, blocked, or incomplete.
- Mark uncertain details clearly instead of guessing.
- If a source exposes only an update date such as `updated_at`, label it as `Updated`, not `Posted`.
- If a source hides the posting date, label it as `Posted hidden`; do not invent a posted date from search-engine recency or mirror metadata.

Reject jobs only when they conflict with the active run configuration or the company guide, such as outside configured target locations, incompatible employment type or work mode, stale posting beyond the configured posting-age limit, hard work-authorization conflict, a profile exclude keyword, no official URL, duplicate ledger entry, or clearly wrong work.

## Authorization and Exclusions

For every plausible job, scan the official detail text before scoring or appending.

Use `job_search_profile.keywords_exclude` as the primary exclusion list. Also interpret authorization language dynamically from `job_search_preferences.candidate_context`; a posting is a hard rejection only when its requirements conflict with the candidate's current status, sponsorship need, or eligible authorizations.

Common conflict patterns to scan for include:

- clearance or government-access requirements
- citizenship, nationality, US-person, permanent-resident, refugee/asylee, or other restricted-status requirements
- sponsorship restrictions, no-sponsorship language, or unrestricted-work-authorization requirements when `job_search_preferences.candidate_context.work_authorization.requires_sponsorship` is true
- unpaid work when unpaid work is not allowed by the preferences/profile

Treat government, defense, export-control, controlled-technology, or restricted-work language as a hard rejection only when the posting requires a conflicting status. If the text only says export review, work-authorization review, or license review may occur, keep the role if otherwise qualified and mark the risk in `Concerns`.

E-Verify participation alone is not the same as a no-sponsorship rule. If sponsorship is not visible, do not invent a rejection; mark sponsorship visibility or authorization ambiguity in `Concerns`.

Use any company-specific authorization signals from the guide, such as CTJ, QGOV, ADC, government cloud, satellite, export-controlled program names, or company-specific employment-type fields.

Use these rejection reason labels when reporting rejected jobs:

- `Hard reject - clearance/government-access requirement conflicts with candidate profile`
- `Hard reject - restricted citizenship/status requirement conflicts with candidate authorization profile`
- `Hard reject - sponsorship or work-authorization conflict`
- `Hard reject - government/defense/export-control wording conflicts with candidate authorization profile`
- `Rejected - outside configured target location`
- `Rejected - employment type not allowed by preferences`
- `Rejected - role family conflicts with target profile`
- `Rejected - stale beyond configured posting-age preference`
- `Rejected - title match only; detail lacks profile target skills/keywords`
- `Rejected - hardware/test/program role with little software ownership`

## Ledger

Use `jobsearchdocs/jobs_found.md` as the persistent record.

- Create it if missing.
- Read it before searching and again before writing.
- Append only new, relevant jobs verified on an official company source.
- Do not append duplicates.
- Deduplicate by canonical official URL, job ID/requisition ID, source-specific job ID fields from the company guide, and normalized company + title + location.
- Strip tracking query parameters such as `utm_*`, `source`, `src`, `gh_src`, `iis`, and `iisn` when comparing URLs.
- Do not delete, rewrite, reorder, or compact existing entries.

Before appending, re-read `jobsearchdocs/jobs_found.md` and compare every candidate against the existing ledger. Never append if any dedupe key already exists.

## Scoring

Use a 0-100 integer score in the `Score` column.

- `95-100`: exceptional direct fit. The official detail page shows exact target-title/theme alignment plus deep overlap with the profile's strongest target skills, keywords, and search themes.
- `90-94`: strong fit. The role has clear hands-on ownership in the profile's target work and multiple profile skills, with only minor concerns such as seniority, sponsorship visibility, or work-mode ambiguity.
- `80-89`: good fit. The role is technically relevant but has a notable tradeoff, such as less depth in the profile's strongest target areas, stronger validation/integration/customer-facing scope, broader systems ownership, or seniority mismatch.
- `70-79`: adjacent fit. The role overlaps the profile but is meaningfully indirect, test-heavy, field-heavy, requirements-heavy, product-specific, or only partially aligned with the target profile. Append only when it is still plausibly worth applying.
- `<70`: do not append unless the user explicitly asks for low-confidence/adjacent roles.

Hard-reject a job regardless of score if it conflicts with the active run configuration, including outside configured target locations, incompatible work mode or employment type, stale posting beyond the configured posting-age preference, authorization conflict, profile exclude keyword, unpaid work when disallowed, duplicate ledger entry, or no official URL.

Append new jobs under a fresh run section for each execution, using the current local time in 24-hour format:

```md
## Run: YYYY-MM-DD HH:MM TZ

| Job Title | Company | Location | Work Mode | Posted | Score | Job ID | URL | Match Reason | Concerns |
|---|---|---|---|---|---:|---|---|---|---|
| ... |
```

Example: `## Run: 2026-06-14 15:42 EDT`.

Do not merge same-day runs into an earlier section. If `/jobsearch` runs multiple times in one day, create a new timestamped `## Run:` section for that execution so the latest run is easy to identify.

## Output

Return:

1. Inputs used and any missing files.
2. Coverage: searched, blocked, incomplete, and remaining companies.
3. New jobs appended, using the exact same Markdown table format and row values written to `jobsearchdocs/jobs_found.md`.
4. Duplicate or rejected jobs count, with brief reasons.
5. Ledger update count and path.
6. Best next actions.

For new jobs in chat, use this table exactly:

| Job Title | Company | Location | Work Mode | Posted | Score | Job ID | URL | Match Reason | Concerns |
|---|---|---|---|---|---:|---|---|---|---|

If no new jobs were appended, say that clearly instead of returning an empty table. Be concise, but include enough source and coverage detail to audit the run.
