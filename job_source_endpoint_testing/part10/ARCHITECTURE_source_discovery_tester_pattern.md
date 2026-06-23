# Architecture Design: Source Discovery Tester Pattern — Part 10

## Purpose

This file explains the architecture behind Part 10 `unified_job_source_tester.py` and records the source-access design for `job_search_10` companies (ranks 91–95).

Part 10 is the **final ranked batch** — only five companies. The tester uses the same `Result` table and `JOB_SOURCE_TEST_LIMIT=50` as earlier parts, but natural counts may be small (especially GoPro).

The tester is not the final job-search pipeline. It is the **source-discovery and source-health layer**.

---

## Core Idea

Part 10 is a small mixed ATS batch with two new adapter families:

```text
1 company -> SmartRecruiters API
1 company -> Oracle CE API
1 company -> Pinpoint postings.json
1 company -> Gem public GraphQL
1 company -> Greenhouse API
```

Architecture flow:

```text
company_search_guide_part_10.md
  -> official endpoint discovery
  -> broad recent/top fetch (up to 50)
  -> US location prefilter when fields exist
  -> basic parser (title, count, official URL)
  -> unified Result output
```

---

## Unified Result Object

```python
@dataclass
class Result:
    company: str
    method: str
    status: str
    count: int
    sample_title: str = ""
    sample_url: str = ""
```

---

## Source Types Used in Part 10

| Source Type | Companies | Count |
|---|---|---|
| SmartRecruiters API | Wabtec | 1 |
| Oracle CE API | Resideo | 1 |
| Pinpoint JSON | Brivo | 1 |
| Gem GraphQL | Wyze | 1 |
| Greenhouse API | GoPro | 1 |

All Part 10 adapters use method `requests` (stdlib `urllib`).

---

## Reusable Helpers

### `test_smartrecruiters(company, company_slug, public_company)`

Same as Part 8/9:

```text
GET api.smartrecruiters.com/v1/companies/{slug}/postings?limit=20&offset=N
Sort: releasedDate descending
US filter: location.fullLocation, location.country
URL: https://jobs.smartrecruiters.com/{public_company}/{id}
```

Used by: Wabtec (`Wabtec`).

### `test_oracle(company, host, site, public_base)`

Same as Part 8:

```text
GET /hcmRestApi/resources/latest/recruitingCEJobRequisitions
finder=findReqs;siteNumber={site},...;sortBy=POSTING_DATES_DESC
Parser: items[0].requisitionList[].Title, .Id
URL: {public_base}/job/{Id}
US filter: PrimaryLocationCountry, PrimaryLocation
```

Used by: Resideo (`ehtl.fa.us6.oraclecloud.com`, site `CX`).

Note: Resideo uses site token `CX`, not `CX_1001` like ON Semiconductor in Part 8.

### `test_pinpoint(company, postings_url)`

```text
GET https://careers.brivo.com/postings.json
Parser: data[].title, .url, .location
US filter: location.city/state/country/name
URL: item["url"]
```

Used by: Brivo.

Lowest-risk Part 10 adapter — single JSON GET, no auth.

### `test_gem(company, board_id)`

```text
POST https://jobs.gem.com/api/public/graphql
operationName: JobBoardList
variables: {"boardId": board_id}
Query selection: oatsExternalJobPostings { jobPostings { title extId locations { name } } }
US filter: locations[].name
URL: https://jobs.gem.com/{board_id}/{extId}
```

Used by: Wyze (`wyzecam-com`).

The real script should also use `ExternalJobPostingQuery` for full description on detail fetch.

### `test_greenhouse(company, board)`

Same as Part 7/8/9:

```text
GET boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true
Sort: updated_at descending
US filter: location.name + offices[].name
URL: absolute_url
```

Used by: GoPro (`goprocareers`).

---

## Part 10 Adapter Summary

### Wabtec (rank 91)

```text
Source: SmartRecruiters API
Method: requests
Slug: Wabtec
Date field: releasedDate
URL: jobs.smartrecruiters.com/Wabtec/{id}
Live: ok, count=36
```

### Resideo (rank 92)

```text
Source: Oracle CE API
Method: requests
Host: ehtl.fa.us6.oraclecloud.com
Site: CX
Date field: PostedDate
URL: hcmUI/CandidateExperience/en/sites/CX/job/{Id}
Live: ok, count=24
```

### Brivo (rank 93)

```text
Source: Pinpoint postings.json
Method: requests
Endpoint: careers.brivo.com/postings.json
Date field: not in JSON (detail schema.org or RSS)
URL: careers.brivo.com/en/postings/{uuid}
Live: ok, count=13
```

### Wyze (rank 94)

```text
Source: Gem public GraphQL
Method: requests
Board: wyzecam-com
Date field: on ExternalJobPostingQuery detail (not in list query)
URL: jobs.gem.com/wyzecam-com/{extId}
Live: ok, count=9
```

### GoPro (rank 95)

```text
Source: Greenhouse API
Method: requests
Board: goprocareers
Date field: updated_at
URL: jobs.gopro.com/jobs/?gh_jid={id}
Live: ok, count=1
```

---

## Location and Date Field Notes

| Company | Location fields used by tester | Date fields in source |
|---|---|---|
| Wabtec | location.fullLocation, location.country | releasedDate |
| Resideo | PrimaryLocationCountry, PrimaryLocation | PostedDate |
| Brivo | location object (city, state, country) | datePosted on detail only |
| Wyze | locations[].name | detail GraphQL |
| GoPro | location.name, offices[] | updated_at |

---

## Known Caveats (Tester vs Real Script)

```text
GoPro: very few active roles; count=1 is valid ok.
Brivo: postings.json has no posted date; use detail schema.org or jobs.rss pubDate.
Wyze: list GraphQL is minimal; real script needs ExternalJobPostingQuery for description.
Resideo: Oracle host and site CX are company-specific; do not reuse ON Semi CX_1001 host.
Wabtec: SR feed mixes manufacturing and engineering; real script filters on detail text.
```

---

## Live Verification Summary

Run date: 2026-06-22

```text
5/5 ok
```

All companies returned count > 0 with official or source-backed sample URLs.

---

## Future Pipeline Mapping

```text
test_smartrecruiters -> Wabtec SR list + detail API
test_oracle          -> Resideo Oracle CE list + ById detail
test_pinpoint        -> Brivo JSON list + detail schema.org
test_gem             -> Wyze Gem list + ExternalJobPostingQuery
test_greenhouse      -> GoPro GH list + detail content
```

Part 10 completes the ranked company source-discovery tester series (Parts 1–10, ranks 1–95).
