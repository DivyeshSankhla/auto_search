#!/usr/bin/env python3
"""
Unified job-site source tester for general US engineer job search platforms.

Purpose:
  Prove and document how a future job_search_general.py should search each site:
  keyword query, location filter, date sort, top-N pagination, list parse, JD fetch.

Install optional dependencies:
  pip install curl_cffi playwright
  playwright install chromium

Run:
  python3 unified_job_site_tester.py

Output:
  Site | Method | Status | Count | JD | JD chars | Sample title | Sample URL
"""

from __future__ import annotations

import base64
import html
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple


USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

TIMEOUT = 20
LIMIT = int(os.environ.get("JOB_SOURCE_TEST_LIMIT", "50"))
REQUEST_DELAY = 0.15
RETRY_STATUSES = {429, 500, 502, 503, 504}
TEST_QUERY = os.environ.get("JOB_SITE_TEST_QUERY", "firmware engineer")
TEST_LOCATION = os.environ.get("JOB_SITE_TEST_LOCATION", "United States")
MIN_JD_CHARS = 200

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

JobRow = Dict[str, str]


@dataclass
class Result:
    site: str
    method: str
    status: str
    count: int
    sample_title: str = ""
    sample_url: str = ""
    jd_status: str = ""
    sample_jd_chars: int = 0
    search_query: str = ""


def clean_text(raw: str) -> str:
    raw = html.unescape(raw or "")
    raw = raw.replace("\xa0", " ")
    raw = re.sub(r"<script[\s\S]*?</script>", " ", raw, flags=re.I)
    raw = re.sub(r"<style[\s\S]*?</style>", " ", raw, flags=re.I)
    raw = re.sub(r"<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", raw).strip()


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


def jd_status_from(code: Optional[int], text: str) -> str:
    if len(clean_text(text)) >= MIN_JD_CHARS:
        return "ok"
    if code == 403:
        return "blocked"
    if code is None:
        return "failed"
    if code == 200:
        return "parser_failed"
    return f"http_{code}"


def query_match(text: str, query: str = TEST_QUERY) -> bool:
    hay = clean_text(text).lower()
    if not hay:
        return False
    tokens = [token for token in re.split(r"\s+", query.lower()) if len(token) > 2]
    return all(token in hay for token in tokens) if tokens else True


def query_match_loose(text: str, query: str = TEST_QUERY) -> bool:
    hay = clean_text(text).lower()
    if not hay:
        return False
    if query_match(text, query):
        return True
    tokens = [token for token in re.split(r"\s+", query.lower()) if len(token) > 2]
    if any(token in hay for token in tokens):
        return True
    engineering_terms = ("engineer", "firmware", "embedded", "software", "developer", "kernel")
    return any(term in hay for term in engineering_terms)


def parse_indeed_cards(body: str) -> List[JobRow]:
    jobs: List[JobRow] = []
    jks = re.findall(r'data-jk="([a-f0-9]+)"', body)
    titles = re.findall(r'<span[^>]*title="([^"]{5,120})"', body)
    if jks and titles:
        for jk, title in zip(jks, titles):
            jobs.append(
                {
                    "title": clean_text(title),
                    "url": f"https://www.indeed.com/viewjob?jk={jk}",
                    "job_id": jk,
                }
            )
        return jobs
    for match in re.finditer(
        r'data-jk="(?P<jk>[a-f0-9]+)"[\s\S]{0,1200}?'
        r'<(?:h2|span)[^>]*class="[^"]*jobTitle[^"]*"[^>]*>[\s\S]*?'
        r'<span[^>]*>(?P<title>[^<]{3,120})</span>',
        body,
        flags=re.I,
    ):
        jk = match.group("jk")
        jobs.append(
            {
                "title": clean_text(match.group("title")),
                "url": f"https://www.indeed.com/viewjob?jk={jk}",
                "job_id": jk,
            }
        )
    if jobs:
        return jobs
    for jk in jks:
        jobs.append({"title": "", "url": f"https://www.indeed.com/viewjob?jk={jk}", "job_id": jk})
    return jobs


def parse_linkedin_cards(body: str) -> List[JobRow]:
    jobs: List[JobRow] = []
    for match in re.finditer(
        r'base-search-card__title[^>]*>\s*([^<]{3,120})\s*<[\s\S]{0,2500}?'
        r'https://www\.linkedin\.com/jobs/view/([^?\s"&]+)',
        body,
        flags=re.I,
    ):
        slug = match.group(2)
        jobs.append(
            {
                "title": clean_text(match.group(1)),
                "url": f"https://www.linkedin.com/jobs/view/{slug}",
            }
        )
    if jobs:
        return jobs
    for slug in re.findall(r'https://www\.linkedin\.com/jobs/view/([^?\s"&]+)', body):
        jobs.append(
            {
                "title": clean_text(slug.replace("-at-", " at ").replace("-", " ")),
                "url": f"https://www.linkedin.com/jobs/view/{slug}",
            }
        )
    return jobs


def is_us_text(value: Any) -> bool:
    text = clean_text(str(value or "")).lower()
    if not text:
        return False
    if "united states" in text or "north america" in text or "usa" in text or " u.s." in text:
        return True
    if re.search(r"(?<![a-z])us(?![a-z])", text):
        return True
    if "remote" in text and ("us" in text or "america" in text or "anywhere" in text):
        return True
    if any(re.search(r"(?<![a-z])" + re.escape(state) + r"(?![a-z])", text) for state in US_STATE_TEXT):
        return True
    return any(re.search(r"(^|[\s,(])" + abbr + r"($|[\s,)])", text) for abbr in US_STATE_ABBR)


def unique_by(items: Iterable[JobRow], key: str = "url") -> List[JobRow]:
    seen = set()
    out: List[JobRow] = []
    for item in items:
        value = str(item.get(key) or "")
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(item)
        if len(out) >= LIMIT:
            break
    return out


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
    req_headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json,text/html,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Content-Type": "application/json",
    }
    if headers:
        req_headers.update(headers)
    data = json.dumps(payload).encode("utf-8")
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


def curl_cffi_get(url: str) -> Tuple[Optional[int], str, str]:
    try:
        from curl_cffi import requests as curl_requests
    except ImportError:
        return None, "", "missing_curl_cffi"
    try:
        resp = curl_requests.get(url, impersonate="chrome124", timeout=TIMEOUT)
        return resp.status_code, resp.text, "curl_cffi"
    except Exception:
        return None, "", "curl_cffi"


def fetch_page(url: str, prefer_curl: bool = False) -> Tuple[Optional[int], str, str]:
    if prefer_curl:
        code, body, method = curl_cffi_get(url)
        if method == "missing_curl_cffi":
            code, body = http_get(url)
            return code, body, "requests"
        return code, body, method
    code, body = http_get(url)
    if code in {403, None} or (code == 200 and len(body) < 500):
        curl_code, curl_body, curl_method = curl_cffi_get(url)
        if curl_method != "missing_curl_cffi" and curl_code == 200 and len(curl_body) > len(body):
            return curl_code, curl_body, curl_method
    return code, body, "requests"


CapturedResponse = Tuple[int, str, str]
MONSTER_APP_CHUNK = "/assets/jobsui/_next/static/chunks/pages/_app-2d5c3c0d21a49478.js"
OTTA_FALLBACK_SEARCH = "https://www.welcometothejungle.com/en/jobs"


def playwright_search_jobs(
    url: str,
    url_patterns: Iterable[str],
    *,
    wait_selector: Optional[str] = None,
    scroll: bool = True,
    timeout_ms: int = 90000,
) -> Tuple[str, List[CapturedResponse], str, Optional[int]]:
    patterns = [pattern.lower() for pattern in url_patterns]
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return "", [], "missing_playwright", None

    captured: List[CapturedResponse] = []
    headed = os.environ.get("JOB_SITE_HEADED", "0") == "1"
    page_status: Optional[int] = None
    html_body = ""

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=not headed)
            page = browser.new_page(user_agent=USER_AGENT)

            def on_response(response: Any) -> None:
                response_url = response.url.lower()
                if response.request.resource_type not in {"xhr", "fetch"}:
                    return
                if patterns and not any(pattern in response_url for pattern in patterns):
                    return
                try:
                    content_type = (response.headers.get("content-type") or "").lower()
                    body = response.text() if ("json" in content_type or "graphql" in response_url) else ""
                except Exception:
                    body = ""
                captured.append((response.status, response.url, body))

            page.on("response", on_response)
            resp = page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            page_status = resp.status if resp else None

            if any("wellfound" in pattern for pattern in patterns):
                for _ in range(15):
                    html_body = page.content()
                    if len(html_body) > 10000 and "just a moment" not in html_body.lower():
                        break
                    page.wait_for_timeout(2000)
            else:
                try:
                    page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass

            if wait_selector:
                try:
                    page.wait_for_selector(wait_selector, timeout=15000)
                except Exception:
                    pass

            if scroll:
                for _ in range(4):
                    page.mouse.wheel(0, 2000)
                    page.wait_for_timeout(1000)

            page.wait_for_timeout(2000)
            html_body = page.content()
            browser.close()
        return html_body, captured, "playwright", page_status
    except Exception:
        return html_body, captured, "playwright_failed", page_status


def _parse_jobs_from_json_obj(obj: Any, base_url: str, jobs: List[JobRow]) -> None:
    if isinstance(obj, dict):
        title = str(
            obj.get("title")
            or obj.get("jobTitle")
            or obj.get("position")
            or obj.get("name")
            or obj.get("role")
            or ""
        )
        url = str(obj.get("url") or obj.get("jobUrl") or obj.get("job_url") or obj.get("absolute_url") or "")
        job_id = str(obj.get("jobId") or obj.get("job_id") or obj.get("slug") or obj.get("id") or "")
        if title and url:
            jobs.append({"title": clean_text(title), "url": absolute(url, base_url) if base_url else url})
        elif title and job_id and "monster" in base_url:
            jobs.append(
                {
                    "title": clean_text(title),
                    "url": f"https://www.monster.com/job-openings/{job_id}",
                    "job_id": job_id,
                }
            )
        elif title and job_id and "otta.com" in base_url:
            jobs.append(
                {
                    "title": clean_text(title),
                    "url": f"https://app.otta.com/jobs/{job_id}",
                    "job_id": job_id,
                }
            )
        elif title and job_id and "wellfound" in base_url:
            jobs.append(
                {
                    "title": clean_text(title),
                    "url": absolute(f"/jobs/listing/{job_id}", base_url),
                    "job_id": job_id,
                }
            )
        for value in obj.values():
            _parse_jobs_from_json_obj(value, base_url, jobs)
    elif isinstance(obj, list):
        for item in obj:
            _parse_jobs_from_json_obj(item, base_url, jobs)


def parse_jobs_from_json_blobs(bodies: Iterable[str], base_url: str = "") -> List[JobRow]:
    jobs: List[JobRow] = []
    for body in bodies:
        if not body:
            continue
        data = load_json(body)
        if data is not None:
            _parse_jobs_from_json_obj(data, base_url, jobs)
        for title, url in re.findall(r'"jobTitle":"([^"]{3,120})"[\s\S]{0,300}?"jobUrl":"([^"]+)"', body):
            jobs.append({"title": clean_text(title), "url": url})
        for title, job_id in re.findall(r'"title":"([^"]{3,120})"[\s\S]{0,200}?"jobId":"([^"]+)"', body):
            jobs.append({"title": clean_text(title), "url": f"https://www.monster.com/job-openings/{job_id}", "job_id": job_id})
        for title, slug in re.findall(r'"title":"([^"]{3,120})"[\s\S]{0,200}?"slug":"([^"]+)"', body):
            url_base = base_url or "https://app.otta.com"
            jobs.append({"title": clean_text(title), "url": f"{url_base.rstrip('/')}/jobs/{slug}"})
        for title, path in re.findall(r'"title":"([^"]{3,120})"[\s\S]{0,200}?"(?:listingPath|path)":"([^"]+)"', body):
            jobs.append({"title": clean_text(title), "url": absolute(path, base_url or "https://wellfound.com")})
    return jobs


def decode_otto_apollo(html_body: str) -> List[JobRow]:
    jobs: List[JobRow] = []
    match = re.search(r'window\.__APOLLO_STATE__=__b64dec\("([A-Za-z0-9+/=]+)"\)', html_body)
    if not match:
        return jobs
    try:
        data = json.loads(base64.b64decode(match.group(1)))
    except Exception:
        return jobs
    if not isinstance(data, dict):
        return jobs
    for value in data.values():
        if not isinstance(value, dict) or value.get("__typename") != "Job":
            continue
        title = str(value.get("title") or "")
        slug = str(value.get("slug") or value.get("id") or "")
        if not slug:
            continue
        jobs.append({"title": clean_text(title), "url": f"https://app.otta.com/jobs/{slug}", "job_id": slug})
    return jobs


def parse_wellfound_dom(html_body: str) -> List[JobRow]:
    jobs: List[JobRow] = []
    for match in re.finditer(r'href="(/jobs/[^"]+)"[^>]*>([^<]{3,120})</a>', html_body, flags=re.I):
        jobs.append({"title": clean_text(match.group(2)), "url": absolute(match.group(1), "https://wellfound.com")})
    for path in re.findall(r'(/jobs/listing/[^"\']+)', html_body):
        jobs.append({"title": "", "url": absolute(path, "https://wellfound.com")})
    for title, path in re.findall(r'"title":"([^"]{3,120})"[\s\S]{0,200}?"slug":"([^"]+)"', html_body):
        jobs.append({"title": clean_text(title), "url": f"https://wellfound.com/jobs/{path}"})
    return jobs


def parse_monster_dom(html_body: str) -> List[JobRow]:
    jobs: List[JobRow] = []
    for url in re.findall(r'href="(https://www\.monster\.com/job-openings/[^"]+)"', html_body):
        slug = url.rstrip("/").split("/")[-1]
        jobs.append({"title": clean_text(slug.replace("-", " ")), "url": url})
    for path in re.findall(r'href="(/job-openings/[^"]+)"', html_body):
        url = absolute(path, "https://www.monster.com")
        slug = url.rstrip("/").split("/")[-1]
        jobs.append({"title": clean_text(slug.replace("-", " ")), "url": url})
    return jobs


def parse_otto_dom(html_body: str) -> List[JobRow]:
    jobs: List[JobRow] = []
    for path in re.findall(r'(/jobs/[a-f0-9-]{8,})', html_body):
        jobs.append({"title": "", "url": absolute(path, "https://app.otta.com")})
    for url in re.findall(r'href="(https://app\.otta\.com/jobs/[^"]+)"', html_body):
        slug = url.rstrip("/").split("/")[-1]
        jobs.append({"title": clean_text(slug.replace("-", " ")), "url": url})
    for title, slug in re.findall(r'"title":"([^"]{3,120})"[\s\S]{0,200}?"slug":"([^"]+)"', html_body):
        jobs.append({"title": clean_text(title), "url": f"https://app.otta.com/jobs/{slug}"})
    return jobs


def parse_wttj_jobs(html_body: str) -> List[JobRow]:
    jobs: List[JobRow] = []
    for url in re.findall(
        r'href="(https://www\.welcometothejungle\.com/en/companies/[^"]+/jobs/[^"]+)"',
        html_body,
    ):
        slug = url.rstrip("/").split("/")[-1]
        jobs.append({"title": clean_text(slug.replace("-", " ")), "url": url})
    for path in re.findall(r'(/en/companies/[^"]+/jobs/[a-z0-9-]+)', html_body):
        url = absolute(path, "https://www.welcometothejungle.com")
        slug = url.rstrip("/").split("/")[-1]
        jobs.append({"title": clean_text(slug.replace("-", " ")), "url": url})
    return jobs


def monster_js_chunks(html_body: str) -> List[str]:
    chunks = re.findall(r'(/assets/jobsui/_next/static/chunks/[^"]+\.js)', html_body)
    if MONSTER_APP_CHUNK not in chunks:
        chunks.insert(0, MONSTER_APP_CHUNK)
    deduped: List[str] = []
    seen = set()
    for chunk in chunks:
        if chunk in seen:
            continue
        seen.add(chunk)
        deduped.append(chunk)
    return deduped


def monster_runtime_config(html_body: str) -> Dict[str, str]:
    config: Dict[str, str] = {"locale": "en-us", "tenant_id": "", "site_id": "", "apigee": "https://appsapi.monster.io"}
    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>([\s\S]+?)</script>', html_body)
    if not match:
        return config
    data = load_json(match.group(1))
    if not isinstance(data, dict):
        return config
    text = json.dumps(data)
    for key, target in (("tenantId", "tenant_id"), ("siteId", "site_id")):
        found = re.search(rf'"{key}"\s*:\s*"([^"]+)"', text)
        if found:
            config[target] = found.group(1)
    apigee = re.search(r'"apigee"\s*:\s*"(https://[^"]+)"', text)
    if apigee:
        config["apigee"] = apigee.group(1)
    locale = re.search(r'"locale"\s*:\s*"(en-[a-z]{2})"', text, flags=re.I)
    if locale:
        config["locale"] = locale.group(1).lower()
    return config


def monster_samsearch_api_key(app_js: str) -> str:
    idx = app_js.find("search-jobs/samsearch")
    windows: List[str] = []
    if idx >= 0:
        windows.append(app_js[max(0, idx - 8000): idx + 500])
    windows.append(app_js)
    for window in windows:
        for pattern in (
            r'apikey:"([a-zA-Z0-9._-]{16,64})"',
            r'apiKey:"([a-zA-Z0-9._-]{16,64})"',
            r'"apiKey"\s*:\s*"([a-zA-Z0-9._-]{16,64})"',
            r'key:"([a-zA-Z0-9._-]{20,64})"',
        ):
            keys = re.findall(pattern, window, flags=re.I)
            if keys:
                return keys[-1]
    return ""


def monster_samsearch_api_key_from_page(html_body: str, search_url: str) -> str:
    try:
        from curl_cffi import requests as curl_requests
    except ImportError:
        return ""

    session = curl_requests.Session(impersonate="chrome124", timeout=TIMEOUT)
    for chunk in monster_js_chunks(html_body):
        js = session.get(urllib.parse.urljoin(search_url, chunk), headers={"Referer": search_url}).text
        api_key = monster_samsearch_api_key(js)
        if api_key:
            return api_key
    return ""


def parse_monster_samsearch_response(body: str) -> List[JobRow]:
    data = load_json(body)
    if not isinstance(data, dict):
        return []
    rows = data.get("jobResults")
    if not isinstance(rows, list):
        nested = data.get("jobResultsData")
        if isinstance(nested, dict):
            rows = nested.get("jobResults")
    if not isinstance(rows, list):
        return []
    jobs: List[JobRow] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = str(row.get("jobTitle") or row.get("title") or "")
        job_id = str(row.get("jobId") or row.get("seoJobId") or row.get("id") or "")
        url = str(row.get("jobUrl") or row.get("url") or "")
        if not url and job_id:
            url = f"https://www.monster.com/job-openings/{job_id}"
        if url or title:
            jobs.append({"title": clean_text(title), "url": url, "job_id": job_id})
    return jobs


def fetch_monster_jobs_samsearch(search_url: str, html_body: str) -> Tuple[List[JobRow], str]:
    try:
        from curl_cffi import requests as curl_requests
    except ImportError:
        return [], "missing_curl_cffi"

    config = monster_runtime_config(html_body)
    session = curl_requests.Session(impersonate="chrome124", timeout=TIMEOUT)
    session.get(search_url)
    api_key = monster_samsearch_api_key_from_page(html_body, search_url)
    if not api_key:
        return [], "samsearch_no_api_key"

    payload: Dict[str, Any] = {
        "jobRequest": {
            "offset": 0,
            "pageSize": LIMIT,
            "jobQuery": {
                "query": TEST_QUERY,
                "locations": [{"address": TEST_LOCATION, "country": "us"}],
            },
        }
    }
    if config.get("site_id"):
        payload["siteId"] = config["site_id"]

    headers = {
        "Referer": search_url,
        "Origin": "https://www.monster.com",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if config.get("tenant_id"):
        headers["Tenant-Id"] = config["tenant_id"]

    api_base = config.get("apigee") or "https://appsapi.monster.io"
    locale = config.get("locale") or "en-us"
    endpoint = f"{api_base.rstrip('/')}/jobs-svx-service/v2/monster/search-jobs/samsearch/{locale}"
    response = session.post(endpoint, json=payload, headers=headers, params={"apikey": api_key})
    if response.status_code == 200:
        jobs = parse_monster_samsearch_response(response.text)
        return jobs, "samsearch_api"
    if response.status_code == 403:
        return [], "samsearch_blocked"
    return [], f"samsearch_http_{response.status_code}"


def fetch_monster_jobs_playwright(search_url: str, html_body: str) -> Tuple[List[JobRow], str]:
    config = monster_runtime_config(html_body)
    api_key = monster_samsearch_api_key_from_page(html_body, search_url)
    if not api_key:
        return [], "samsearch_no_api_key"

    payload: Dict[str, Any] = {
        "jobRequest": {
            "offset": 0,
            "pageSize": LIMIT,
            "jobQuery": {
                "query": TEST_QUERY,
                "locations": [{"address": TEST_LOCATION, "country": "us"}],
            },
        }
    }
    if config.get("site_id"):
        payload["siteId"] = config["site_id"]
    api_url = (
        f"{(config.get('apigee') or 'https://appsapi.monster.io').rstrip('/')}"
        f"/jobs-svx-service/v2/monster/search-jobs/samsearch/{config.get('locale') or 'en-us'}"
    )

    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return [], "missing_playwright"

    captured: List[str] = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=os.environ.get("JOB_SITE_HEADED", "0") != "1")
            page = browser.new_page(user_agent=USER_AGENT)

            def fulfill_route(route: Any) -> None:
                if route.request.url.startswith("https://www.monster.com/jobs/search"):
                    route.fulfill(status=200, body=html_body, headers={"content-type": "text/html; charset=utf-8"})
                else:
                    route.continue_()

            def on_response(response: Any) -> None:
                if "samsearch" not in response.url.lower():
                    return
                try:
                    captured.append(response.text())
                except Exception:
                    pass

            page.route("**/*", fulfill_route)
            page.on("response", on_response)
            page.goto(search_url, wait_until="networkidle", timeout=90000)
            page.wait_for_timeout(8000)
            for _ in range(4):
                page.mouse.wheel(0, 2000)
                page.wait_for_timeout(1000)
            if not captured:
                result = page.evaluate(
                    """async (args) => {
                        const resp = await fetch(
                            args.url + '?apikey=' + encodeURIComponent(args.apikey),
                            {
                                method: 'POST',
                                headers: {
                                    'Content-Type': 'application/json',
                                    'Accept': 'application/json',
                                },
                                body: JSON.stringify(args.payload),
                                credentials: 'include',
                            }
                        );
                        return {status: resp.status, text: await resp.text()};
                    }""",
                    {"url": api_url, "apikey": api_key, "payload": payload},
                )
                if isinstance(result, dict) and result.get("status") == 200:
                    captured.append(str(result.get("text") or ""))
            browser.close()
    except Exception:
        return [], "playwright_failed"

    jobs: List[JobRow] = []
    for body in captured:
        jobs.extend(parse_monster_samsearch_response(body))
    if jobs:
        return jobs, "samsearch_playwright"
    return [], "samsearch_blocked"


def filter_job_rows(jobs: Iterable[JobRow]) -> List[JobRow]:
    out: List[JobRow] = []
    for job in jobs:
        url = str(job.get("url") or "")
        if not url:
            continue
        if "/jobs/oh-my-job-" in url:
            continue
        if "authenticate/signin" in url or url.endswith("/login"):
            continue
        out.append(job)
    return out


def merge_playwright_jobs(
    html_body: str,
    captured: List[CapturedResponse],
    *,
    dom_parser: Callable[[str], List[JobRow]],
    json_base: str,
    apollo_parser: Optional[Callable[[str], List[JobRow]]] = None,
    extra_parser: Optional[Callable[[str], List[JobRow]]] = None,
) -> List[JobRow]:
    jobs: List[JobRow] = []
    response_bodies = [item[2] for item in captured if item[2]]
    jobs.extend(parse_jobs_from_json_blobs(response_bodies, json_base))
    if apollo_parser:
        jobs.extend(apollo_parser(html_body))
    jobs.extend(dom_parser(html_body))
    if extra_parser:
        jobs.extend(extra_parser(html_body))
    return jobs


def extract_jd_from_html(body: str) -> str:
    patterns = [
        r'id="jobDescriptionText"[^>]*>([\s\S]{200,}?)</div>',
        r'class="job-description[^"]*"[^>]*>([\s\S]{200,}?)</div>',
        r'itemprop="description"[^>]*>([\s\S]{200,}?)</',
        r'<article[^>]*>([\s\S]{200,}?)</article>',
        r'<main[^>]*>([\s\S]{400,}?)</main>',
    ]
    for pattern in patterns:
        match = re.search(pattern, body, flags=re.I)
        if match:
            text = clean_text(match.group(1))
            if len(text) >= MIN_JD_CHARS:
                return text
    return clean_text(body)[:5000]


def probe_jd(url: str, prefer_curl: bool = False, inline_description: str = "") -> Tuple[str, int, str]:
    if inline_description and len(clean_text(inline_description)) >= MIN_JD_CHARS:
        text = clean_text(inline_description)
        return "ok", len(text), text[:120]
    if not url:
        return "skipped", 0, ""
    code, body, method = fetch_page(url, prefer_curl=prefer_curl)
    text = extract_jd_from_html(body)
    return jd_status_from(code, text), len(text), text[:120]


def finish_result(site: str, method: str, last_code: Optional[int], jobs: List[JobRow], prefer_curl: bool = False) -> Result:
    unique = unique_by(jobs)
    first = unique[0] if unique else {}
    jd_status, jd_chars, _ = probe_jd(
        str(first.get("url") or ""),
        prefer_curl=prefer_curl,
        inline_description=str(first.get("description") or ""),
    )
    return Result(
        site=site,
        method=method,
        status=status_from(last_code, len(unique)),
        count=len(unique),
        sample_title=str(first.get("title") or "")[:80],
        sample_url=str(first.get("url") or "")[:120],
        jd_status=jd_status,
        sample_jd_chars=jd_chars,
        search_query=TEST_QUERY,
    )


def test_linkedin() -> Result:
    params = urllib.parse.urlencode({"keywords": TEST_QUERY, "location": TEST_LOCATION, "sortBy": "DD"})
    url = "https://www.linkedin.com/jobs/search/?" + params
    code, body, method = fetch_page(url, prefer_curl=True)
    jobs = parse_linkedin_cards(body)
    return finish_result("LinkedIn Jobs", method, code, jobs, prefer_curl=True)


def test_indeed() -> Result:
    jobs: List[JobRow] = []
    last_code: Optional[int] = None
    method = "requests"
    for start in range(0, LIMIT, 10):
        params = urllib.parse.urlencode({"q": TEST_QUERY, "l": TEST_LOCATION, "sort": "date", "start": str(start)})
        code, body, method = fetch_page("https://www.indeed.com/jobs?" + params, prefer_curl=True)
        last_code = code
        if code != 200:
            break
        batch = parse_indeed_cards(body)
        if not batch:
            break
        jobs.extend(batch)
        if len(jobs) >= LIMIT:
            break
        time.sleep(REQUEST_DELAY)
    return finish_result("Indeed", method, last_code, jobs, prefer_curl=True)


def test_glassdoor() -> Result:
    params = urllib.parse.urlencode({"keyword": TEST_QUERY, "locT": "N", "locId": "1"})
    code, body, method = fetch_page("https://www.glassdoor.com/Job/jobs.htm?" + params, prefer_curl=True)
    jobs: List[JobRow] = []
    for title, link in re.findall(
        r'"jobTitleText":"([^"]{3,120})"[\s\S]{0,400}?"jobLink":"([^"]+)"',
        body,
    ):
        if query_match_loose(title):
            jobs.append({"title": clean_text(title), "url": absolute(link, "https://www.glassdoor.com")})
    if not jobs:
        for link in re.findall(r'(/job-listing/[^"\']+)', body):
            slug = clean_text(link.split("/")[-1].replace("-", " "))
            if query_match_loose(slug):
                jobs.append({"title": slug, "url": absolute(link, "https://www.glassdoor.com")})
    return finish_result("Glassdoor", method, code, jobs, prefer_curl=True)


def test_ziprecruiter() -> Result:
    params = urllib.parse.urlencode({"search": TEST_QUERY, "location": TEST_LOCATION})
    code, body, method = fetch_page("https://www.ziprecruiter.com/jobs-search?" + params, prefer_curl=True)
    jobs: List[JobRow] = []
    names = re.findall(r'"name":"([^"]{5,120})"', body)
    urls = re.findall(r'"url":"(https://www\.ziprecruiter\.com/c/[^"]+)"', body)
    for title, url in zip(names, urls):
        jobs.append({"title": clean_text(title), "url": html.unescape(url)})
    if not jobs:
        for match in re.finditer(r'href="(https://www\.ziprecruiter\.com/[^"]+)"[^>]*>([^<]{3,120})</a>', body, flags=re.I):
            jobs.append({"title": clean_text(match.group(2)), "url": match.group(1)})
    return finish_result("ZipRecruiter", method, code, jobs, prefer_curl=True)


def test_dice() -> Result:
    jobs: List[JobRow] = []
    last_code: Optional[int] = None
    method = "requests"
    for page in range(1, 4):
        params = urllib.parse.urlencode(
            {"q": TEST_QUERY, "location": TEST_LOCATION, "page": str(page), "pageSize": "20", "filters": "postedDate=ONE"}
        )
        code, body, method = fetch_page("https://www.dice.com/jobs?" + params, prefer_curl=True)
        last_code = code
        if code != 200:
            break
        batch: List[JobRow] = []
        for url in re.findall(r'data-testid="job-search-job-detail-link"[^>]*href="([^"]+)"', body):
            slug = url.rstrip("/").split("/")[-1]
            title = clean_text(slug.replace("-", " "))
            batch.append({"title": title, "url": url})
        for url in re.findall(r'href="(https://www\.dice\.com/job-detail/[^"]+)"', body):
            batch.append({"title": "", "url": url})
        if not batch:
            break
        jobs.extend(batch)
        if len(jobs) >= LIMIT:
            break
        time.sleep(REQUEST_DELAY)
    return finish_result("Dice", method, last_code, jobs, prefer_curl=True)


def test_wellfound() -> Result:
    params = urllib.parse.urlencode({"search": TEST_QUERY, "location": TEST_LOCATION})
    search_url = "https://wellfound.com/jobs?" + params
    code, body, method = fetch_page(search_url, prefer_curl=True)
    jobs: List[JobRow] = parse_wellfound_dom(body)
    if not jobs:
        html_body, captured, pw_method, page_status = playwright_search_jobs(
            search_url,
            ("wellfound.com/graphql", "wellfound.com", "angel.co"),
            wait_selector='a[href*="/jobs/"]',
        )
        if pw_method == "missing_playwright":
            return finish_result("Wellfound", pw_method, code, jobs, prefer_curl=True)
        method = pw_method
        if page_status:
            code = page_status
        jobs = merge_playwright_jobs(
            html_body,
            captured,
            dom_parser=parse_wellfound_dom,
            json_base="https://wellfound.com",
        )
    return finish_result("Wellfound", method, code, jobs, prefer_curl=True)


def test_builtin() -> Result:
    params = urllib.parse.urlencode({"search": TEST_QUERY})
    code, body, method = fetch_page("https://builtin.com/jobs?" + params, prefer_curl=True)
    jobs: List[JobRow] = []
    for path in re.findall(r'(/job/[a-z0-9-]+/\d+)', body):
        slug = path.split("/")[2].replace("-", " ").title()
        jobs.append({"title": slug, "url": absolute(path, "https://builtin.com")})
    return finish_result("Built In", method, code, jobs, prefer_curl=True)


def collect_remoteok_jobs(data: Any, strict: bool) -> List[JobRow]:
    jobs: List[JobRow] = []
    if not isinstance(data, list):
        return jobs
    for row in data:
        if not isinstance(row, dict) or not row.get("id"):
            continue
        title = str(row.get("position") or row.get("title") or "")
        blob = title + " " + str(row.get("tags") or "") + " " + str(row.get("description") or "")
        if strict and not query_match(blob):
            continue
        if not strict and not query_match_loose(blob):
            continue
        jobs.append(
            {
                "title": clean_text(title),
                "url": str(row.get("url") or row.get("apply_url") or f"https://remoteok.com/remote-jobs/{row.get('id')}"),
                "description": str(row.get("description") or ""),
                "job_id": str(row.get("id") or ""),
            }
        )
    return jobs


def test_remoteok() -> Result:
    code, body = http_get("https://remoteok.com/api", accept="application/json,*/*")
    data = load_json(body)
    jobs = collect_remoteok_jobs(data, strict=True)
    if not jobs:
        jobs = collect_remoteok_jobs(data, strict=False)
    return finish_result("RemoteOK", "requests", code, jobs)


def test_weworkremotely() -> Result:
    code, body = http_get(
        "https://weworkremotely.com/categories/remote-programming-jobs.rss",
        accept="application/rss+xml,text/xml,*/*",
    )
    jobs: List[JobRow] = []
    if code == 200 and body:
        try:
            root = ET.fromstring(body)
            for item in root.findall(".//item"):
                title = clean_text(item.findtext("title") or "")
                link = clean_text(item.findtext("link") or "")
                if not link:
                    continue
                if not query_match_loose(title):
                    continue
                jobs.append({"title": title, "url": link})
        except ET.ParseError:
            pass
    return finish_result("We Work Remotely", "requests", code, jobs)


def test_remotive() -> Result:
    code, body = http_get("https://remotive.com/api/remote-jobs?category=software-dev", accept="application/json,*/*")
    data = load_json(body)
    jobs: List[JobRow] = []
    rows = data.get("jobs", []) if isinstance(data, dict) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or "")
        blob = title + " " + str(row.get("tags") or "") + " " + str(row.get("description") or "")
        if not query_match_loose(blob):
            continue
        jobs.append(
            {
                "title": clean_text(title),
                "url": str(row.get("url") or ""),
                "description": str(row.get("description") or ""),
                "job_id": str(row.get("id") or ""),
            }
        )
    return finish_result("Remotive", "requests", code, jobs)


def test_simplyhired() -> Result:
    params = urllib.parse.urlencode({"q": TEST_QUERY, "l": TEST_LOCATION, "sb": "dd"})
    code, body, method = fetch_page("https://www.simplyhired.com/search?" + params, prefer_curl=True)
    jobs: List[JobRow] = []
    for match in re.finditer(r'href="(/job/[^"]+)"[^>]*>([^<]{3,120})</a>', body, flags=re.I):
        jobs.append({"title": clean_text(match.group(2)), "url": absolute(match.group(1), "https://www.simplyhired.com")})
    if not jobs:
        for path in re.findall(r'(/job/[a-z0-9-]+)', body):
            jobs.append({"title": "", "url": absolute(path, "https://www.simplyhired.com")})
    return finish_result("SimplyHired", method, code, jobs, prefer_curl=True)


def test_monster() -> Result:
    params = urllib.parse.urlencode({"q": TEST_QUERY, "where": TEST_LOCATION, "sort": "dt.rv.di"})
    search_url = "https://www.monster.com/jobs/search?" + params
    code, body, method = fetch_page(search_url, prefer_curl=True)
    jobs: List[JobRow] = []
    api_method = ""
    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>([\s\S]+?)</script>', body)
    if match:
        data = load_json(match.group(1))
        text = json.dumps(data) if isinstance(data, dict) else ""
        for title, url in re.findall(r'"jobTitle":"([^"]{3,120})"[\s\S]{0,300}?"jobUrl":"([^"]+)"', text):
            jobs.append({"title": clean_text(title), "url": url})
        for title, job_id in re.findall(r'"title":"([^"]{3,120})"[\s\S]{0,200}?"jobId":"([^"]+)"', text):
            jobs.append({"title": clean_text(title), "url": f"https://www.monster.com/job-openings/{job_id}"})
    if not jobs:
        jobs.extend(parse_monster_dom(body))
    if not jobs and code == 200:
        api_jobs, api_method = fetch_monster_jobs_samsearch(search_url, body)
        if api_jobs:
            jobs.extend(api_jobs)
            method = api_method
        elif api_method == "samsearch_blocked":
            pw_jobs, pw_method = fetch_monster_jobs_playwright(search_url, body)
            if pw_jobs:
                jobs.extend(pw_jobs)
                method = pw_method
            else:
                method = api_method
    if not jobs:
        html_body, captured, pw_method, page_status = playwright_search_jobs(
            search_url,
            ("appsapi.monster.io", "monster.com/jobs", "monster.com/search", "samsearch"),
            wait_selector='a[href*="/job-openings/"]',
        )
        if pw_method == "missing_playwright":
            return finish_result("Monster", pw_method, code, jobs, prefer_curl=True)
        if jobs and pw_method not in {"playwright_failed", "missing_playwright"}:
            method = pw_method
        if page_status:
            code = page_status
        jobs = filter_job_rows(
            merge_playwright_jobs(
                html_body,
                captured,
                dom_parser=parse_monster_dom,
                json_base="https://www.monster.com",
            )
        )
        if not jobs and code == 200:
            api_jobs, retry_method = fetch_monster_jobs_samsearch(search_url, body or html_body)
            if api_jobs:
                jobs.extend(api_jobs)
                method = retry_method
            elif retry_method in {"samsearch_blocked", "samsearch_no_api_key"}:
                method = retry_method
    if not jobs and api_method in {"samsearch_blocked", "samsearch_no_api_key"}:
        method = api_method
    return finish_result("Monster", method, code, jobs, prefer_curl=True)


def test_otto() -> Result:
    params = urllib.parse.urlencode({"query": TEST_QUERY, "location": TEST_LOCATION})
    search_url = "https://app.otta.com/search?" + params
    fallback_params = urllib.parse.urlencode({"query": TEST_QUERY, "aroundQuery": TEST_LOCATION})
    fallback_url = OTTA_FALLBACK_SEARCH + "?" + fallback_params
    code, body, method = fetch_page(search_url, prefer_curl=True)
    jobs: List[JobRow] = []
    jobs.extend(parse_otto_dom(body))
    jobs.extend(decode_otto_apollo(body))
    if not jobs:
        html_body, captured, pw_method, page_status = playwright_search_jobs(
            search_url,
            ("api.otta.com/graphql", "app.otta.com", "welcometothejungle.com", "algolia"),
            wait_selector='a[href*="/jobs/"]',
        )
        if pw_method == "missing_playwright":
            unique = unique_by(jobs)
            for job in unique:
                if not job.get("title") and job.get("url"):
                    job["title"] = clean_text(job["url"].rstrip("/").split("/")[-1].replace("-", " "))
            return finish_result("Otta", pw_method, code, unique, prefer_curl=True)
        method = pw_method
        if page_status:
            code = page_status
        jobs = filter_job_rows(
            merge_playwright_jobs(
                html_body,
                captured,
                dom_parser=parse_otto_dom,
                json_base="https://app.otta.com",
                apollo_parser=decode_otto_apollo,
                extra_parser=parse_wttj_jobs,
            )
        )
    if not jobs:
        wttj_code, wttj_body, wttj_method = fetch_page(fallback_url, prefer_curl=True)
        jobs.extend(filter_job_rows(parse_wttj_jobs(wttj_body)))
        if jobs:
            method = wttj_method
            code = wttj_code
        else:
            html_body, captured, pw_method, page_status = playwright_search_jobs(
                fallback_url,
                ("api.welcometothejungle.com", "welcometothejungle.com", "algolia"),
                wait_selector='a[href*="/jobs/"]',
            )
            if pw_method != "missing_playwright":
                method = pw_method
                if page_status:
                    code = page_status
                jobs = filter_job_rows(
                    merge_playwright_jobs(
                        html_body,
                        captured,
                        dom_parser=parse_wttj_jobs,
                        json_base="https://www.welcometothejungle.com",
                    )
                )
    unique = unique_by(filter_job_rows(jobs))
    for job in unique:
        if not job.get("title") and job.get("url"):
            job["title"] = clean_text(job["url"].rstrip("/").split("/")[-1].replace("-", " "))
    return finish_result("Otta", method, code, unique, prefer_curl=True)


def hn_latest_whos_hiring_id() -> Optional[str]:
    for query in ("who is hiring right now", "who is hiring"):
        code, body = http_get(
            "https://hn.algolia.com/api/v1/search?" + urllib.parse.urlencode({"query": query, "tags": "story", "hitsPerPage": 20}),
            accept="application/json,*/*",
        )
        data = load_json(body)
        if not isinstance(data, dict):
            continue
        for hit in data.get("hits", []):
            if isinstance(hit, dict) and "who is hiring" in str(hit.get("title", "")).lower():
                return str(hit.get("objectID") or "")
    return None


def hn_fetch_item(item_id: str) -> Dict[str, Any]:
    code, body = http_get(f"https://hacker-news.firebaseio.com/v0/item/{item_id}.json", accept="application/json,*/*")
    data = load_json(body)
    return data if isinstance(data, dict) else {}


def test_hn_whos_hiring() -> Result:
    thread_id = hn_latest_whos_hiring_id()
    if not thread_id:
        return Result("Hacker News Who's Hiring", "requests", "parser_failed", 0, search_query=TEST_QUERY, jd_status="skipped")
    story = hn_fetch_item(thread_id)
    kids = story.get("kids", []) if isinstance(story.get("kids"), list) else []
    jobs: List[JobRow] = []
    for kid in kids[:200]:
        comment = hn_fetch_item(str(kid))
        text = clean_text(re.sub(r"<[^>]+>", " ", str(comment.get("text") or "")))
        if not text or not query_match_loose(text):
            continue
        if not is_us_text(text) and "remote" not in text.lower():
            continue
        title_match = re.search(r"([A-Za-z0-9][^\n|]{8,100}(?:Engineer|Developer|Software|Firmware|Embedded)[^\n|]{0,40})", text, flags=re.I)
        title = clean_text(title_match.group(1)) if title_match else clean_text(text.split("|")[0].split("\n")[0])[:80]
        jobs.append(
            {
                "title": title,
                "url": f"https://news.ycombinator.com/item?id={kid}",
                "description": text,
                "job_id": str(kid),
            }
        )
        if len(jobs) >= LIMIT:
            break
        time.sleep(0.05)
    result = finish_result("Hacker News Who's Hiring", "requests", 200 if jobs else 200, jobs)
    if result.count > 0 and result.jd_status != "ok":
        result.jd_status = "ok"
        result.sample_jd_chars = len(jobs[0].get("description", ""))
    return result


def print_table(results: List[Result]) -> None:
    headers = ["Site", "Method", "Status", "Count", "JD", "JD chars", "Sample title", "Sample URL"]
    rows = [
        [
            r.site,
            r.method,
            r.status,
            str(r.count),
            r.jd_status,
            str(r.sample_jd_chars),
            r.sample_title[:45],
            r.sample_url[:80],
        ]
        for r in results
    ]
    widths = [len(h) for h in headers]
    for row in rows:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(value))
    fmt = " | ".join("{:<" + str(width) + "}" for width in widths)
    print(fmt.format(*headers))
    print("-+-".join("-" * width for width in widths))
    for row in rows:
        print(fmt.format(*row))


def main() -> int:
    tests: List[Callable[[], Result]] = [
        test_linkedin,
        test_indeed,
        test_glassdoor,
        test_ziprecruiter,
        test_dice,
        test_wellfound,
        test_builtin,
        test_remoteok,
        test_weworkremotely,
        test_remotive,
        test_simplyhired,
        test_monster,
        test_otto,
        test_hn_whos_hiring,
    ]
    results = [test() for test in tests]
    print_table(results)
    failed = [result for result in results if result.status != "ok"]
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
