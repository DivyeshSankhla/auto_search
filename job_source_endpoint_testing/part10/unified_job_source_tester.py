#!/usr/bin/env python3
"""
Unified simple job-source tester for Part 10 companies.

Purpose:
  Test official source access methods intended for job_search_10.

This tester fetches recent/top official records first. It does not score jobs,
append to a ledger, or run profile keyword searches.
"""

from __future__ import annotations

import html
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple


USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

TIMEOUT = 15
LIMIT = int(os.environ.get("JOB_SOURCE_TEST_LIMIT", "50"))
REQUEST_DELAY = 0.1
RETRY_STATUSES = {429, 500, 502, 503, 504}
US_STATE_TEXT = (
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
    "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana",
    "maine", "maryland", "massachusetts", "michigan", "minnesota",
    "mississippi", "missouri", "montana", "nebraska", "nevada",
    "new hampshire", "new jersey", "new mexico", "new york",
    "north carolina", "north dakota", "ohio", "oklahoma", "oregon",
    "pennsylvania", "rhode island", "south carolina", "south dakota",
    "tennessee", "texas", "utah", "vermont", "virginia", "washington",
    "west virginia", "wisconsin", "wyoming",
)
US_STATE_ABBR = (
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga", "hi", "id",
    "il", "in", "ia", "ks", "ky", "la", "me", "md", "ma", "mi", "mn", "ms",
    "mo", "mt", "ne", "nv", "nh", "nj", "nm", "ny", "nc", "nd", "oh", "ok",
    "or", "pa", "ri", "sc", "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv",
    "wi", "wy",
)

GEM_JOB_BOARD_QUERY = """
query JobBoardList($boardId: String!) {
  oatsExternalJobPostings(boardId: $boardId) {
    jobPostings {
      title
      extId
      locations {
        name
      }
    }
  }
}
""".strip()


@dataclass
class Result:
    company: str
    method: str
    status: str
    count: int
    sample_title: str = ""
    sample_url: str = ""


def clean_text(raw: str) -> str:
    raw = html.unescape(raw or "")
    raw = raw.replace("\xa0", " ")
    raw = re.sub(r"<script[\s\S]*?</script>", " ", raw, flags=re.I)
    raw = re.sub(r"<style[\s\S]*?</style>", " ", raw, flags=re.I)
    raw = re.sub(r"<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", raw).strip()


def http_get(url: str, accept: str = "application/json,text/html,*/*", headers: Optional[Dict[str, str]] = None) -> Tuple[Optional[int], str]:
    req_headers = {"User-Agent": USER_AGENT, "Accept": accept, "Accept-Language": "en-US,en;q=0.9"}
    if headers:
        req_headers.update(headers)
    for attempt in range(3):
        req = urllib.request.Request(url, headers=req_headers)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return resp.status, resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            try:
                body = exc.read().decode("utf-8", errors="replace")
            except Exception:
                body = ""
            if exc.code in RETRY_STATUSES and attempt < 2:
                time.sleep(0.5 * (attempt + 1))
                continue
            return exc.code, body
        except Exception:
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
                continue
            return None, ""
    return None, ""


def http_post_json(url: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> Tuple[Optional[int], str]:
    data = json.dumps(payload).encode("utf-8")
    req_headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json,text/html,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Content-Type": "application/json",
    }
    if headers:
        req_headers.update(headers)
    for attempt in range(3):
        req = urllib.request.Request(url, data=data, method="POST", headers=req_headers)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return resp.status, resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            try:
                body = exc.read().decode("utf-8", errors="replace")
            except Exception:
                body = ""
            if exc.code in RETRY_STATUSES and attempt < 2:
                time.sleep(0.5 * (attempt + 1))
                continue
            return exc.code, body
        except Exception:
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
                continue
            return None, ""
    return None, ""


def load_json(body: str) -> Any:
    try:
        return json.loads(body)
    except Exception:
        return None


def status_from(code: Optional[int], count: int) -> str:
    if count > 0:
        return "ok"
    if code == 403:
        return "blocked"
    if code is None:
        return "failed"
    if code == 200:
        return "parser_failed"
    return f"http_{code}"


def is_us_text(value: Any) -> bool:
    text = clean_text(str(value or "")).lower()
    if not text:
        return False
    if "united states" in text or "north america" in text or "americas" in text:
        return True
    if re.search(r"(?<![a-z])u\.?s\.?a\.?(?![a-z])", text) or re.search(r"(?<![a-z])us(?![a-z])", text):
        return True
    if any(re.search(r"(?<![a-z])" + re.escape(state) + r"(?![a-z])", text) for state in US_STATE_TEXT):
        return True
    return any(re.search(r"(^|[\s,(])" + abbr + r"($|[\s,)])", text) for abbr in US_STATE_ABBR)


def first_text(*values: Any) -> str:
    for value in values:
        if value:
            return clean_text(str(value))
    return ""


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "job"


def unique_by(items: Iterable[Any], key_func) -> List[Any]:
    seen = set()
    out = []
    for item in items:
        key = key_func(item)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= LIMIT:
            break
    return out


def pinpoint_location_text(item: Dict[str, Any]) -> str:
    location = item.get("location")
    if isinstance(location, dict):
        return " ".join(str(location.get(key) or "") for key in ("city", "state", "country", "name"))
    return str(location or "")


def test_pinpoint(company: str, postings_url: str) -> Result:
    code, body = http_get(postings_url, accept="application/json,*/*")
    data = load_json(body)
    jobs: List[Dict[str, Any]] = []
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        jobs = data["data"]
    elif isinstance(data, list):
        jobs = data
    us_jobs = [job for job in jobs if is_us_text(pinpoint_location_text(job))]
    unique = unique_by(us_jobs or jobs, lambda job: str(job.get("url") or job.get("id") or job.get("title") or ""))
    first = unique[0] if unique else {}
    return Result(company, "requests", status_from(code, len(unique)), len(unique), first_text(first.get("title")), str(first.get("url") or ""))


def gem_location_text(job: Dict[str, Any]) -> str:
    parts = []
    for loc in job.get("locations", []) or []:
        if isinstance(loc, dict):
            parts.append(str(loc.get("name") or ""))
        else:
            parts.append(str(loc))
    return " ".join(parts)


def test_gem(company: str, board_id: str) -> Result:
    payload = {
        "operationName": "JobBoardList",
        "variables": {"boardId": board_id},
        "query": GEM_JOB_BOARD_QUERY,
    }
    code, body = http_post_json("https://jobs.gem.com/api/public/graphql", payload)
    data = load_json(body)
    jobs: List[Dict[str, Any]] = []
    if isinstance(data, dict):
        postings = data.get("data", {}).get("oatsExternalJobPostings", {})
        if isinstance(postings, dict):
            raw = postings.get("jobPostings", [])
            jobs = raw if isinstance(raw, list) else []

    us_jobs = [job for job in jobs if is_us_text(gem_location_text(job))]
    unique = unique_by(us_jobs or jobs, lambda job: str(job.get("extId") or job.get("title") or ""))
    first = unique[0] if unique else {}
    ext_id = str(first.get("extId") or "")
    sample_url = f"https://jobs.gem.com/{board_id}/{ext_id}" if ext_id else f"https://jobs.gem.com/{board_id}"
    return Result(company, "requests", status_from(code, len(unique)), len(unique), first_text(first.get("title")), sample_url)


def oracle_url(host: str, site: str, offset: int, limit: int = 25) -> str:
    finder = (
        f"findReqs;siteNumber={site},"
        "facetsList=LOCATIONS%3BWORK_LOCATIONS%3BTITLES%3BCATEGORIES%3BORGANIZATIONS%3BPOSTING_DATES%3BFLEX_FIELDS,"
        f"limit={limit},offset={offset},sortBy=POSTING_DATES_DESC"
    )
    return (
        f"{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions?"
        "onlyData=true&expand=requisitionList.secondaryLocations,flexFieldsFacet.values,requisitionList.requisitionFlexFields&finder="
        + finder
    )


def test_oracle(company: str, host: str, site: str, public_base: str) -> Result:
    jobs: List[Dict[str, Any]] = []
    last_code = None
    for offset in range(0, LIMIT, 25):
        code, body = http_get(oracle_url(host, site, offset), accept="application/json,*/*")
        last_code = code
        if code != 200:
            break
        data = load_json(body)
        items = data.get("items", []) if isinstance(data, dict) else []
        batch = items[0].get("requisitionList", []) if items and isinstance(items[0], dict) else []
        if not isinstance(batch, list) or not batch:
            break
        jobs.extend(batch)
        if len(jobs) >= LIMIT:
            break
        time.sleep(REQUEST_DELAY)

    us_jobs = [job for job in jobs if is_us_text(job.get("PrimaryLocationCountry")) or is_us_text(job.get("PrimaryLocation"))]
    unique = unique_by(us_jobs or jobs, lambda job: str(job.get("Id") or job.get("Title") or ""))
    first = unique[0] if unique else {}
    job_id = str(first.get("Id") or "")
    sample_url = f"{public_base}/job/{job_id}" if job_id else public_base
    return Result(company, "requests", status_from(last_code, len(unique)), len(unique), first_text(first.get("Title")), sample_url)


def greenhouse_location_text(job: Dict[str, Any]) -> str:
    parts = [str((job.get("location") or {}).get("name") or "")]
    parts.extend(str(office.get("name") or "") for office in job.get("offices", []) if isinstance(office, dict))
    return " ".join(parts)


def greenhouse_sort_key(job: Dict[str, Any]) -> str:
    return str(job.get("updated_at") or job.get("created_at") or job.get("first_published") or "")


def test_greenhouse(company: str, board: str) -> Result:
    url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true"
    code, body = http_get(url)
    data = load_json(body)
    jobs = data.get("jobs", []) if isinstance(data, dict) else []
    jobs = jobs if isinstance(jobs, list) else []
    jobs.sort(key=greenhouse_sort_key, reverse=True)
    us_jobs = [job for job in jobs if is_us_text(greenhouse_location_text(job))]
    unique = unique_by(us_jobs or jobs, lambda job: str(job.get("id") or job.get("absolute_url") or ""))
    first = unique[0] if unique else {}
    return Result(company, "requests", status_from(code, len(unique)), len(unique), first_text(first.get("title")), str(first.get("absolute_url") or ""))


def smartrecruiters_public_url(job: Dict[str, Any], public_company: str) -> str:
    job_id = str(job.get("id") or "")
    if job_id:
        return f"https://jobs.smartrecruiters.com/{public_company}/{job_id}"
    ref = str(job.get("refNumber") or "")
    name = first_text(job.get("name"))
    if ref and name:
        return f"https://jobs.smartrecruiters.com/{public_company}/{ref}-{slugify(name)}"
    return str(job.get("ref") or "")


def test_smartrecruiters(company: str, company_slug: str, public_company: str) -> Result:
    jobs: List[Dict[str, Any]] = []
    last_code = None
    for offset in range(0, LIMIT, 20):
        params = {"limit": str(min(20, LIMIT - offset)), "offset": str(offset)}
        url = f"https://api.smartrecruiters.com/v1/companies/{company_slug}/postings?" + urllib.parse.urlencode(params)
        code, body = http_get(url, accept="application/json,*/*")
        last_code = code
        if code != 200:
            break
        data = load_json(body)
        batch = data.get("content", []) if isinstance(data, dict) else []
        if not isinstance(batch, list) or not batch:
            break
        jobs.extend(batch)
        if len(jobs) >= LIMIT:
            break
        time.sleep(REQUEST_DELAY)

    jobs.sort(key=lambda job: str(job.get("releasedDate") or ""), reverse=True)
    us_jobs = [
        job
        for job in jobs
        if is_us_text((job.get("location") or {}).get("fullLocation"))
        or is_us_text((job.get("location") or {}).get("country"))
    ]
    unique = unique_by(us_jobs or jobs, lambda job: str(job.get("id") or job.get("uuid") or job.get("refNumber") or ""))
    first = unique[0] if unique else {}
    return Result(
        company,
        "requests",
        status_from(last_code, len(unique)),
        len(unique),
        first_text(first.get("name")),
        smartrecruiters_public_url(first, public_company),
    )


def print_table(results: List[Result]) -> None:
    headers = ["Company", "Method", "Status", "Count", "Sample title", "Sample URL / Note"]
    rows = [[r.company, r.method, r.status, str(r.count), r.sample_title[:50], r.sample_url[:95]] for r in results]
    widths = [len(h) for h in headers]
    for row in rows:
        for i, value in enumerate(row):
            widths[i] = max(widths[i], len(value))
    fmt = " | ".join("{:<" + str(w) + "}" for w in widths)
    print(fmt.format(*headers))
    print("-+-".join("-" * w for w in widths))
    for row in rows:
        print(fmt.format(*row))


def main() -> int:
    tests = [
        lambda: test_smartrecruiters("Wabtec", "Wabtec", "Wabtec"),
        lambda: test_oracle(
            "Resideo",
            "https://ehtl.fa.us6.oraclecloud.com",
            "CX",
            "https://ehtl.fa.us6.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX",
        ),
        lambda: test_pinpoint("Brivo", "https://careers.brivo.com/postings.json"),
        lambda: test_gem("Wyze", "wyzecam-com"),
        lambda: test_greenhouse("GoPro", "goprocareers"),
    ]
    results = [test() for test in tests]
    print_table(results)
    failed = [r for r in results if r.status != "ok"]
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
