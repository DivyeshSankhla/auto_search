#!/usr/bin/env python3
"""
Unified simple job-source tester.

Purpose:
  Test the exact source access methods intended for the real job-search script.

Sources:
  NVIDIA     requests PCS API
  Apple      requests static HTML
  Google     requests static HTML / job ID parser
  Microsoft  requests PCS API
  Meta       Playwright rendered HTML
  OpenAI     requests Ashby API
  Amazon     requests search JSON
  Waymo      requests Greenhouse API
  Qualcomm   requests PCS API
  Tesla      curl_cffi official detail URL verification

Install optional dependencies:
  pip install playwright curl_cffi
  playwright install chromium

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
from typing import Any, Dict, List, Optional, Tuple


USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

TIMEOUT = 20
LIMIT = 50


TESLA_URLS = [
    "https://www.tesla.com/careers/search/job/firmware-engineer-silicon-tesla-ai-263752",
    "https://www.tesla.com/careers/search/job/embedded-firmware-engineer-battery-management-system-254793",
    "https://www.tesla.com/careers/search/job/embedded-software-engineer-reliability-test--260562",
    "https://www.tesla.com/careers/search/job/integration-engineer-drive-inverter-firmware-vehicle-software-239741",
    "https://www.tesla.com/careers/search/job/sr-embedded-firmware-development-engineer--251119",
]


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


def http_get(url: str) -> Tuple[Optional[int], str]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json,text/html,*/*",
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


def title_from_slug(url: str) -> str:
    slug = urllib.parse.urlparse(url).path.rstrip("/").split("/")[-1]
    slug = re.sub(r"-?[0-9]{5,}$", "", slug).strip("-")
    return slug.replace("-", " ").title()


def req_id_from_url(url: str) -> str:
    slug = urllib.parse.urlparse(url).path.rstrip("/").split("/")[-1]
    m = re.search(r"([0-9]{5,})$", slug)
    return m.group(1) if m else ""


def test_pcs(company: str, endpoint: str, domain: str, base: str) -> Result:
    jobs: List[Dict[str, Any]] = []
    sample_title = ""
    sample_url = ""
    last_code = None

    for start in range(0, LIMIT, 10):
        params = {
            "domain": domain,
            "location": "United States",
            "start": str(start),
            "sort_by": "timestamp",
        }
        url = endpoint + "?" + urllib.parse.urlencode(params)
        code, body = http_get(url)
        last_code = code

        if code != 200:
            break

        data = load_json(body)
        positions = []

        if isinstance(data, dict):
            if isinstance(data.get("data"), dict) and isinstance(data["data"].get("positions"), list):
                positions = data["data"]["positions"]
            elif isinstance(data.get("positions"), list):
                positions = data["positions"]

        if not positions:
            break

        if not sample_title:
            first = positions[0]
            sample_title = str(first.get("name") or first.get("title") or "")
            raw_url = str(first.get("publicUrl") or first.get("positionUrl") or first.get("canonicalPositionUrl") or "")
            sample_url = absolute(raw_url, base)

        jobs.extend(positions)
        time.sleep(0.1)

    return Result(company, "requests", status_from(last_code, len(jobs)), len(jobs), sample_title, sample_url)


def test_apple() -> Result:
    url = "https://jobs.apple.com/en-us/search?sort=newest&location=united-states-USA&page=1"
    code, body = http_get(url)

    links = re.findall(r'href=["\']([^"\']*/en-us/details/[^"\']+)["\']', body, flags=re.I)

    urls = []
    for link in links:
        full = absolute(link, "https://jobs.apple.com")
        if full not in urls:
            urls.append(full)

    sample_url = urls[0] if urls else ""
    sample_title = title_from_slug(sample_url) if sample_url else ""

    return Result("Apple", "requests", status_from(code, len(urls)), len(urls), sample_title, sample_url)


def test_google() -> Result:
    url = "https://www.google.com/about/careers/applications/jobs/results?location=United%20States&sort_by=date&page=1"
    code, body = http_get(url)

    decoded = (
        body.replace("\\u002F", "/")
            .replace("\\u002f", "/")
            .replace("\\/", "/")
    )

    ids = re.findall(r"/about/careers/applications/jobs/results/([0-9]{6,})", decoded)

    if not ids:
        # Conservative fallback from Google Careers static JS blobs.
        if "careers/applications/jobs" in decoded.lower() or "google careers" in decoded.lower():
            ids = re.findall(r"\b([0-9]{12,22})\b", decoded)

    unique_ids = []
    for jid in ids:
        if jid not in unique_ids:
            unique_ids.append(jid)

    sample_url = ""
    if unique_ids:
        sample_url = f"https://www.google.com/about/careers/applications/jobs/results/{unique_ids[0]}"

    return Result("Google", "requests", status_from(code, len(unique_ids)), len(unique_ids), "", sample_url)


def test_ashby(company: str, board: str) -> Result:
    url = f"https://api.ashbyhq.com/posting-api/job-board/{board}"
    code, body = http_get(url)
    data = load_json(body)

    jobs = data.get("jobs", []) if isinstance(data, dict) else []
    first = jobs[0] if jobs else {}

    return Result(
        company,
        "requests",
        status_from(code, len(jobs)),
        len(jobs),
        str(first.get("title") or ""),
        str(first.get("jobUrl") or ""),
    )


def test_amazon() -> Result:
    params = {"country": "USA", "sort": "recent", "result_limit": str(LIMIT)}
    url = "https://www.amazon.jobs/en/search.json?" + urllib.parse.urlencode(params)
    code, body = http_get(url)
    data = load_json(body)

    jobs = data.get("jobs", []) if isinstance(data, dict) else []
    first = jobs[0] if jobs else {}

    return Result(
        "Amazon",
        "requests",
        status_from(code, len(jobs)),
        len(jobs),
        str(first.get("title") or ""),
        absolute(str(first.get("job_path") or ""), "https://www.amazon.jobs"),
    )


def test_greenhouse(company: str, board: str) -> Result:
    url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true"
    code, body = http_get(url)
    data = load_json(body)

    jobs = data.get("jobs", []) if isinstance(data, dict) else []
    first = jobs[0] if jobs else {}

    return Result(
        company,
        "requests",
        status_from(code, len(jobs)),
        len(jobs),
        str(first.get("title") or ""),
        str(first.get("absolute_url") or ""),
    )


def parse_meta_jobs(body: str) -> List[Tuple[str, str]]:
    jobs = []

    pattern = re.compile(
        r'<a\b(?=[^>]*href=["\'](?P<href>/profile/job_details/(?P<id>\d+)[^"\']*)["\'])[^>]*>(?P<inner>.*?)</a>',
        flags=re.I | re.S,
    )

    for match in pattern.finditer(body or ""):
        href = html.unescape(match.group("href"))
        inner = match.group("inner")

        title_match = re.search(r"<h3[^>]*>(.*?)</h3>", inner, flags=re.I | re.S)
        title = clean_text(title_match.group(1)) if title_match else clean_text(inner)
        url = "https://www.metacareers.com" + href

        jobs.append((title, url))

    seen = set()
    out = []
    for title, url in jobs:
        if url in seen:
            continue
        seen.add(url)
        out.append((title, url))

    return out


def test_meta() -> Result:
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return Result("Meta", "playwright", "missing_playwright", 0, "", "pip install playwright && playwright install chromium")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=USER_AGENT)
            resp = page.goto("https://www.metacareers.com/jobsearch/?page=1", wait_until="domcontentloaded", timeout=45000)

            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass

            for _ in range(4):
                page.mouse.wheel(0, 2000)
                page.wait_for_timeout(1000)

            body = page.content()
            code = resp.status if resp else None
            browser.close()

        jobs = parse_meta_jobs(body)
        sample_title, sample_url = jobs[0] if jobs else ("", "")

        return Result("Meta", "playwright", status_from(code, len(jobs)), len(jobs), sample_title, sample_url)

    except Exception:
        return Result("Meta", "playwright", "failed", 0)


def get_tesla(url: str) -> Tuple[int, str]:
    try:
        from curl_cffi import requests
    except Exception:
        return 0, ""

    try:
        r = requests.get(
            url,
            impersonate="chrome124",
            timeout=25,
            headers={
                "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "accept-language": "en-US,en;q=0.9",
            },
        )
        return r.status_code, r.text
    except Exception:
        return 0, ""


def test_tesla() -> Result:
    try:
        import curl_cffi  # noqa: F401
    except Exception:
        return Result("Tesla", "curl_cffi", "missing_curl_cffi", 0, "", "pip install curl_cffi")

    ok_urls = []
    sample_title = ""
    sample_url = ""

    for url in TESLA_URLS:
        code, body = get_tesla(url)

        if code != 200:
            continue

        title = ""
        h1 = re.search(r"<h1[^>]*>(.*?)</h1>", body, flags=re.I | re.S)
        if h1:
            title = clean_text(h1.group(1))

        if not title or title.lower() in {"tesla careers", "build your career at tesla"}:
            title = title_from_slug(url)

        req_id = ""
        text = clean_text(body)
        req_match = re.search(r"Req\.?\s*ID\s*[:#]?\s*([0-9]{5,})", text, flags=re.I)
        if req_match:
            req_id = req_match.group(1)

        if not req_id:
            req_id = req_id_from_url(url)

        if title and req_id:
            ok_urls.append(url)

            if not sample_title:
                sample_title = title
                sample_url = url

    return Result("Tesla", "curl_cffi", status_from(200, len(ok_urls)), len(ok_urls), sample_title, sample_url)


def print_table(results: List[Result]) -> None:
    headers = ["Company", "Method", "Status", "Count", "Sample title", "Sample URL / Note"]
    rows = []

    for r in results:
        rows.append([
            r.company,
            r.method,
            r.status,
            str(r.count),
            r.sample_title[:50],
            r.sample_url[:95],
        ])

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
        lambda: test_pcs("NVIDIA", "https://jobs.nvidia.com/api/pcsx/search", "nvidia.com", "https://jobs.nvidia.com"),
        test_apple,
        test_google,
        lambda: test_pcs("Microsoft", "https://apply.careers.microsoft.com/api/pcsx/search", "microsoft.com", "https://apply.careers.microsoft.com"),
        test_meta,
        lambda: test_ashby("OpenAI", "openai"),
        test_amazon,
        lambda: test_greenhouse("Waymo", "waymo"),
        lambda: test_pcs("Qualcomm", "https://careers.qualcomm.com/api/pcsx/search", "qualcomm.com", "https://careers.qualcomm.com"),
        test_tesla,
    ]

    results = [test() for test in tests]
    print_table(results)

    failed = [r for r in results if r.status != "ok"]
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
