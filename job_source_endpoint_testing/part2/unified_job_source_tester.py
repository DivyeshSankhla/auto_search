#!/usr/bin/env python3
"""
Unified simple job-source tester for Part 2 companies.

Purpose:
  Test the exact official source access methods intended for job_search_2.

This tester fetches recent/top official records first. It does not run
profile keyword searches, score jobs, enrich detail pages, or append to a
ledger. Relevance filtering belongs in the real job_search_2 script.

Run:
  python3 unified_job_source_tester.py

Output:
  company | method | status | count | sample title | sample url
"""

from __future__ import annotations

import html
import json
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

TIMEOUT = 25
LIMIT = 50
REQUEST_DELAY = 0.1
US_LOCATION_TEXT = ("united states", "united states of america", "usa", "us,", "us ")


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


def http_get(url: str, accept: str = "application/json,text/html,*/*") -> Tuple[Optional[int], str]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": accept,
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        return e.code, body
    except Exception:
        return None, ""


def http_post_json(url: str, payload: Dict[str, Any]) -> Tuple[Optional[int], str]:
    data = json.dumps(payload).encode("utf-8")
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
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        return e.code, body
    except Exception:
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


def first_text(*values: Any) -> str:
    for value in values:
        if value:
            return clean_text(str(value))
    return ""


def title_from_url(url: str) -> str:
    slug = urllib.parse.urlparse(url).path.rstrip("/").split("/")[-1]
    slug = re.sub(r"[-_]+", " ", slug)
    return clean_text(slug).title()


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "job"


def is_us_text(value: Any) -> bool:
    text = clean_text(str(value or "")).lower()
    return any(token in text for token in US_LOCATION_TEXT)


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


def canonical_from_jibe(job: Dict[str, Any], base: str) -> str:
    data = job.get("data", job)
    meta = data.get("meta_data") if isinstance(data.get("meta_data"), dict) else {}
    url = str(meta.get("canonical_url") or data.get("canonical_url") or data.get("url") or "")
    if url:
        return absolute(url, base)
    req_id = str(data.get("req_id") or data.get("id") or "")
    return f"{base}/jobs/{req_id}?lang=en-us" if req_id else ""


def test_jibe(company: str, base: str, api_url: str) -> Result:
    params = {
        "page": "1",
        "sortBy": "posted_date",
        "descending": "true",
        "country": "United States",
    }
    url = api_url + "?" + urllib.parse.urlencode(params)
    code, body = http_get(url)
    data = load_json(body)
    jobs = data.get("jobs", []) if isinstance(data, dict) else []
    jobs = jobs if isinstance(jobs, list) else []

    unique = unique_by(
        jobs,
        lambda job: str((job.get("data", job) if isinstance(job, dict) else {}).get("req_id") or canonical_from_jibe(job, base)),
    )

    first = unique[0].get("data", unique[0]) if unique and isinstance(unique[0], dict) else {}
    return Result(
        company,
        "requests",
        status_from(code, len(unique)),
        len(unique),
        first_text(first.get("title")),
        canonical_from_jibe(unique[0], base) if unique else "",
    )


def iter_workday_facets(node: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(node, dict):
        if isinstance(node.get("facetParameter"), str) and isinstance(node.get("values"), list):
            yield node
        for value in node.values():
            yield from iter_workday_facets(value)
    elif isinstance(node, list):
        for item in node:
            yield from iter_workday_facets(item)


def workday_us_ids_for_facet(facet: Dict[str, Any]) -> List[str]:
    ids: List[str] = []
    values = facet.get("values", [])
    if not isinstance(values, list):
        return ids

    for value in values:
        if not isinstance(value, dict):
            continue
        descriptor = str(value.get("descriptor") or "")
        location_id = str(value.get("id") or "")
        if location_id and is_us_text(descriptor) and location_id not in ids:
            ids.append(location_id)
    return ids


def discover_workday_us_facet(endpoint: str) -> Tuple[Optional[int], str, List[str]]:
    payload = {"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""}
    code, body = http_post_json(endpoint, payload)
    data = load_json(body)
    if not isinstance(data, dict):
        return code, "", []

    country_matches: List[Tuple[str, List[str]]] = []
    location_matches: List[Tuple[str, List[str]]] = []
    for facet in iter_workday_facets(data.get("facets", [])):
        param = str(facet.get("facetParameter") or "")
        ids = workday_us_ids_for_facet(facet)
        if not param or not ids:
            continue
        normalized = param.lower().replace("_", "")
        if "country" in normalized:
            country_matches.append((param, ids))
        elif normalized in {"location", "locations"}:
            location_matches.append((param, ids))

    if country_matches:
        param, ids = country_matches[0]
        return code, param, ids
    if location_matches:
        param, ids = location_matches[0]
        return code, param, ids
    return code, "", []


def test_workday(company: str, endpoint: str, public_base: str) -> Result:
    jobs: List[Dict[str, Any]] = []
    facet_code, facet_param, us_location_ids = discover_workday_us_facet(endpoint)
    applied_facets = {facet_param: us_location_ids} if facet_param and us_location_ids else {}
    last_code = facet_code

    for offset in range(0, LIMIT, 20):
        payload = {
            "appliedFacets": applied_facets,
            "limit": min(20, LIMIT - offset),
            "offset": offset,
            "searchText": "",
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
        total = data.get("total") if isinstance(data, dict) else None
        if isinstance(total, int) and offset + 20 >= total:
            break
        if len(jobs) >= LIMIT:
            break
        time.sleep(REQUEST_DELAY)

    unique = unique_by(jobs, lambda job: str(job.get("externalPath") or job.get("title") or ""))
    first = unique[0] if unique else {}
    external = str(first.get("externalPath") or "")
    sample_url = public_base + external if external.startswith("/") else absolute(external, public_base)

    return Result(
        company,
        "requests",
        status_from(last_code, len(unique)),
        len(unique),
        first_text(first.get("title")),
        sample_url,
    )


def parse_cisco_jobs(body: str) -> List[Tuple[str, str]]:
    decoded = body.replace("\\u002F", "/").replace("\\u002f", "/").replace("\\/", "/")
    jobs: List[Tuple[str, str]] = []

    pattern = (
        r'"country"\s*:\s*"(?P<country>[^"]+)"[\s\S]{0,1200}?'
        r'"title"\s*:\s*"(?P<title>[^"]+)"[\s\S]{0,800}?'
        r'"jobSeqNo"\s*:\s*"(?P<seq>[^"]+)"'
    )
    for match in re.finditer(pattern, decoded):
        if not is_us_text(match.group("country")):
            continue
        title = clean_text(match.group("title"))
        seq = match.group("seq")
        jobs.append((title, f"https://careers.cisco.com/global/en/job/{seq}/{slugify(title)}"))

    if jobs:
        return jobs

    links = re.findall(r'https://careers\.cisco\.com/global/en/job/[^"\'\\< ]+', decoded)
    links += [
        absolute(link, "https://careers.cisco.com")
        for link in re.findall(r'href=["\']([^"\']*/global/en/job/[^"\']+)["\']', decoded, flags=re.I)
    ]
    return [(title_from_url(link), html.unescape(link)) for link in links]


def test_cisco() -> Result:
    jobs: List[Tuple[str, str]] = []
    last_code = None

    for start in range(0, LIMIT, 10):
        params = {"from": str(start), "s": "1", "country": "United States of America"}
        url = "https://careers.cisco.com/global/en/search-results?" + urllib.parse.urlencode(params)
        code, body = http_get(url)
        last_code = code
        if code != 200:
            break

        jobs.extend(parse_cisco_jobs(body))
        if len(jobs) >= LIMIT:
            break
        time.sleep(REQUEST_DELAY)

    unique = unique_by(jobs, lambda item: item[1])
    sample_title, sample_url = unique[0] if unique else ("", "")
    return Result("Cisco", "requests", status_from(last_code, len(unique)), len(unique), sample_title, sample_url)


def parse_arm_cards(body: str) -> List[Tuple[str, str, str]]:
    pattern = re.compile(
        r'<a\b(?=[^>]*class=["\'][^"\']*job-card__title[^"\']*["\'])'
        r'(?=[^>]*href=["\'](?P<href>[^"\']*/job/[^"\']+)["\'])[^>]*>'
        r'(?P<title>.*?)</a>[\s\S]{0,600}?<span class=["\']location["\']>(?P<location>.*?)</span>',
        flags=re.I | re.S,
    )
    return [
        (clean_text(m.group("title")), absolute(m.group("href"), "https://careers.arm.com"), clean_text(m.group("location")))
        for m in pattern.finditer(body)
    ]


def test_arm() -> Result:
    url = "https://careers.arm.com/search-jobs/?sort=posted_date"
    code, body = http_get(url)
    jobs = parse_arm_cards(body)

    # Arm exposes country facet 6252001 for United States, but the static GET
    # route does not reliably honor it. Keep only obvious US rows from the
    # official recent/top page and let the real script mark unknowns incomplete.
    us_jobs = [(title, link) for title, link, location in jobs if is_us_text(location) or location in {"Austin, Texas", "San Jose, California"}]
    if not us_jobs:
        us_jobs = [(title, link) for title, link, _location in jobs]

    unique = unique_by(us_jobs, lambda item: item[1])
    sample_title, sample_url = unique[0] if unique else ("", "")
    return Result("Arm", "requests", status_from(code, len(unique)), len(unique), sample_title, sample_url)


def test_ti() -> Result:
    finder = (
        "findReqs;siteNumber=CX,"
        "facetsList=LOCATIONS%3BWORK_LOCATIONS%3BTITLES%3BCATEGORIES%3BORGANIZATIONS%3BPOSTING_DATES%3BFLEX_FIELDS,"
        "limit=50,sortBy=POSTING_DATES_DESC"
    )
    url = (
        "https://edbz.fa.us2.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions?"
        "onlyData=true&expand=requisitionList.secondaryLocations,flexFieldsFacet.values,requisitionList.requisitionFlexFields&finder="
        + finder
    )
    code, body = http_get(url, accept="application/json,*/*")
    data = load_json(body)
    items = data.get("items", []) if isinstance(data, dict) else []
    jobs = []
    if items and isinstance(items[0], dict):
        batch = items[0].get("requisitionList", [])
        jobs = batch if isinstance(batch, list) else []

    us_jobs = [
        job for job in jobs
        if is_us_text(job.get("PrimaryLocationCountry") or job.get("PrimaryLocation") or job.get("Locations"))
    ]
    unique = unique_by(us_jobs or jobs, lambda job: str(job.get("Id") or job.get("Title") or ""))

    first = unique[0] if unique else {}
    req_id = str(first.get("Id") or "")
    sample_url = f"https://careers.ti.com/job/{req_id}" if req_id else "https://careers.ti.com/"
    return Result(
        "Texas Instruments",
        "requests",
        status_from(code, len(unique)),
        len(unique),
        first_text(first.get("Title")),
        sample_url,
    )


def test_sony() -> Result:
    workday = collect_sony_workday()
    ps = collect_playstation()
    combined = unique_by(workday + ps, lambda item: item[1])
    sample_title, sample_url = combined[0] if combined else ("", "")
    return Result("Sony", "requests", status_from(200, len(combined)), len(combined), sample_title, sample_url)


def collect_sony_workday() -> List[Tuple[str, str]]:
    endpoint = "https://sonyglobal.wd1.myworkdayjobs.com/wday/cxs/sonyglobal/SonyGlobalCareers/jobs"
    result = test_workday(
        "Sony Global",
        endpoint,
        "https://sonyglobal.wd1.myworkdayjobs.com/SonyGlobalCareers",
    )
    if result.status != "ok":
        return []

    _, facet_param, us_location_ids = discover_workday_us_facet(endpoint)
    payload = {
        "appliedFacets": {facet_param: us_location_ids} if facet_param and us_location_ids else {},
        "limit": 20,
        "offset": 0,
        "searchText": "",
    }
    code, body = http_post_json(endpoint, payload)
    if code != 200:
        return []
    data = load_json(body)
    postings = data.get("jobPostings", []) if isinstance(data, dict) else []

    out = []
    for job in postings:
        external = str(job.get("externalPath") or "")
        url = "https://sonyglobal.wd1.myworkdayjobs.com/SonyGlobalCareers" + external if external.startswith("/") else external
        out.append((first_text(job.get("title")), url))
    return out


def collect_playstation() -> List[Tuple[str, str]]:
    url = "https://careers.playstation.com/jobs?sortBy=posted_date"
    code, body = http_get(url)
    if code != 200:
        return []
    decoded = body.replace("\\u002F", "/").replace("\\u002f", "/").replace("\\/", "/")
    links = re.findall(r'https://careers\.playstation\.com/[^"\'\\< ]+', decoded)
    links += [
        absolute(link, "https://careers.playstation.com")
        for link in re.findall(r'href=["\']([^"\']*/jobs/[^"\']+)["\']', decoded, flags=re.I)
    ]
    titles = re.findall(r'"title"\s*:\s*"([^"]{3,160})"', decoded)

    out = []
    for idx, link in enumerate(links):
        if "/jobs/" not in link:
            continue
        out.append((clean_text(titles[idx]) if idx < len(titles) else title_from_url(link), link))
    return out


def print_table(results: List[Result]) -> None:
    headers = ["Company", "Method", "Status", "Count", "Sample title", "Sample URL / Note"]
    rows = []
    for r in results:
        rows.append([r.company, r.method, r.status, str(r.count), r.sample_title[:50], r.sample_url[:95]])

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
        test_cisco,
        lambda: test_jibe("AMD", "https://careers.amd.com", "https://careers.amd.com/api/jobs"),
        lambda: test_workday(
            "Broadcom",
            "https://broadcom.wd1.myworkdayjobs.com/wday/cxs/broadcom/External_Career/jobs",
            "https://broadcom.wd1.myworkdayjobs.com/External_Career",
        ),
        lambda: test_workday(
            "Intel",
            "https://intel.wd1.myworkdayjobs.com/wday/cxs/intel/External/jobs",
            "https://intel.wd1.myworkdayjobs.com/External",
        ),
        test_arm,
        lambda: test_workday(
            "Marvell",
            "https://marvell.wd1.myworkdayjobs.com/wday/cxs/marvell/MarvellCareers/jobs",
            "https://marvell.wd1.myworkdayjobs.com/MarvellCareers",
        ),
        test_ti,
        lambda: test_workday(
            "NXP",
            "https://nxp.wd3.myworkdayjobs.com/wday/cxs/nxp/careers/jobs",
            "https://nxp.wd3.myworkdayjobs.com/careers",
        ),
        lambda: test_jibe("Garmin", "https://careers.garmin.com", "https://careers.garmin.com/api/jobs"),
        test_sony,
    ]
    results = [test() for test in tests]
    print_table(results)
    failed = [r for r in results if r.status != "ok"]
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
