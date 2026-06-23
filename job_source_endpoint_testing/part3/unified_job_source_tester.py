#!/usr/bin/env python3
"""
Unified simple job-source tester for Part 3 companies.

Purpose:
  Test official source access methods intended for job_search_3.

This tester fetches recent/top official records first. It does not score jobs,
append to a ledger, or run profile keyword searches. Brand terms such as Aruba
and Juniper are used only to identify sub-company surfaces inside HPE Careers.
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

TIMEOUT = 8
LIMIT = int(os.environ.get("JOB_SOURCE_TEST_LIMIT", "20"))
REQUEST_DELAY = 0.1
RETRY_STATUSES = {429, 500, 502, 503, 504}
US_TEXT = ("united states", "united states of america", "usa", "us,", ",us", ", us", " us")


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
        except urllib.error.HTTPError as e:
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:
                body = ""
            if e.code in RETRY_STATUSES and attempt < 2:
                time.sleep(0.5 * (attempt + 1))
                continue
            return e.code, body
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
        except urllib.error.HTTPError as e:
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:
                body = ""
            if e.code in RETRY_STATUSES and attempt < 2:
                time.sleep(0.5 * (attempt + 1))
                continue
            return e.code, body
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
        return "schema_changed"
    return f"http_{code}"


def is_us_text(value: Any) -> bool:
    text = clean_text(str(value or "")).lower()
    return any(token in text for token in US_TEXT) or text in {"us", "usa", "united states"}


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


def first_text(*values: Any) -> str:
    for value in values:
        if value:
            return clean_text(str(value))
    return ""


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "job"


def test_bosch() -> Result:
    config_url = "https://jobs.bosch.com/en/"
    config_code, config_body = http_get(config_url, accept="text/html,*/*")
    api_match = re.search(
        r"jobsApi:\{\s*baseUrl:\"(?P<base>[^\"]+)\".*?tenant:\"(?P<tenant>[^\"]+)\".*?"
        r"project:\"(?P<project>[^\"]+)\".*?collection:\"(?P<collection>[^\"]+)\".*?apiKey:\"(?P<key>[^\"]+)\"",
        config_body,
        flags=re.S,
    )
    prefix_match = re.search(r'jobAdLinkPrefix:"(?P<prefix>[^"]+)"', config_body)
    if not api_match:
        return Result("Bosch", "requests", status_from(config_code, 0), 0, "", "jobsApi config not found")

    endpoint = (
        f"{api_match.group('base')}/{api_match.group('tenant')}/"
        f"{api_match.group('project')}.{api_match.group('collection')}.content/_aggrs/get_jobs"
    )
    avars = {"country": ["us"], "sort": {"releasedDate": -1}}
    params = {"np": "", "rep": "pj", "pagesize": str(LIMIT), "page": "1", "avars": json.dumps(avars, separators=(",", ":"))}
    url = endpoint + "?" + urllib.parse.urlencode(params)
    code, body = http_get(url, headers={"Authorization": f"Bearer {api_match.group('key')}"})
    data = load_json(body)
    jobs = []
    if isinstance(data, list) and data and isinstance(data[0], dict):
        jobs = data[0].get("data", [])
    jobs = jobs if isinstance(jobs, list) else []
    unique = unique_by(jobs, lambda job: str(job.get("refNumber") or job.get("_id") or job.get("jobUrl") or ""))

    first = unique[0] if unique else {}
    prefix = prefix_match.group("prefix") if prefix_match else "https://jobs.bosch.com/en/job/"
    sample_url = absolute(str(first.get("jobUrl") or ""), prefix)
    return Result("Bosch", "requests", status_from(code, len(unique)), len(unique), first_text(first.get("name")), sample_url)


def parse_siemens_cards(body: str) -> List[Tuple[str, str, str]]:
    cards = []
    article_pattern = re.compile(r"<article\b[\s\S]*?</article>", flags=re.I)
    for article in article_pattern.findall(body):
        link_match = re.search(r'href=["\'](?P<href>https://jobs\.siemens\.com/en_US/externaljobs/JobDetail/(?P<id>\d+))["\']', article)
        title_match = re.search(
            r'<a[^>]*class=["\']link["\'][^>]*href=["\']https://jobs\.siemens\.com/en_US/externaljobs/JobDetail/\d+["\'][^>]*>(?P<title>.*?)</a>',
            article,
            flags=re.I | re.S,
        )
        loc_match = re.search(r'<span class=["\']list-item-location["\']>(?P<loc>.*?)</span>', article, flags=re.I | re.S)
        if link_match:
            cards.append((
                clean_text(title_match.group("title")) if title_match else f"Job {link_match.group('id')}",
                link_match.group("href"),
                clean_text(loc_match.group("loc")) if loc_match else "",
            ))
    if cards:
        return cards

    links = re.findall(r'https://jobs\.siemens\.com/en_US/externaljobs/JobDetail/\d+', body)
    return [(f"Job {url.rsplit('/', 1)[-1]}", url, "") for url in links]


def test_siemens() -> Result:
    jobs: List[Tuple[str, str, str]] = []
    last_code = None
    for offset in range(0, LIMIT, 6):
        params = {"folderRecordsPerPage": "6", "folderOffset": str(offset), "folderSort": "postedDate", "folderSortDirection": "desc"}
        url = "https://jobs.siemens.com/en_US/externaljobs/SearchJobs/?" + urllib.parse.urlencode(params)
        code, body = http_get(url, accept="text/html,*/*")
        last_code = code
        if code != 200:
            break
        jobs.extend(parse_siemens_cards(body))
        if len(jobs) >= LIMIT:
            break
        time.sleep(REQUEST_DELAY)

    unique = unique_by(jobs, lambda item: item[1])
    sample = unique[0] if unique else ("", "", "")
    return Result("Siemens", "requests", status_from(last_code, len(unique)), len(unique), sample[0], sample[1])


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
        values = facet.get("values", [])
        ids = []
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
        payload = {"appliedFacets": applied, "limit": min(20, LIMIT - offset), "offset": offset, "searchText": ""}
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


def hpe_search_url(brand: str) -> str:
    params = {"keywords": brand, "from": "0", "s": "1", "country": "United States"}
    return "https://careers.hpe.com/us/en/search-results?" + urllib.parse.urlencode(params)


def extract_hpe_ddo(body: str) -> Dict[str, Any]:
    match = re.search(r"phApp\.ddo\s*=\s*(\{.*?\});\s*phApp\.", body, flags=re.S)
    if not match:
        return {}
    data = load_json(match.group(1))
    return data if isinstance(data, dict) else {}


def test_hpe(company: str, brand: str) -> Result:
    url = hpe_search_url(brand)
    code, body = http_get(url, accept="text/html,*/*")
    data = extract_hpe_ddo(body)
    search = data.get("eagerLoadRefineSearch", {}) if isinstance(data, dict) else {}
    payload = search.get("data", {}) if isinstance(search, dict) else {}
    jobs = payload.get("jobs", []) if isinstance(payload, dict) else []
    jobs = jobs if isinstance(jobs, list) else []

    us_jobs = [
        job
        for job in jobs
        if is_us_text(job.get("country")) or is_us_text(job.get("multi_location")) or is_us_text(job.get("address"))
    ]
    unique = unique_by(us_jobs or jobs, lambda job: str(job.get("jobSeqNo") or job.get("reqId") or job.get("applyUrl") or ""))
    first = unique[0] if unique else {}
    sample_url = first_text(first.get("applyUrl"), first.get("jobUrl"), url)
    return Result(company, "requests", status_from(code, len(unique)), len(unique), first_text(first.get("title")), sample_url)


def smartrecruiters_public_url(job: Dict[str, Any]) -> str:
    ref = str(job.get("refNumber") or "")
    name = first_text(job.get("name"))
    if ref and name:
        return f"https://jobs.smartrecruiters.com/AristaNetworks/{ref}-{slugify(name)}"
    ref_url = str(job.get("ref") or "")
    if ref_url:
        return ref_url
    job_id = str(job.get("id") or "")
    return f"https://api.smartrecruiters.com/v1/companies/AristaNetworks/postings/{job_id}" if job_id else ""


def test_arista() -> Result:
    jobs: List[Dict[str, Any]] = []
    last_code = None
    for offset in range(0, LIMIT, 20):
        params = {"limit": str(min(20, LIMIT - offset)), "offset": str(offset), "q": "United States"}
        url = "https://api.smartrecruiters.com/v1/companies/AristaNetworks/postings?" + urllib.parse.urlencode(params)
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

    us_jobs = [job for job in jobs if is_us_text(job.get("location", {}).get("fullLocation"))]
    unique = unique_by(us_jobs or jobs, lambda job: str(job.get("id") or job.get("uuid") or job.get("refNumber") or ""))
    first = unique[0] if unique else {}
    return Result("Arista Networks", "requests", status_from(last_code, len(unique)), len(unique), first_text(first.get("name")), smartrecruiters_public_url(first))


def test_ericsson() -> Result:
    jobs: List[Dict[str, Any]] = []
    last_code = None
    for start in [0]:
        params = {"domain": "ericsson.com", "location": "United States", "start": str(start), "sort_by": "timestamp"}
        url = "https://jobs.ericsson.com/api/pcsx/search?" + urllib.parse.urlencode(params)
        code, body = http_get(url)
        last_code = code
        if code != 200:
            break
        data = load_json(body)
        positions = []
        if isinstance(data, dict):
            positions = data.get("data", {}).get("positions", []) if isinstance(data.get("data"), dict) else data.get("positions", [])
        if not isinstance(positions, list) or not positions:
            break
        jobs.extend(positions)
        if len(jobs) >= LIMIT:
            break
        time.sleep(REQUEST_DELAY)

    unique = unique_by(jobs, lambda job: str(job.get("id") or job.get("displayJobId") or job.get("positionUrl") or ""))
    first = unique[0] if unique else {}
    sample_url = absolute(str(first.get("publicUrl") or first.get("positionUrl") or ""), "https://jobs.ericsson.com")
    return Result("Ericsson", "requests", status_from(last_code, len(unique)), len(unique), first_text(first.get("name")), sample_url)


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
        test_bosch,
        test_siemens,
        lambda: test_oracle("Honeywell", "https://ibqbjb.fa.ocs.oraclecloud.com", "CX_1", "https://careers.honeywell.com/en/sites/Honeywell"),
        lambda: test_hpe("HPE Aruba Networking", "Aruba"),
        lambda: test_hpe("Juniper Networks", "Juniper"),
        test_arista,
        lambda: test_oracle("Fortinet", "https://edel.fa.us2.oraclecloud.com", "CX_2001", "https://edel.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_2001"),
        lambda: test_workday("Ciena", "https://ciena.wd5.myworkdayjobs.com/wday/cxs/ciena/Careers/jobs", "https://ciena.wd5.myworkdayjobs.com/Careers"),
        lambda: test_oracle("Nokia", "https://fa-evmr-saasfaprod1.fa.ocs.oraclecloud.com", "CX_1", "https://jobs.nokia.com/en/sites/CX_1"),
        test_ericsson,
    ]
    results = [test() for test in tests]
    print_table(results)
    failed = [r for r in results if r.status != "ok"]
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
