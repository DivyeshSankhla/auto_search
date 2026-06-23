#!/usr/bin/env python3
"""
Unified simple job-source tester for Part 4 companies.

Purpose:
  Test official source access methods intended for job_search_4.

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

TIMEOUT = 12
LIMIT = int(os.environ.get("JOB_SOURCE_TEST_LIMIT", "50"))
REQUEST_DELAY = 0.1
RETRY_STATUSES = {429, 500, 502, 503, 504}
US_STATE_TEXT = (
    "alabama",
    "alaska",
    "arizona",
    "arkansas",
    "california",
    "colorado",
    "connecticut",
    "delaware",
    "florida",
    "georgia",
    "hawaii",
    "idaho",
    "illinois",
    "indiana",
    "iowa",
    "kansas",
    "kentucky",
    "louisiana",
    "maine",
    "maryland",
    "massachusetts",
    "michigan",
    "minnesota",
    "mississippi",
    "missouri",
    "montana",
    "nebraska",
    "nevada",
    "new hampshire",
    "new jersey",
    "new mexico",
    "new york",
    "north carolina",
    "north dakota",
    "ohio",
    "oklahoma",
    "oregon",
    "pennsylvania",
    "rhode island",
    "south carolina",
    "south dakota",
    "tennessee",
    "texas",
    "utah",
    "vermont",
    "virginia",
    "washington",
    "west virginia",
    "wisconsin",
    "wyoming",
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
    req_headers = {
        "User-Agent": USER_AGENT,
        "Accept": accept,
        "Accept-Language": "en-US,en;q=0.9",
    }
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
    if "united states" in text or re.search(r"(?<![a-z])u\.?s\.?a\.?(?![a-z])", text) or re.search(r"(?<![a-z])us(?![a-z])", text):
        return True
    return any(re.search(r"(?<![a-z])" + re.escape(state) + r"(?![a-z])", text) for state in US_STATE_TEXT)


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
        payload = {
            "appliedFacets": applied,
            "limit": min(20, LIMIT - offset),
            "offset": offset,
            "searchText": "",
            "sortBy": "postedOn",
        }
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


def parse_searchjobs_cards(body: str, host: str) -> List[Tuple[str, str, str]]:
    cards = []
    article_pattern = re.compile(r"<article\b[\s\S]*?</article>", flags=re.I)
    link_re = re.compile(r'href=["\'](?P<href>https://%s/[^"\']*/JobDetail/(?P<id>\d+))["\']' % re.escape(host), flags=re.I)
    for article in article_pattern.findall(body):
        link_match = link_re.search(article)
        title_match = re.search(r'<a[^>]*class=["\']link["\'][^>]*href=["\'][^"\']*/JobDetail/\d+["\'][^>]*>(?P<title>.*?)</a>', article, flags=re.I | re.S)
        loc_match = re.search(r'<span class=["\']list-item-location["\']>(?P<loc>.*?)</span>', article, flags=re.I | re.S)
        if link_match:
            cards.append((
                clean_text(title_match.group("title")) if title_match else f"Job {link_match.group('id')}",
                link_match.group("href"),
                clean_text(loc_match.group("loc")) if loc_match else "",
            ))
    if cards:
        return cards

    links = re.findall(r"https://%s/[^\"'< ]*/JobDetail/\d+" % re.escape(host), body)
    return [(f"Job {url.rsplit('/', 1)[-1]}", url, "") for url in links]


def test_searchjobs(company: str, base_url: str, host: str) -> Result:
    jobs: List[Tuple[str, str, str]] = []
    last_code = None
    for offset in range(0, LIMIT, 6):
        params = {"folderRecordsPerPage": "6", "folderOffset": str(offset), "folderSort": "postedDate", "folderSortDirection": "desc"}
        url = base_url + "?" + urllib.parse.urlencode(params)
        code, body = http_get(url, accept="text/html,*/*")
        last_code = code
        if code != 200:
            break
        jobs.extend(parse_searchjobs_cards(body, host))
        if len(jobs) >= LIMIT:
            break
        time.sleep(REQUEST_DELAY)
    unique = unique_by(jobs, lambda item: item[1])
    sample = unique[0] if unique else ("", "", "")
    return Result(company, "requests", status_from(last_code, len(unique)), len(unique), sample[0], sample[1])


def canonical_from_jibe(job: Dict[str, Any], base: str) -> str:
    data = job.get("data", job)
    meta = data.get("meta_data") if isinstance(data.get("meta_data"), dict) else {}
    url = str(meta.get("canonical_url") or data.get("canonical_url") or data.get("url") or "")
    if url:
        return absolute(url, base)
    req_id = str(data.get("req_id") or data.get("id") or "")
    return f"{base}/jobs/{req_id}?lang=en-us" if req_id else ""


def test_jibe(company: str, base: str, api_url: str) -> Result:
    params = {"page": "1", "limit": str(LIMIT), "sortBy": "posted_date", "descending": "true", "country": "United States"}
    code, body = http_get(api_url + "?" + urllib.parse.urlencode(params))
    data = load_json(body)
    jobs = data.get("jobs", []) if isinstance(data, dict) else []
    jobs = jobs if isinstance(jobs, list) else []
    unique = unique_by(jobs, lambda job: str((job.get("data", job) if isinstance(job, dict) else {}).get("req_id") or canonical_from_jibe(job, base)))
    first = unique[0].get("data", unique[0]) if unique and isinstance(unique[0], dict) else {}
    return Result(company, "requests", status_from(code, len(unique)), len(unique), first_text(first.get("title")), canonical_from_jibe(unique[0], base) if unique else "")


def test_eightfold_pcs(company: str, base: str, domain: str) -> Result:
    params = {"domain": domain, "query": "", "location": "United States", "start": "0", "num": str(LIMIT)}
    code, body = http_get(base + "/api/pcsx/search?" + urllib.parse.urlencode(params), headers={"Referer": base + "/careers"})
    data = load_json(body)
    positions = []
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        positions = data["data"].get("positions", [])
    positions = positions if isinstance(positions, list) else []
    jobs = [job for job in positions if "do no apply" not in first_text(job.get("name")).lower()]
    unique = unique_by(jobs, lambda job: str(job.get("id") or job.get("displayJobId") or job.get("positionUrl") or ""))
    first = unique[0] if unique else {}
    sample_url = absolute(str(first.get("positionUrl") or ""), base)
    return Result(company, "requests", status_from(code, len(unique)), len(unique), first_text(first.get("name")), sample_url)


def parse_static_job_links(body: str, base: str, href_pattern: str) -> List[Tuple[str, str]]:
    jobs = []
    for match in re.finditer(r'href=["\'](?P<href>%s)["\'][^>]*>(?P<title>.*?)</a>' % href_pattern, body, flags=re.I | re.S):
        title = clean_text(match.group("title"))
        url = absolute(html.unescape(match.group("href")), base)
        if title and url:
            jobs.append((title, url))
    return jobs


def test_caterpillar() -> Result:
    code, body = http_get("https://careers.caterpillar.com/en/jobs/xml/?rss=true", accept="application/xml,text/xml,*/*")
    jobs = []
    for block in re.findall(r"<job>[\s\S]*?</job>", body):
        title_match = re.search(r"<title><!\[CDATA\[(?P<title>[\s\S]*?)\]\]></title>", block)
        url_match = re.search(r"<url><!\[CDATA\[(?P<url>[\s\S]*?)\]\]></url>", block)
        country_match = re.search(r"<country><!\[CDATA\[(?P<country>[\s\S]*?)\]\]></country>", block)
        if not title_match or not url_match:
            continue
        if country_match and not is_us_text(country_match.group("country")):
            continue
        jobs.append((clean_text(title_match.group("title")), clean_text(url_match.group("url"))))
    unique = unique_by(jobs, lambda item: item[1])
    sample = unique[0] if unique else ("", "")
    return Result("Caterpillar", "requests", status_from(code, len(unique)), len(unique), sample[0], sample[1])


def test_john_deere() -> Result:
    jobs: List[Tuple[str, str]] = []
    last_code = None
    for startrow in range(0, LIMIT, 25):
        params = {
            "q": "",
            "locationsearch": "United States",
            "sortColumn": "referencedate",
            "sortDirection": "desc",
            "startrow": str(startrow),
        }
        url = "https://jobs.deere.com/search/?" + urllib.parse.urlencode(params)
        code, body = http_get(url, accept="text/html,*/*")
        last_code = code
        if code != 200:
            break
        jobs.extend(parse_static_job_links(body, "https://jobs.deere.com", r"/(?:eightfold|successfactors)/job/[^\"']+"))
        if len(unique_by(jobs, lambda item: item[1])) >= LIMIT:
            break
        time.sleep(REQUEST_DELAY)
    unique = unique_by(jobs, lambda item: item[1])
    sample = unique[0] if unique else ("", "")
    return Result("John Deere", "requests", status_from(last_code, len(unique)), len(unique), sample[0], sample[1])


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
        lambda: test_workday(
            "Medtronic",
            "https://medtronic.wd1.myworkdayjobs.com/wday/cxs/medtronic/MedtronicCareers/jobs",
            "https://medtronic.wd1.myworkdayjobs.com/MedtronicCareers",
        ),
        lambda: test_workday(
            "Intuitive Surgical",
            "https://intuitive.wd1.myworkdayjobs.com/wday/cxs/intuitive/irtc_careers/jobs",
            "https://intuitive.wd1.myworkdayjobs.com/irtc_careers",
        ),
        lambda: test_workday(
            "GE HealthCare",
            "https://gehc.wd5.myworkdayjobs.com/wday/cxs/gehc/GEHC_ExternalSite/jobs",
            "https://gehc.wd5.myworkdayjobs.com/GEHC_ExternalSite",
        ),
        lambda: test_searchjobs(
            "Siemens Healthineers",
            "https://jobs.siemens-healthineers.com/en_US/searchjobs/SearchJobs",
            "jobs.siemens-healthineers.com",
        ),
        lambda: test_workday(
            "Dexcom",
            "https://dexcom.wd1.myworkdayjobs.com/wday/cxs/dexcom/Dexcom/jobs",
            "https://dexcom.wd1.myworkdayjobs.com/Dexcom",
        ),
        lambda: test_workday(
            "Rockwell Automation",
            "https://rockwellautomation.wd1.myworkdayjobs.com/wday/cxs/rockwellautomation/External_Rockwell_Automation/jobs",
            "https://rockwellautomation.wd1.myworkdayjobs.com/External_Rockwell_Automation",
        ),
        lambda: test_jibe("Schneider Electric", "https://careers.se.com", "https://careers.se.com/api/jobs"),
        lambda: test_eightfold_pcs("Eaton", "https://eaton.eightfold.ai", "eaton.com"),
        test_caterpillar,
        test_john_deere,
    ]
    results = [test() for test in tests]
    print_table(results)
    failed = [r for r in results if r.status != "ok"]
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
