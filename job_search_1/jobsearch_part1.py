#!/usr/bin/env python3
"""
Part 1 job-search automation.

This script implements the repeatable /jobsearch flow for job_search_1 only:
official source access, normalization, relevance filtering, sponsorship checks,
ledger dedupe, scoring, dry-run reporting, and optional append.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


ROOT = os.path.dirname(os.path.abspath(__file__))
DOCS_DIR = os.path.join(ROOT, "..", "jobsearchdocs")
PREFERENCES_PATH = os.path.join(DOCS_DIR, "job_search_preferences.json")
PROFILE_PATH = os.path.join(DOCS_DIR, "job_search_profile.json")
GUIDE_PATH = os.path.join(DOCS_DIR, "company_search_guide_part_01.md")
LEDGER_PATH = os.path.join(DOCS_DIR, "jobs_found.md")

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

DEFAULT_LIMIT = 50
DEFAULT_DAYS = 3
TIMEOUT = 20
REQUEST_DELAY_SECONDS = 0.15
MAX_RETRIES = 3

DATE_CONFIRMED_RECENT = "confirmed_recent"
DATE_OLD = "old"
DATE_HIDDEN = "posted_hidden_top_results"

RANKED_TERMS = [
    "firmware",
    "embedded linux",
    "linux kernel",
    "kernel",
    "device driver",
    "device drivers",
    "systems software",
    "system software",
    "platform software",
    "embedded software",
    "operating systems",
    "networking",
    "connectivity",
    "performance",
    "robotics",
    "rtos",
    "bootloader",
    "uefi",
    "bios",
    "openbmc",
    "bmc",
    "tcp/ip",
    "c++",
    "embedded c",
]

COMPANY_TERMS = {
    "NVIDIA": [
        "preboot",
        "cuda driver",
        "robotics platform",
        "networking firmware",
        "security firmware",
        "tegra",
        "soc",
    ],
    "Apple": [
        "core os",
        "darwin",
        "platform firmware",
        "os diagnostics",
        "pcie",
        "wireless",
        "security",
    ],
    "Google": [
        "android kernel",
        "chromeos",
        "platforms and devices",
        "pixel",
        "xr",
        "tcp/ip",
        "systems security",
    ],
    "Microsoft": [
        "sonic",
        "azure hardware",
        "dpu",
        "uefi",
        "boot",
        "security firmware",
        "windows internals",
    ],
    "Meta": [
        "coreos",
        "core android",
        "os frameworks",
        "reality labs",
        "bsp",
        "connectivity firmware",
        "android kernel",
    ],
    "OpenAI": [
        "host systems",
        "kernel drivers",
        "networking operating system",
        "sonic",
        "sai",
        "frr",
        "hardware systems",
        "platform drivers",
    ],
    "Amazon": [
        "lab126",
        "ring",
        "blink",
        "annapurna",
        "aws hardware",
        "accelerator firmware",
        "robotics firmware",
        "nitro",
    ],
    "Waymo": [
        "vehicle platforms",
        "onboard infrastructure",
        "telematics",
        "android automotive",
        "core platforms",
        "edge computers",
        "real-time",
    ],
    "Qualcomm": [
        "linux bsp",
        "android kernel",
        "iot linux",
        "bootloader",
        "crypto",
        "qemu",
        "systemc",
        "soc",
        "acpi",
        "arm server",
    ],
    "Tesla": [
        "ai linux systems",
        "silicon firmware",
        "vehicle software",
        "body controls firmware",
        "battery management firmware",
        "drive inverter firmware",
        "power electronics firmware",
        "optimus embedded",
    ],
}

TESLA_SEED_URLS = [
    "https://www.tesla.com/careers/search/job/firmware-engineer-silicon-tesla-ai-263752",
    "https://www.tesla.com/careers/search/job/embedded-firmware-engineer-battery-management-system-254793",
    "https://www.tesla.com/careers/search/job/embedded-software-engineer-reliability-test--260562",
    "https://www.tesla.com/careers/search/job/integration-engineer-drive-inverter-firmware-vehicle-software-239741",
    "https://www.tesla.com/careers/search/job/sr-embedded-firmware-development-engineer--251119",
]

OFFICIAL_DOMAINS = {
    "NVIDIA": ("jobs.nvidia.com",),
    "Apple": ("jobs.apple.com",),
    "Google": ("www.google.com", "google.com"),
    "Microsoft": ("apply.careers.microsoft.com",),
    "Meta": ("www.metacareers.com", "metacareers.com"),
    "OpenAI": ("api.ashbyhq.com", "jobs.ashbyhq.com", "openai.com"),
    "Amazon": ("www.amazon.jobs", "amazon.jobs"),
    "Waymo": ("boards-api.greenhouse.io", "careers.withwaymo.com"),
    "Qualcomm": ("careers.qualcomm.com",),
    "Tesla": ("www.tesla.com", "tesla.com"),
}


@dataclass
class RawJob:
    company: str
    source_method: str
    title: str
    url: str
    job_id: str = ""
    requisition_id: str = ""
    location: str = ""
    work_mode: str = ""
    employment_type: str = ""
    posted_raw: str = ""
    posted_date: Optional[dt.date] = None
    description: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Job:
    company: str
    title: str
    location: str
    work_mode: str
    posted: str
    score: int
    job_id: str
    url: str
    match_reason: str
    concerns: List[str]
    date_status: str
    source_method: str
    reject_reasons: List[str] = field(default_factory=list)


@dataclass
class Health:
    company: str
    method: str
    status: str
    count: int
    note: str = ""


@dataclass
class AdapterResult:
    health: Health
    raw_jobs: List[RawJob]


class RunContext:
    def __init__(self, limit: int, days: int, verbose: bool = False) -> None:
        self.limit = limit
        self.days = days
        self.verbose = verbose
        self.today = dt.date.today()
        self.cutoff = self.today - dt.timedelta(days=days)
        self.search_cache: Dict[str, Tuple[Optional[int], str]] = {}
        self.detail_cache: Dict[str, str] = {}


def read_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Expected object JSON at {path}")
    return data


def clean_text(raw: str) -> str:
    raw = html.unescape(raw or "")
    raw = raw.replace("\xa0", " ")
    raw = re.sub(r"<script[\s\S]*?</script>", " ", raw, flags=re.I)
    raw = re.sub(r"<style[\s\S]*?</style>", " ", raw, flags=re.I)
    raw = re.sub(r"<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", raw).strip()


def html_to_text(raw: str) -> str:
    return clean_text(raw)


def lower_text(*parts: str) -> str:
    return " ".join(p or "" for p in parts).lower()


def absolute(url: str, base: str) -> str:
    return urllib.parse.urljoin(base, url or "")


def title_from_slug(url: str) -> str:
    slug = urllib.parse.urlparse(url).path.rstrip("/").split("/")[-1]
    slug = re.sub(r"-?[0-9]{5,}$", "", slug).strip("-")
    return slug.replace("-", " ").title()


def req_id_from_url(url: str) -> str:
    slug = urllib.parse.urlparse(url).path.rstrip("/").split("/")[-1]
    m = re.search(r"([0-9]{5,})$", slug)
    return m.group(1) if m else ""


def load_json_body(body: str) -> Any:
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


def is_official_url(company: str, url: str) -> bool:
    try:
        host = urllib.parse.urlparse(url).netloc.lower()
    except Exception:
        return False
    return any(host == d or host.endswith("." + d) for d in OFFICIAL_DOMAINS.get(company, ()))


def http_get(ctx: RunContext, url: str, accept: str = "application/json,text/html,*/*") -> Tuple[Optional[int], str]:
    if url in ctx.search_cache:
        return ctx.search_cache[url]

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": accept,
        "Accept-Language": "en-US,en;q=0.9",
    }
    result: Tuple[Optional[int], str] = (None, "")

    for attempt in range(MAX_RETRIES):
        if attempt or ctx.search_cache:
            time.sleep(REQUEST_DELAY_SECONDS * (2 ** attempt))
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                result = (resp.status, body)
                break
        except urllib.error.HTTPError as e:
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:
                body = ""
            result = (e.code, body)
            if e.code not in {403, 429, 500, 502, 503, 504}:
                break
        except Exception:
            result = (None, "")

    ctx.search_cache[url] = result
    return result


def parse_date(value: Any) -> Optional[dt.date]:
    if value is None:
        return None
    if isinstance(value, dt.date):
        return value
    if isinstance(value, (int, float)):
        # PCS timestamps have been observed as Unix seconds.
        try:
            parsed = dt.datetime.fromtimestamp(float(value), tz=dt.timezone.utc).date()
            if dt.date(2020, 1, 1) <= parsed <= dt.date.today() + dt.timedelta(days=2):
                return parsed
        except Exception:
            return None
        return None

    text = str(value).strip()
    if not text:
        return None

    text = re.sub(r"\s+", " ", text)
    if re.fullmatch(r"\d{10,13}", text):
        number = int(text[:10])
        return parse_date(number)

    for fmt in (
        "%Y-%m-%d",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S",
        "%b %d, %Y",
        "%B %d, %Y",
        "%b. %d, %Y",
        "%B %d %Y",
    ):
        try:
            return dt.datetime.strptime(text.replace("Z", "+0000"), fmt).date()
        except Exception:
            pass

    rel = text.lower()
    if "today" in rel:
        return dt.date.today()
    if "yesterday" in rel:
        return dt.date.today() - dt.timedelta(days=1)
    m = re.search(r"(\d+)\s+days?\s+ago", rel)
    if m:
        return dt.date.today() - dt.timedelta(days=int(m.group(1)))
    return None


def posted_label(raw: RawJob) -> str:
    if raw.posted_date:
        return raw.posted_date.isoformat()
    if raw.posted_raw:
        return raw.posted_raw
    return "Posted hidden"


def date_status(raw: RawJob, ctx: RunContext) -> str:
    if not raw.posted_date:
        return DATE_HIDDEN
    if raw.posted_date >= ctx.cutoff:
        return DATE_CONFIRMED_RECENT
    return DATE_OLD


def normalize_location(value: Any) -> str:
    if isinstance(value, str):
        return clean_text(value)
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, str):
                parts.append(clean_text(item))
            elif isinstance(item, dict):
                parts.append(clean_text(str(item.get("name") or item.get("displayName") or item.get("city") or "")))
        return "; ".join(p for p in parts if p)
    if isinstance(value, dict):
        return clean_text(str(value.get("name") or value.get("displayName") or value.get("city") or ""))
    return ""


def extract_json_ld_dates(body: str) -> Tuple[Optional[dt.date], str]:
    dates: List[str] = []
    for match in re.finditer(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', body, flags=re.I | re.S):
        raw = html.unescape(match.group(1)).strip()
        try:
            data = json.loads(raw)
        except Exception:
            continue
        nodes = data if isinstance(data, list) else [data]
        for node in nodes:
            if isinstance(node, dict) and node.get("@type") == "JobPosting":
                value = node.get("datePosted")
                if value:
                    dates.append(str(value))
                    parsed = parse_date(value)
                    if parsed:
                        return parsed, str(value)
    return None, dates[0] if dates else ""


def extract_title_from_html(body: str) -> str:
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", body, flags=re.I | re.S)
    if h1:
        title = clean_text(h1.group(1))
        if title and title.lower() not in {"tesla careers", "build your career at tesla"}:
            return title
    title = re.search(r"<title[^>]*>(.*?)</title>", body, flags=re.I | re.S)
    return clean_text(title.group(1)) if title else ""


class BaseAdapter:
    company = ""
    method = "requests"

    def fetch(self, ctx: RunContext) -> AdapterResult:
        raise NotImplementedError


class PCSAdapter(BaseAdapter):
    method = "requests"

    def __init__(self, company: str, endpoint: str, detail_endpoint: str, domain: str, base: str) -> None:
        self.company = company
        self.endpoint = endpoint
        self.detail_endpoint = detail_endpoint
        self.domain = domain
        self.base = base

    def fetch(self, ctx: RunContext) -> AdapterResult:
        jobs: List[RawJob] = []
        last_code: Optional[int] = None
        seen: set[str] = set()

        for start in range(0, ctx.limit, 10):
            params = {
                "domain": self.domain,
                "location": "United States",
                "start": str(start),
                "sort_by": "timestamp",
            }
            url = self.endpoint + "?" + urllib.parse.urlencode(params)
            code, body = http_get(ctx, url)
            last_code = code
            if code != 200:
                break

            data = load_json_body(body)
            positions: List[Dict[str, Any]] = []
            if isinstance(data, dict):
                if isinstance(data.get("data"), dict) and isinstance(data["data"].get("positions"), list):
                    positions = data["data"]["positions"]
                elif isinstance(data.get("positions"), list):
                    positions = data["positions"]

            if not positions:
                break

            for pos in positions:
                jid = str(pos.get("id") or pos.get("atsJobId") or pos.get("displayJobId") or "")
                if jid and jid in seen:
                    continue
                seen.add(jid)

                raw_url = str(pos.get("publicUrl") or pos.get("positionUrl") or pos.get("canonicalPositionUrl") or "")
                url_out = absolute(raw_url, self.base)
                title = str(pos.get("name") or pos.get("title") or "")
                posted = parse_date(pos.get("postedTs") or pos.get("creationTs"))
                posted_raw = str(pos.get("postedTs") or pos.get("creationTs") or "")
                location = normalize_location(pos.get("locations") or pos.get("standardizedLocations"))
                description = " ".join(
                    str(pos.get(k) or "")
                    for k in ("name", "department", "workLocationOption", "locationFlexibility", "jdHighlight")
                )
                raw = RawJob(
                    company=self.company,
                    source_method=self.method,
                    title=title,
                    url=url_out,
                    job_id=jid,
                    requisition_id=str(pos.get("displayJobId") or pos.get("atsJobId") or ""),
                    location=location,
                    work_mode=str(pos.get("workLocationOption") or pos.get("locationFlexibility") or ""),
                    posted_raw=posted_raw,
                    posted_date=posted,
                    description=description,
                    raw=pos,
                )
                self._enrich_detail(ctx, raw)
                jobs.append(
                    raw
                )
                if len(jobs) >= ctx.limit:
                    break
            if len(jobs) >= ctx.limit:
                break
            time.sleep(REQUEST_DELAY_SECONDS)

        health = Health(self.company, self.method, status_from(last_code, len(jobs)), len(jobs))
        return AdapterResult(health, jobs)

    def _enrich_detail(self, ctx: RunContext, raw: RawJob) -> None:
        if not raw.job_id:
            return
        cache_key = f"{self.company}:{raw.job_id}"
        if cache_key in ctx.detail_cache:
            body = ctx.detail_cache[cache_key]
            code = 200
        else:
            params = {"domain": self.domain, "position_id": raw.job_id}
            if self.company == "Microsoft":
                params["hl"] = "en"
            url = self.detail_endpoint + "?" + urllib.parse.urlencode(params)
            code, body = http_get(ctx, url)
            if code == 200:
                ctx.detail_cache[cache_key] = body

        if code != 200 or not body:
            return
        data = load_json_body(body)
        if not isinstance(data, dict):
            return
        detail = data.get("data") if isinstance(data.get("data"), dict) else data
        if not isinstance(detail, dict):
            return

        raw.title = str(detail.get("name") or detail.get("title") or raw.title)
        raw.url = str(detail.get("publicUrl") or detail.get("canonicalPositionUrl") or detail.get("positionUrl") or raw.url)
        raw.location = normalize_location(detail.get("locations") or detail.get("standardizedLocations")) or raw.location
        raw.work_mode = str(detail.get("workLocationOption") or detail.get("locationFlexibility") or detail.get("efcustomTextWorkSite") or raw.work_mode)
        raw.employment_type = str(detail.get("efcustomTextEmploymentType") or raw.employment_type)
        raw.requisition_id = str(detail.get("displayJobId") or detail.get("atsJobId") or raw.requisition_id)
        parsed_date = parse_date(detail.get("postedTs") or detail.get("creationTs"))
        if parsed_date:
            raw.posted_date = parsed_date
            raw.posted_raw = str(detail.get("postedTs") or detail.get("creationTs") or raw.posted_raw)
        detail_text = " ".join(
            str(detail.get(k) or "")
            for k in (
                "jobDescription",
                "description",
                "jdHighlight",
                "efcustomTextCurrentProfession",
                "efcustomTextTaDisciplineName",
                "efcustomTextRoletype",
                "department",
            )
        )
        if detail_text.strip():
            raw.description = " ".join([raw.description, html_to_text(detail_text)])
        raw.raw.update({"detail": detail})


class AppleAdapter(BaseAdapter):
    company = "Apple"
    method = "requests"

    def fetch(self, ctx: RunContext) -> AdapterResult:
        jobs: List[RawJob] = []
        seen: set[str] = set()
        last_code: Optional[int] = None

        for page in range(1, 15):
            url = f"https://jobs.apple.com/en-us/search?sort=newest&location=united-states-USA&page={page}"
            code, body = http_get(ctx, url)
            last_code = code
            if code != 200:
                break

            links = re.findall(r'href=["\']([^"\']*/en-us/details/[^"\']+)["\']', body, flags=re.I)
            if not links:
                break

            new_on_page = 0
            for link in links:
                full = absolute(link, "https://jobs.apple.com")
                if full in seen:
                    continue
                seen.add(full)
                new_on_page += 1
                title = title_from_slug(full)
                req_match = re.search(r"/details/([^/]+)/", urllib.parse.urlparse(full).path)
                req_id = urllib.parse.unquote(req_match.group(1)) if req_match else req_id_from_url(full)
                posted = None
                # Apple often embeds postingDate around cards; detail pages can hide content.
                jobs.append(
                    RawJob(
                        company=self.company,
                        source_method=self.method,
                        title=title,
                        url=full,
                        job_id=req_id,
                        requisition_id=req_id,
                        location="United States",
                        posted_raw="Posted hidden",
                        posted_date=posted,
                        description=title,
                    )
                )
                if len(jobs) >= ctx.limit:
                    break
            if len(jobs) >= ctx.limit or new_on_page == 0:
                break
            time.sleep(REQUEST_DELAY_SECONDS)

        return AdapterResult(Health(self.company, self.method, status_from(last_code, len(jobs)), len(jobs)), jobs)


class GoogleAdapter(BaseAdapter):
    company = "Google"
    method = "requests"

    def fetch(self, ctx: RunContext) -> AdapterResult:
        jobs: List[RawJob] = []
        seen: set[str] = set()
        last_code: Optional[int] = None

        for page in range(1, 15):
            url = (
                "https://www.google.com/about/careers/applications/jobs/results?"
                + urllib.parse.urlencode({"location": "United States", "sort_by": "date", "page": str(page)})
            )
            code, body = http_get(ctx, url)
            last_code = code
            if code != 200:
                break

            decoded = body.replace("\\u002F", "/").replace("\\u002f", "/").replace("\\/", "/")
            ids = re.findall(r"/about/careers/applications/jobs/results/([0-9]{6,})", decoded)

            if not ids and ("careers/applications/jobs" in decoded.lower() or "google careers" in decoded.lower()):
                ids = re.findall(r"\b([0-9]{12,22})\b", decoded)

            unique_ids = []
            for jid in ids:
                if jid not in unique_ids:
                    unique_ids.append(jid)

            new_on_page = 0
            for jid in unique_ids:
                if jid in seen:
                    continue
                seen.add(jid)
                new_on_page += 1
                detail_url = f"https://www.google.com/about/careers/applications/jobs/results/{jid}"
                title = self._extract_title_near_id(decoded, jid) or "Google Careers Job"
                jobs.append(
                    RawJob(
                        company=self.company,
                        source_method=self.method,
                        title=title,
                        url=detail_url,
                        job_id=jid,
                        requisition_id=jid,
                        location="United States",
                        posted_raw="Posted hidden",
                        description=title,
                    )
                )
                if len(jobs) >= ctx.limit:
                    break

            if len(jobs) >= ctx.limit or new_on_page == 0:
                break
            time.sleep(REQUEST_DELAY_SECONDS)

        return AdapterResult(Health(self.company, self.method, status_from(last_code, len(jobs)), len(jobs)), jobs)

    @staticmethod
    def _extract_title_near_id(body: str, jid: str) -> str:
        idx = body.find(jid)
        if idx < 0:
            return ""
        window = body[max(0, idx - 1500): idx + 1500]
        quoted = re.findall(r'"([^"]{8,120})"', window)
        for item in quoted:
            text = clean_text(item)
            if text and not re.search(r"https?://|/about/careers|google|applications", text, re.I):
                if any(term in text.lower() for term in ("software", "firmware", "engineer", "systems", "kernel", "embedded")):
                    return text
        return ""


class MetaAdapter(BaseAdapter):
    company = "Meta"
    method = "playwright"

    def fetch(self, ctx: RunContext) -> AdapterResult:
        try:
            from playwright.sync_api import sync_playwright
        except Exception:
            return AdapterResult(
                Health(self.company, self.method, "missing_playwright", 0, "pip install playwright && playwright install chromium"),
                [],
            )

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(user_agent=USER_AGENT)
                resp = page.goto("https://www.metacareers.com/jobsearch/?page=1", wait_until="domcontentloaded", timeout=45000)
                try:
                    page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass

                for _ in range(8):
                    page.mouse.wheel(0, 2200)
                    page.wait_for_timeout(800)

                body = page.content()
                code = resp.status if resp else None
                browser.close()
        except Exception as exc:
            return AdapterResult(Health(self.company, self.method, "failed", 0, str(exc)[:80]), [])

        parsed = parse_meta_jobs(body)
        jobs = [
            RawJob(
                company=self.company,
                source_method=self.method,
                title=title,
                url=url,
                job_id=req_id_from_url(url),
                requisition_id=req_id_from_url(url),
                location="United States",
                posted_raw="Posted hidden",
                description=title,
            )
            for title, url in parsed[: ctx.limit]
        ]
        return AdapterResult(Health(self.company, self.method, status_from(code, len(jobs)), len(jobs)), jobs)


def parse_meta_jobs(body: str) -> List[Tuple[str, str]]:
    jobs: List[Tuple[str, str]] = []
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

    seen: set[str] = set()
    out: List[Tuple[str, str]] = []
    for title, url in jobs:
        if url in seen:
            continue
        seen.add(url)
        out.append((title, url))
    return out


class AshbyAdapter(BaseAdapter):
    method = "requests"

    def __init__(self, company: str, board: str) -> None:
        self.company = company
        self.board = board

    def fetch(self, ctx: RunContext) -> AdapterResult:
        url = f"https://api.ashbyhq.com/posting-api/job-board/{self.board}"
        code, body = http_get(ctx, url)
        data = load_json_body(body)
        items = data.get("jobs", []) if isinstance(data, dict) else []
        if not isinstance(items, list):
            items = []

        jobs: List[RawJob] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("isListed") is False:
                continue
            location = normalize_location(item.get("location"))
            secondary = normalize_location(item.get("secondaryLocations"))
            if secondary and secondary not in location:
                location = f"{location}; {secondary}" if location else secondary
            desc = html_to_text(str(item.get("descriptionPlain") or item.get("descriptionHtml") or ""))
            posted = parse_date(item.get("publishedAt"))
            jobs.append(
                RawJob(
                    company=self.company,
                    source_method=self.method,
                    title=str(item.get("title") or ""),
                    url=str(item.get("jobUrl") or item.get("applyUrl") or ""),
                    job_id=str(item.get("id") or ""),
                    requisition_id=str(item.get("id") or ""),
                    location=location,
                    work_mode=str(item.get("workplaceType") or ("remote" if item.get("isRemote") else "")),
                    employment_type=str(item.get("employmentType") or ""),
                    posted_raw=str(item.get("publishedAt") or ""),
                    posted_date=posted,
                    description=" ".join([str(item.get("title") or ""), str(item.get("department") or ""), str(item.get("team") or ""), desc]),
                    raw=item,
                )
            )

        jobs.sort(key=lambda j: j.posted_date or dt.date.min, reverse=True)
        jobs = jobs[: ctx.limit]
        return AdapterResult(Health(self.company, self.method, status_from(code, len(jobs)), len(jobs)), jobs)


class AmazonAdapter(BaseAdapter):
    company = "Amazon"
    method = "requests"

    def fetch(self, ctx: RunContext) -> AdapterResult:
        params = {"country": "USA", "sort": "recent", "result_limit": str(ctx.limit)}
        url = "https://www.amazon.jobs/en/search.json?" + urllib.parse.urlencode(params)
        code, body = http_get(ctx, url)
        data = load_json_body(body)
        items = data.get("jobs", []) if isinstance(data, dict) else []
        if not isinstance(items, list):
            items = []

        jobs: List[RawJob] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            desc = " ".join(
                str(item.get(k) or "")
                for k in ("description", "description_short", "basic_qualifications", "preferred_qualifications", "job_category", "team")
            )
            jid = str(item.get("id_icims") or item.get("id") or "")
            jobs.append(
                RawJob(
                    company=self.company,
                    source_method=self.method,
                    title=str(item.get("title") or ""),
                    url=absolute(str(item.get("job_path") or ""), "https://www.amazon.jobs"),
                    job_id=jid,
                    requisition_id=jid,
                    location=normalize_location(item.get("locations") or item.get("location") or item.get("normalized_location")),
                    work_mode=str(item.get("job_schedule_type") or ""),
                    employment_type=str(item.get("job_schedule_type") or ""),
                    posted_raw=str(item.get("posted_date") or ""),
                    posted_date=parse_date(item.get("posted_date")),
                    description=desc,
                    raw=item,
                )
            )
        return AdapterResult(Health(self.company, self.method, status_from(code, len(jobs)), len(jobs)), jobs[: ctx.limit])


class GreenhouseAdapter(BaseAdapter):
    method = "requests"

    def __init__(self, company: str, board: str) -> None:
        self.company = company
        self.board = board

    def fetch(self, ctx: RunContext) -> AdapterResult:
        url = f"https://boards-api.greenhouse.io/v1/boards/{self.board}/jobs?content=true"
        code, body = http_get(ctx, url)
        data = load_json_body(body)
        items = data.get("jobs", []) if isinstance(data, dict) else []
        if not isinstance(items, list):
            items = []

        jobs: List[RawJob] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            offices = item.get("offices") if isinstance(item.get("offices"), list) else []
            office_locations = "; ".join(normalize_location(o.get("location") or o.get("name")) for o in offices if isinstance(o, dict))
            loc = normalize_location(item.get("location"))
            if office_locations:
                loc = f"{loc}; {office_locations}" if loc else office_locations
            posted = parse_date(item.get("first_published") or item.get("updated_at"))
            jobs.append(
                RawJob(
                    company=self.company,
                    source_method=self.method,
                    title=str(item.get("title") or ""),
                    url=str(item.get("absolute_url") or ""),
                    job_id=str(item.get("id") or ""),
                    requisition_id=str(item.get("requisition_id") or item.get("internal_job_id") or ""),
                    location=loc,
                    posted_raw=str(item.get("first_published") or item.get("updated_at") or ""),
                    posted_date=posted,
                    description=html_to_text(str(item.get("content") or "")),
                    raw=item,
                )
            )

        jobs.sort(key=lambda j: j.posted_date or dt.date.min, reverse=True)
        return AdapterResult(Health(self.company, self.method, status_from(code, len(jobs)), len(jobs)), jobs[: ctx.limit])


class TeslaAdapter(BaseAdapter):
    company = "Tesla"
    method = "curl_cffi"

    def fetch(self, ctx: RunContext) -> AdapterResult:
        try:
            from curl_cffi import requests
        except Exception:
            return AdapterResult(Health(self.company, self.method, "missing_curl_cffi", 0, "pip install curl_cffi"), [])

        jobs: List[RawJob] = []
        for url in TESLA_SEED_URLS[: ctx.limit]:
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
                code, body = r.status_code, r.text
            except Exception:
                continue

            if code != 200:
                continue
            title = extract_title_from_html(body) or title_from_slug(url)
            req_id = ""
            text = clean_text(body)
            req_match = re.search(r"Req\.?\s*ID\s*[:#]?\s*([0-9]{5,})", text, flags=re.I)
            if req_match:
                req_id = req_match.group(1)
            if not req_id:
                req_id = req_id_from_url(url)
            if title and req_id:
                loc = ""
                loc_match = re.search(r"Location\s*[:#]?\s*([^|]{2,120})", text, flags=re.I)
                if loc_match:
                    loc = clean_text(loc_match.group(1))
                jobs.append(
                    RawJob(
                        company=self.company,
                        source_method=self.method,
                        title=title,
                        url=url,
                        job_id=req_id,
                        requisition_id=req_id,
                        location=loc or "United States",
                        posted_raw="Posted hidden",
                        description=text[:10000],
                    )
                )

        return AdapterResult(Health(self.company, self.method, status_from(200, len(jobs)), len(jobs)), jobs)


def build_adapters() -> List[BaseAdapter]:
    return [
        PCSAdapter(
            "NVIDIA",
            "https://jobs.nvidia.com/api/pcsx/search",
            "https://jobs.nvidia.com/api/pcsx/position_details",
            "nvidia.com",
            "https://jobs.nvidia.com",
        ),
        AppleAdapter(),
        GoogleAdapter(),
        PCSAdapter(
            "Microsoft",
            "https://apply.careers.microsoft.com/api/pcsx/search",
            "https://apply.careers.microsoft.com/api/pcsx/position_details",
            "microsoft.com",
            "https://apply.careers.microsoft.com",
        ),
        MetaAdapter(),
        AshbyAdapter("OpenAI", "openai"),
        AmazonAdapter(),
        GreenhouseAdapter("Waymo", "waymo"),
        PCSAdapter(
            "Qualcomm",
            "https://careers.qualcomm.com/api/pcsx/search",
            "https://careers.qualcomm.com/api/pcsx/position_details",
            "qualcomm.com",
            "https://careers.qualcomm.com",
        ),
        TeslaAdapter(),
    ]


def load_context() -> Tuple[Dict[str, Any], Dict[str, Any], str]:
    prefs = read_json(PREFERENCES_PATH)
    profile = read_json(PROFILE_PATH)
    with open(LEDGER_PATH, "r", encoding="utf-8") as f:
        ledger = f.read()
    return prefs, profile, ledger


def ledger_index(ledger: str) -> set[str]:
    keys: set[str] = set()
    for url in re.findall(r"https?://[^\s|)]+", ledger):
        keys.add(url.strip())
    for job_id in re.findall(r"\|\s*([A-Za-z0-9][A-Za-z0-9_.:/ -]{4,})\s*\|", ledger):
        norm = normalize_key(job_id)
        if norm:
            keys.add(norm)
    return keys


def normalize_key(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def job_keys(raw: RawJob) -> List[str]:
    keys = []
    if raw.url:
        keys.append(raw.url.strip())
    if raw.job_id:
        keys.append(normalize_key(raw.job_id))
    if raw.requisition_id:
        keys.append(normalize_key(raw.requisition_id))
    combo = normalize_key(f"{raw.company} {raw.title} {raw.location}")
    if combo:
        keys.append(combo)
    return keys


def is_duplicate(raw: RawJob, existing: set[str], run_seen: set[str]) -> bool:
    keys = job_keys(raw)
    return any(k in existing or k in run_seen for k in keys if k)


def add_seen(raw: RawJob, run_seen: set[str]) -> None:
    for key in job_keys(raw):
        if key:
            run_seen.add(key)


def location_ok(raw: RawJob) -> bool:
    text = lower_text(raw.location, raw.url)
    if not text:
        return raw.company in {"Apple", "Google", "Meta", "Tesla"}
    if any(country in text for country in ("india", "karnataka", "canada", "waterloo", "london, uk", "united kingdom")):
        if not re.search(r"\b(us|usa|united states|remote - us|remote us)\b", text):
            us_city_signal = re.search(
                r"\b(san jose|miami|mountain view|sunnyvale|seattle|austin|san francisco|cupertino|redmond)\b",
                text,
            )
            if not us_city_signal:
                return False
    if "canada" in text and not re.search(r"\b(us|usa|united states|remote - us|remote us|san jose|miami|mountain view|sunnyvale|seattle|austin)\b", text):
        return False
    if any(x in text for x in ("united states", "usa", "us;", " us", "remote - us", "remote us")):
        return True
    state_signal = re.search(
        r"\b(ca|wa|tx|ny|ma|or|co|nc|fl|il|mi|ga|oh|pa|az|nv|va|dc)\b(?:[,; ]|$)",
        text,
    )
    if state_signal:
        return True
    us_signals = [
        "palo alto",
        "cupertino",
        "sunnyvale",
        "mountain view",
        "san jose",
        "san francisco",
        "seattle",
        "redmond",
        "austin",
        "san diego",
        "santa clara",
        "north reading",
        "pasadena",
    ]
    return any(signal in text for signal in us_signals)


SENIOR_TITLE_PATTERNS = (
    r"\bprincipal\b",
    r"\bstaff\b",
    r"\blead\b",
    r"\barchitect\b",
    r"\bdistinguished\b",
    r"\bfellow\b",
    r"\bmanager\b",
    r"\bdirector\b",
    r"\bhead of\b",
    r"\bvp\b",
    r"\bv\.?p\.?\b",
    r"\bvice president\b",
)


def is_new_grad_title(title: str) -> bool:
    return bool(re.search(r"\bgrad\b", title or "", flags=re.I))


def title_exceeds_experience_level(title: str) -> bool:
    if is_new_grad_title(title):
        return False
    return any(re.search(p, title or "", flags=re.I) for p in SENIOR_TITLE_PATTERNS)


def hard_reject_reasons(raw: RawJob, ctx: RunContext) -> List[str]:
    text = lower_text(raw.title, raw.location, raw.work_mode, raw.employment_type, raw.description)
    reasons: List[str] = []

    if not raw.url or not is_official_url(raw.company, raw.url):
        reasons.append("non_official_source")
    if not location_ok(raw):
        reasons.append("location_mismatch")
    if date_status(raw, ctx) == DATE_OLD:
        reasons.append("old_posting")

    reject_patterns = {
        "internship": [r"\bintern(ship)?\b"],
        "part_time": [r"\bpart[- ]time\b", r"\bseasonal\b"],
        "citizenship_required": [
            r"must be (a )?(u\.?s\.?|us) citizen",
            r"(u\.?s\.?|us) citizen required",
            r"citizenship required",
            r"(u\.?s\.?|us) person required",
            r"permanent resident required",
            r"green card required",
        ],
        "clearance_required": [
            r"active .*clearance",
            r"security clearance required",
            r"top secret",
            r"ts/sci",
            r"polygraph",
        ],
        "no_sponsorship": [
            r"no sponsorship",
            r"will not sponsor",
            r"cannot sponsor",
            r"not eligible .*sponsorship",
            r"must not require sponsorship",
            r"without .*sponsorship",
        ],
    }
    for reason, patterns in reject_patterns.items():
        if any(re.search(pattern, text, flags=re.I) for pattern in patterns):
            reasons.append(reason)

    role_bad = [
        "manager",
        "product manager",
        "program manager",
        "technical program manager",
        "tpm",
        "director",
        "sales",
        "recruiter",
        "legal",
        "facilities",
        "financial analyst",
        "business partner",
        "technician",
        "manufacturing",
        "supply chain",
        "customer engineer",
        "field applications engineer",
        "quality assurance",
        "sdet",
        "engineer in test",
        "test development engineer",
    ]
    if any(bad in text for bad in role_bad):
        reasons.append("non_target_role_family")

    if title_exceeds_experience_level(raw.title):
        reasons.append("experience_level_high")

    return sorted(set(reasons))


def term_hits(raw: RawJob, profile: Dict[str, Any]) -> List[str]:
    text = lower_text(raw.title, raw.description, raw.location)
    terms = list(RANKED_TERMS)
    terms.extend(COMPANY_TERMS.get(raw.company, []))
    terms.extend(str(x).lower() for x in profile.get("keywords_include", [])[:80])
    hits = []
    for term in terms:
        t = term.lower().strip()
        if not t or len(t) < 2:
            continue
        if term_in_text(t, text):
            hits.append(t)
    # Keep stable order, unique.
    seen: set[str] = set()
    unique = []
    for hit in hits:
        if hit not in seen:
            seen.add(hit)
            unique.append(hit)
    return unique


def term_in_text(term: str, text: str) -> bool:
    escaped = re.escape(term)
    if re.fullmatch(r"[a-z0-9+#./-]+", term):
        return bool(re.search(rf"(?<![a-z0-9+#./-]){escaped}(?![a-z0-9+#./-])", text))
    return bool(re.search(rf"(?<![a-z0-9+#./-]){escaped}(?![a-z0-9+#./-])", text))


def weak_role_match(raw: RawJob, profile: Dict[str, Any]) -> bool:
    hits = term_hits(raw, profile)
    title_text = raw.title.lower()
    strong_title = any(
        term in title_text
        for term in (
            "firmware",
            "embedded",
            "kernel",
            "driver",
            "systems software",
            "system software",
            "platform software",
            "linux",
            "operating system",
            "robotics",
            "connectivity",
            "network",
            "bios",
            "uefi",
        )
    )
    if strong_title and hits:
        return False
    return len(hits) < 3


def concerns_for(raw: RawJob, ctx: RunContext) -> List[str]:
    concerns = []
    text = lower_text(raw.title, raw.description)
    if "sponsor" not in text and "visa" not in text:
        concerns.append("sponsorship not visible")
    if date_status(raw, ctx) == DATE_HIDDEN:
        concerns.append("posting date hidden")
    if re.search(r"\b(senior|sr\.|staff|principal|lead|architect)\b", raw.title, flags=re.I):
        concerns.append("seniority may be high")
    if any(term in text for term in ("export control", "e-verify", "background check", "government")):
        concerns.append("authorization/export-control language needs review")
    return concerns or ["None visible"]


def score_job(raw: RawJob, profile: Dict[str, Any], ctx: RunContext) -> Tuple[int, str]:
    hits = term_hits(raw, profile)
    title = raw.title.lower()
    score = 55
    title_bonus_terms = [
        "firmware",
        "embedded",
        "kernel",
        "device driver",
        "driver",
        "linux",
        "systems software",
        "system software",
        "platform software",
        "operating system",
        "bios",
        "uefi",
        "boot",
        "connectivity",
        "network",
        "robotics",
    ]
    score += min(24, len(hits) * 3)
    score += sum(3 for term in title_bonus_terms if term in title)
    if date_status(raw, ctx) == DATE_CONFIRMED_RECENT:
        score += 8
    elif date_status(raw, ctx) == DATE_HIDDEN:
        score += 2
    if "sponsorship not visible" in concerns_for(raw, ctx):
        score -= 3
    if re.search(r"\b(principal|staff|lead|architect)\b", title):
        score -= 4
    if raw.company in {"NVIDIA", "OpenAI", "Amazon", "Qualcomm", "Tesla", "Apple", "Google"}:
        score += 3
    score = max(0, min(100, score))

    shown_hits = hits[:8]
    reason = "Matches " + ", ".join(shown_hits) if shown_hits else "Profile-adjacent official posting"
    return score, reason


def classify_jobs(
    raw_jobs: Sequence[RawJob],
    profile: Dict[str, Any],
    ctx: RunContext,
    existing: set[str],
) -> Tuple[List[Job], Counter[str], int]:
    accepted: List[Job] = []
    rejected: Counter[str] = Counter()
    duplicate_count = 0
    run_seen: set[str] = set()

    for raw in raw_jobs:
        if is_duplicate(raw, existing, run_seen):
            rejected["duplicate_ledger"] += 1
            duplicate_count += 1
            continue
        add_seen(raw, run_seen)

        reasons = hard_reject_reasons(raw, ctx)
        if not reasons and weak_role_match(raw, profile):
            reasons.append("weak_role_match")

        if reasons:
            for reason in reasons:
                rejected[reason] += 1
            continue

        score, reason = score_job(raw, profile, ctx)
        if score < 70:
            rejected["low_score"] += 1
            continue

        accepted.append(
            Job(
                company=raw.company,
                title=raw.title or "Untitled",
                location=raw.location or "United States",
                work_mode=raw.work_mode or infer_work_mode(raw),
                posted=posted_label(raw),
                score=score,
                job_id=raw.requisition_id or raw.job_id or "Not visible",
                url=raw.url,
                match_reason=reason,
                concerns=concerns_for(raw, ctx),
                date_status=date_status(raw, ctx),
                source_method=raw.source_method,
            )
        )

    accepted.sort(key=lambda j: (j.score, j.date_status == DATE_CONFIRMED_RECENT), reverse=True)
    return accepted, rejected, duplicate_count


def infer_work_mode(raw: RawJob) -> str:
    text = lower_text(raw.location, raw.work_mode, raw.description)
    if "remote" in text:
        return "Remote"
    if "hybrid" in text:
        return "Hybrid"
    return "Onsite/unclear"


def print_health(healths: Sequence[Health]) -> None:
    print("\nSource health")
    print("Company     | Method     | Status             | Count | Note")
    print("------------+------------+--------------------+-------+------------------------------")
    for h in healths:
        print(f"{h.company:<11} | {h.method:<10} | {h.status:<18} | {h.count:>5} | {h.note[:30]}")


def print_jobs(title: str, jobs: Sequence[Job]) -> None:
    print(f"\n{title}")
    if not jobs:
        print("None")
        return
    for idx, job in enumerate(jobs, start=1):
        concerns = "; ".join(job.concerns)
        print(f"{idx}. [{job.score}] {job.company} - {job.title}")
        print(f"   {job.location} | {job.work_mode} | {job.posted} | {job.date_status}")
        print(f"   {job.url}")
        print(f"   {job.match_reason}")
        print(f"   Concerns: {concerns}")


def format_ledger_section(jobs: Sequence[Job]) -> str:
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M %Z").strip()
    if not now.endswith(("EST", "EDT")):
        now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        "",
        f"## Run: {now}",
        "",
        "| Job Title | Company | Location | Work Mode | Posted | Score | Job ID | URL | Match Reason | Concerns |",
        "|---|---|---|---|---|---:|---|---|---|---|",
    ]
    for job in jobs:
        posted = job.posted
        if job.date_status != DATE_CONFIRMED_RECENT:
            posted = f"{posted} ({job.date_status})"
        lines.append(
            "| "
            + " | ".join(
                escape_cell(x)
                for x in (
                    job.title,
                    job.company,
                    job.location,
                    job.work_mode,
                    posted,
                    str(job.score),
                    job.job_id,
                    job.url,
                    job.match_reason,
                    "; ".join(job.concerns),
                )
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def escape_cell(text: str) -> str:
    return str(text or "").replace("|", "\\|").replace("\n", " ").strip()


def append_jobs(jobs: Sequence[Job]) -> int:
    with open(LEDGER_PATH, "r", encoding="utf-8") as f:
        ledger = f.read()
    existing = ledger_index(ledger)

    final: List[Job] = []
    seen: set[str] = set()
    for job in jobs:
        raw = RawJob(job.company, job.source_method, job.title, job.url, job.job_id, job.job_id, job.location)
        if is_duplicate(raw, existing, seen):
            continue
        add_seen(raw, seen)
        final.append(job)

    if not final:
        print("\nAppend skipped: no new jobs after final ledger re-read.")
        return 0

    with open(LEDGER_PATH, "a", encoding="utf-8") as f:
        f.write(format_ledger_section(final))
    print(f"\nAppended {len(final)} jobs to {LEDGER_PATH}")
    return len(final)


def run_search(args: argparse.Namespace) -> int:
    prefs, profile, ledger = load_context()
    days = args.days
    if days is None:
        days = int(
            prefs.get("job_search_preferences", {}).get("job_posting_age_days")
            or DEFAULT_DAYS
        )
    ctx = RunContext(limit=args.limit, days=days, verbose=args.verbose)
    existing = ledger_index(ledger)

    print(f"Part 1 search: limit={ctx.limit}, days={ctx.days}, cutoff={ctx.cutoff.isoformat()}")
    print("Official-source adapters only. Dry-run unless --append is set.")

    healths: List[Health] = []
    all_raw: List[RawJob] = []
    for adapter in build_adapters():
        if args.company and adapter.company.lower() not in {c.lower() for c in args.company}:
            continue
        result = adapter.fetch(ctx)
        healths.append(result.health)
        all_raw.extend(result.raw_jobs)
        if args.verbose:
            print(f"{result.health.company}: {result.health.status}, raw={len(result.raw_jobs)}")

    accepted, rejected, duplicate_count = classify_jobs(all_raw, profile, ctx, existing)
    confirmed = [j for j in accepted if j.date_status == DATE_CONFIRMED_RECENT]
    hidden = [j for j in accepted if j.date_status == DATE_HIDDEN]

    print_health(healths)
    print_jobs("New confirmed_recent jobs", confirmed)
    print_jobs("New posted_hidden_top_results jobs", hidden)

    print("\nRejected")
    if rejected:
        for reason, count in rejected.most_common():
            print(f"- {reason}: {count}")
    else:
        print("None")

    print(f"\nRaw jobs: {len(all_raw)} | Accepted: {len(accepted)} | Duplicates skipped: {duplicate_count}")

    if args.append:
        append_jobs(accepted)
    else:
        print("\nDry run only. Use --append to write new jobs after final ledger re-read.")
    return 0


def run_self_tests() -> int:
    failures: List[str] = []

    def check(name: str, condition: bool) -> None:
        if not condition:
            failures.append(name)

    check("parse date iso", parse_date("2026-06-19") == dt.date(2026, 6, 19))
    check("parse date month", parse_date("June 18, 2026") == dt.date(2026, 6, 18))
    check("meta parser", parse_meta_jobs('<a href="/profile/job_details/12345/"><h3>Firmware Engineer</h3></a>') == [("Firmware Engineer", "https://www.metacareers.com/profile/job_details/12345/")])
    check("tesla req id", req_id_from_url("https://www.tesla.com/careers/search/job/foo-bar-263752") == "263752")
    check("official url", is_official_url("Tesla", "https://www.tesla.com/careers/search/job/foo-1"))
    check("term boundary", not term_in_text("ros", "cross-functional debugging"))
    check("term phrase", term_in_text("device driver", "Linux device driver development"))

    ctx = RunContext(limit=5, days=3)
    profile = {"keywords_include": ["firmware", "embedded linux", "kernel", "device driver"]}
    good = RawJob(
        company="Qualcomm",
        source_method="requests",
        title="Embedded Software Engineer - Device Driver Development",
        url="https://careers.qualcomm.com/careers/job/123",
        job_id="123",
        location="San Diego, CA, US",
        posted_date=dt.date.today(),
        description="Embedded Linux kernel device driver firmware C C++",
    )
    bad = dataclasses.replace(good, title="Financial Analyst", description="finance planning")
    no_sponsor = dataclasses.replace(good, description="This role is not eligible for immigration sponsorship.")
    check("good role not weak", not weak_role_match(good, profile))
    check("bad role weak", weak_role_match(bad, profile))
    check("no sponsorship reject", "no_sponsorship" in hard_reject_reasons(no_sponsor, ctx))
    check("grad bypass staff title", not title_exceeds_experience_level("New Grad Staff Engineer"))
    check("staff title filtered", title_exceeds_experience_level("Staff Firmware Engineer"))
    check("experience level reject", "experience_level_high" in hard_reject_reasons(
        dataclasses.replace(good, title="Principal Firmware Engineer"), ctx))
    check("grad bypass not rejected", "experience_level_high" not in hard_reject_reasons(
        dataclasses.replace(good, title="New Grad Software Engineer"), ctx))

    check("date hidden", date_status(dataclasses.replace(good, posted_date=None), ctx) == DATE_HIDDEN)

    if failures:
        print("Self-test failures:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("Self-tests passed.")
    return 0


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Part 1 official-source job search.")
    parser.add_argument("--append", action="store_true", help="Append accepted new jobs to jobsearchdocs/jobs_found.md")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Max raw/top results per company, default 50")
    parser.add_argument("--days", type=int, default=None, help="Freshness window. Defaults to preferences JSON or 3.")
    parser.add_argument("--company", action="append", help="Run only this company. Can be repeated.")
    parser.add_argument("--self-test", action="store_true", help="Run internal tests and exit")
    parser.add_argument("--verbose", action="store_true", help="Print adapter progress")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    if args.limit < 1:
        raise SystemExit("--limit must be positive")
    if args.self_test:
        return run_self_tests()
    return run_search(args)


if __name__ == "__main__":
    raise SystemExit(main())
