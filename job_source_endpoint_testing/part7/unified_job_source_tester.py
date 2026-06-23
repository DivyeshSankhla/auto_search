#!/usr/bin/env python3
"""
Unified simple job-source tester for Part 7 companies.

Purpose:
  Test official source access methods intended for job_search_7.

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


def http_post_json(url: str, payload: Dict[str, Any]) -> Tuple[Optional[int], str]:
    data = json.dumps(payload).encode("utf-8")
    for attempt in range(3):
        req = urllib.request.Request(
            url,
            data=data,
            method="POST",
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json,text/html,*/*",
                "Accept-Language": "en-US,en;q=0.9",
                "Content-Type": "application/json",
            },
        )
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


def absolute(url: str, base: str) -> str:
    return urllib.parse.urljoin(base, url or "")


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


def iter_workday_facets(node: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(node, dict):
        if isinstance(node.get("facetParameter"), str) and isinstance(node.get("values"), list):
            yield node
        for value in node.values():
            yield from iter_workday_facets(value)
    elif isinstance(node, list):
        for item in node:
            yield from iter_workday_facets(item)


def discover_workday_us_facet(endpoint: str) -> Tuple[Optional[int], str, List[str]]:
    code, body = http_post_json(endpoint, {"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""})
    data = load_json(body)
    if not isinstance(data, dict):
        return code, "", []

    matches: List[Tuple[str, List[str]]] = []
    for facet in iter_workday_facets(data.get("facets", [])):
        param = str(facet.get("facetParameter") or "")
        ids = []
        values = facet.get("values", [])
        if isinstance(values, list):
            for value in values:
                if isinstance(value, dict) and is_us_text(value.get("descriptor")) and value.get("id"):
                    ids.append(str(value["id"]))
        if ids and param:
            matches.append((param, ids))

    country_matches = [(param, ids) for param, ids in matches if "country" in param.lower().replace("_", "")]
    if country_matches:
        return code, country_matches[0][0], country_matches[0][1]
    return (code, matches[0][0], matches[0][1]) if matches else (code, "", [])


def test_workday(company: str, endpoint: str, public_base: str) -> Result:
    facet_code, facet_param, us_ids = discover_workday_us_facet(endpoint)
    applied = {facet_param: us_ids} if facet_param and us_ids else {}
    jobs: List[Dict[str, Any]] = []
    last_code = facet_code
    for offset in range(0, LIMIT, 20):
        payload = {"appliedFacets": applied, "limit": min(20, LIMIT - offset), "offset": offset, "searchText": "", "sortBy": "postedOn"}
        code, body = http_post_json(endpoint, payload)
        last_code = code
        if code != 200:
            break
        data = load_json(body)
        batch = data.get("jobPostings", []) if isinstance(data, dict) else []
        if not isinstance(batch, list) or not batch:
            break
        jobs.extend(batch)
        if len(jobs) >= LIMIT:
            break
        time.sleep(REQUEST_DELAY)

    unique = unique_by(jobs, lambda job: str(job.get("externalPath") or job.get("title") or ""))
    first = unique[0] if unique else {}
    external = str(first.get("externalPath") or "")
    sample_url = public_base + external if external.startswith("/") else absolute(external, public_base)
    return Result(company, "requests", status_from(last_code, len(unique)), len(unique), first_text(first.get("title")), sample_url)


def greenhouse_location_text(job: Dict[str, Any]) -> str:
    parts = [str((job.get("location") or {}).get("name") or "")]
    parts.extend(str(office.get("name") or "") for office in job.get("offices", []) if isinstance(office, dict))
    return " ".join(parts)


def greenhouse_sort_key(job: Dict[str, Any]) -> str:
    return str(job.get("updated_at") or job.get("created_at") or job.get("first_published") or "")


def parse_greenhouse_board(company: str, board: str) -> Result:
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


def test_greenhouse(company: str, board: str) -> Result:
    return parse_greenhouse_board(company, board)


def test_may_mobility() -> Result:
    primary = parse_greenhouse_board("May Mobility", "maymobility")
    if primary.count > 0:
        return primary
    return parse_greenhouse_board("May Mobility", "maymobilityjobs")


def ashby_location_text(job: Dict[str, Any]) -> str:
    parts = [str(job.get("location") or "")]
    address = job.get("address")
    if isinstance(address, dict):
        postal = address.get("postalAddress")
        if isinstance(postal, dict):
            parts.extend(str(postal.get(key) or "") for key in ("addressLocality", "addressRegion", "addressCountry"))
    for loc in job.get("secondaryLocations", []) or []:
        if isinstance(loc, dict):
            parts.append(str(loc.get("location") or loc.get("name") or ""))
            addr = loc.get("address")
            if isinstance(addr, dict):
                postal = addr.get("postalAddress")
                if isinstance(postal, dict):
                    parts.extend(str(postal.get(key) or "") for key in ("addressLocality", "addressRegion", "addressCountry"))
        else:
            parts.append(str(loc))
    return " ".join(parts)


def test_ashby(company: str, board: str) -> Result:
    url = f"https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true"
    code, body = http_get(url)
    data = load_json(body)
    jobs = data.get("jobs", []) if isinstance(data, dict) else []
    jobs = jobs if isinstance(jobs, list) else []
    jobs.sort(key=lambda job: str(job.get("publishedAt") or ""), reverse=True)
    us_jobs = [job for job in jobs if is_us_text(ashby_location_text(job))]
    unique = unique_by(us_jobs or jobs, lambda job: str(job.get("id") or job.get("jobUrl") or ""))
    first = unique[0] if unique else {}
    return Result(company, "requests", status_from(code, len(unique)), len(unique), first_text(first.get("title")), str(first.get("jobUrl") or ""))


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
        lambda: test_greenhouse("Nuro", "nuro"),
        lambda: test_greenhouse("Kodiak Robotics", "kodiak"),
        lambda: test_greenhouse("Gatik", "gatikaiinc"),
        lambda: test_may_mobility(),
        lambda: test_greenhouse("Avride", "avride"),
        lambda: test_ashby("Serve Robotics", "serverobotics"),
        lambda: test_ashby("Gecko Robotics", "gecko-robotics"),
        lambda: test_greenhouse("Skild AI", "skildai-careers"),
        lambda: test_workday(
            "Motorola Solutions / Avigilon",
            "https://motorolasolutions.wd5.myworkdayjobs.com/wday/cxs/motorolasolutions/Careers/jobs",
            "https://motorolasolutions.wd5.myworkdayjobs.com/Careers",
        ),
        lambda: test_workday(
            "Zebra Technologies",
            "https://zebra.wd501.myworkdayjobs.com/wday/cxs/zebra/Zebra_careers/jobs",
            "https://zebra.wd501.myworkdayjobs.com/Zebra_careers",
        ),
    ]
    results = [test() for test in tests]
    print_table(results)
    failed = [r for r in results if r.status != "ok"]
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
