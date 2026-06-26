#!/usr/bin/env python3
"""
Part 2 job-search automation.

This script implements the repeatable /jobsearch flow for job_search_2 only:
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
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


ROOT = os.path.dirname(os.path.abspath(__file__))
DOCS_DIR = os.path.join(ROOT, "..", "jobsearchdocs")
PREFERENCES_PATH = os.path.join(DOCS_DIR, "job_search_preferences.json")
PROFILE_PATH = os.path.join(DOCS_DIR, "job_search_profile.json")
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
    "Cisco": [
        "ios",
        "meraki",
        "networking firmware",
        "switch",
        "embedded",
        "datacenter",
        "nexus",
        "wireless",
        "security firmware",
    ],
    "AMD": [
        "uefi",
        "bios",
        "epyc",
        "instinct",
        "interconnect firmware",
        "linux",
        "gpu driver",
        "soc firmware",
        "x86 embedded",
    ],
    "Broadcom": [
        "esx",
        "vmware",
        "kernel",
        "network asic",
        "switch",
        "firmware",
        "server platform",
        "hypervisor",
        "nic",
    ],
    "Intel": [
        "ipu",
        "firmware",
        "fpga",
        "embedded",
        "bios",
        "uefi",
        "programmable",
        "packet processing",
        "platform",
    ],
    "Arm": [
        "bsp",
        "device driver",
        "trustzone",
        "firmware",
        "embedded",
        "soc",
        "kernel",
        "platform software",
    ],
    "Marvell": [
        "ethernet",
        "switch",
        "phy",
        "firmware",
        "embedded",
        "networking",
        "optical",
        "retimer",
        "bgp",
    ],
    "Texas Instruments": [
        "embedded",
        "mcu",
        "dsp",
        "rtos",
        "firmware",
        "linux",
        "processor",
        "automotive",
    ],
    "NXP": [
        "automotive",
        "linux",
        "bsp",
        "device tree",
        "u-boot",
        "yocto",
        "kernel",
        "robotics",
        "mpu",
    ],
    "Garmin": [
        "embedded",
        "rtos",
        "gps",
        "firmware",
        "avionics",
        "marine",
        "fitness",
        "wireless",
    ],
    "Sony": [
        "playstation",
        "embedded",
        "firmware",
        "kernel",
        "camera",
        "imaging",
        "audio",
        "wireless",
        "platform",
    ],
}

US_LOCATION_TEXT = ("united states", "united states of america", "usa", "us,", "us ")

OFFICIAL_DOMAINS = {
    "Cisco": ("careers.cisco.com",),
    "AMD": ("careers.amd.com",),
    "Broadcom": ("broadcom.wd1.myworkdayjobs.com",),
    "Intel": ("intel.wd1.myworkdayjobs.com",),
    "Arm": ("careers.arm.com",),
    "Marvell": ("marvell.wd1.myworkdayjobs.com",),
    "Texas Instruments": ("careers.ti.com", "edbz.fa.us2.oraclecloud.com"),
    "NXP": ("nxp.wd3.myworkdayjobs.com",),
    "Garmin": ("careers.garmin.com",),
    "Sony": ("sonyglobal.wd1.myworkdayjobs.com", "careers.playstation.com"),
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
        self.post_cache: Dict[str, Tuple[Optional[int], str]] = {}
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


def http_post_json(ctx: RunContext, url: str, payload: Dict[str, Any]) -> Tuple[Optional[int], str]:
    cache_key = "POST:" + url + ":" + json.dumps(payload, sort_keys=True)
    if cache_key in ctx.post_cache:
        return ctx.post_cache[cache_key]

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json,text/html,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Content-Type": "application/json",
    }
    data = json.dumps(payload).encode("utf-8")
    result: Tuple[Optional[int], str] = (None, "")

    for attempt in range(MAX_RETRIES):
        if attempt:
            time.sleep(REQUEST_DELAY_SECONDS * (2 ** attempt))
        req = urllib.request.Request(url, data=data, method="POST", headers=headers)
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

    ctx.post_cache[cache_key] = result
    return result


def first_text(*values: Any) -> str:
    for value in values:
        if value:
            return clean_text(str(value))
    return ""


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "job"


def is_us_text(value: Any) -> bool:
    text = clean_text(str(value or "")).lower()
    return any(token in text for token in US_LOCATION_TEXT)


def enrich_from_html_page(ctx: RunContext, raw: RawJob) -> None:
    if not raw.url:
        return
    cache_key = f"html:{raw.url}"
    if cache_key in ctx.detail_cache:
        body = ctx.detail_cache[cache_key]
        code = 200
    else:
        code, body = http_get(ctx, raw.url)
        if code == 200:
            ctx.detail_cache[cache_key] = body
    if code != 200 or not body:
        return

    title = extract_title_from_html(body)
    if title and (not raw.title or raw.title.lower() in {"untitled", "job"}):
        raw.title = title

    posted, posted_raw = extract_json_ld_dates(body)
    if posted:
        raw.posted_date = posted
        raw.posted_raw = posted_raw
    elif not raw.posted_raw:
        rel = re.search(r"Posted\s+(\d+\s+Days?\s+Ago|Today|Yesterday|[A-Za-z]+\.?\s+\d{1,2},?\s+\d{4})", body, flags=re.I)
        if rel:
            raw.posted_raw = clean_text(rel.group(0))
            parsed = parse_date(raw.posted_raw)
            if parsed:
                raw.posted_date = parsed

    loc_match = re.search(r"Location\s*[:#]?\s*([^|<\n]{2,120})", clean_text(body), flags=re.I)
    if loc_match and not raw.location:
        raw.location = clean_text(loc_match.group(1))

    page_text = html_to_text(body)
    if page_text:
        raw.description = " ".join([raw.description, page_text[:12000]]).strip()


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


def discover_workday_us_facet(ctx: RunContext, endpoint: str) -> Tuple[Optional[int], str, List[str]]:
    payload = {"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""}
    code, body = http_post_json(ctx, endpoint, payload)
    data = load_json_body(body)
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


def canonical_from_jibe(job: Dict[str, Any], base: str) -> str:
    data = job.get("data", job) if isinstance(job, dict) else {}
    meta = data.get("meta_data") if isinstance(data.get("meta_data"), dict) else {}
    url = str(meta.get("canonical_url") or data.get("canonical_url") or data.get("url") or "")
    if url:
        return absolute(url, base)
    req_id = str(data.get("req_id") or data.get("id") or "")
    return f"{base}/jobs/{req_id}?lang=en-us" if req_id else ""


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


class WorkdayCXSAdapter(BaseAdapter):
    method = "requests"

    def __init__(self, company: str, endpoint: str, public_base: str) -> None:
        self.company = company
        self.endpoint = endpoint
        self.public_base = public_base.rstrip("/")
        self.cxs_base = endpoint.replace("/jobs", "")

    def fetch(self, ctx: RunContext) -> AdapterResult:
        jobs: List[RawJob] = []
        seen: set[str] = set()
        last_code: Optional[int] = None

        _, facet_param, us_location_ids = discover_workday_us_facet(ctx, self.endpoint)
        applied_facets = {facet_param: us_location_ids} if facet_param and us_location_ids else {}

        for offset in range(0, ctx.limit, 20):
            payload = {
                "appliedFacets": applied_facets,
                "limit": min(20, ctx.limit - offset),
                "offset": offset,
                "searchText": "",
            }
            code, body = http_post_json(ctx, self.endpoint, payload)
            last_code = code
            if code != 200:
                break

            data = load_json_body(body)
            batch = data.get("jobPostings", []) if isinstance(data, dict) else []
            if not isinstance(batch, list) or not batch:
                break

            for posting in batch:
                if not isinstance(posting, dict):
                    continue
                external = str(posting.get("externalPath") or "")
                key = external or str(posting.get("title") or "")
                if not key or key in seen:
                    continue
                seen.add(key)

                url = self.public_base + external if external.startswith("/") else absolute(external, self.public_base)
                title = first_text(posting.get("title"))
                location = first_text(posting.get("locationsText"), posting.get("location"))
                posted_raw = first_text(posting.get("postedOn"), posting.get("postedDate"))
                posted = parse_date(posted_raw)
                req_id = ""
                req_match = re.search(r"_([A-Za-z0-9-]+)$", external)
                if req_match:
                    req_id = req_match.group(1)

                raw = RawJob(
                    company=self.company,
                    source_method=self.method,
                    title=title,
                    url=url,
                    job_id=req_id or key,
                    requisition_id=req_id,
                    location=location,
                    posted_raw=posted_raw,
                    posted_date=posted,
                    description=title,
                    raw=posting,
                )
                self._enrich_detail(ctx, raw)
                jobs.append(raw)
                if len(jobs) >= ctx.limit:
                    break

            total = data.get("total") if isinstance(data, dict) else None
            if isinstance(total, int) and offset + 20 >= total:
                break
            if len(jobs) >= ctx.limit:
                break
            time.sleep(REQUEST_DELAY_SECONDS)

        return AdapterResult(Health(self.company, self.method, status_from(last_code, len(jobs)), len(jobs)), jobs)

    def _enrich_detail(self, ctx: RunContext, raw: RawJob) -> None:
        external = str(raw.raw.get("externalPath") or "")
        if external:
            detail_url = self.cxs_base + external
            cache_key = f"wd:{detail_url}"
            if cache_key in ctx.detail_cache:
                body = ctx.detail_cache[cache_key]
                code = 200
            else:
                code, body = http_get(ctx, detail_url)
                if code == 200:
                    ctx.detail_cache[cache_key] = body
            if code == 200 and body:
                data = load_json_body(body)
                info = {}
                if isinstance(data, dict):
                    info = data.get("jobPostingInfo") if isinstance(data.get("jobPostingInfo"), dict) else data
                if isinstance(info, dict):
                    raw.title = first_text(info.get("title"), raw.title)
                    raw.location = first_text(info.get("location"), info.get("locationsText"), raw.location)
                    raw.posted_raw = first_text(info.get("postedOn"), raw.posted_raw)
                    parsed = parse_date(raw.posted_raw)
                    if parsed:
                        raw.posted_date = parsed
                    desc = first_text(info.get("jobDescription"))
                    if desc:
                        raw.description = " ".join([raw.description, html_to_text(desc)]).strip()
        if len(raw.description) < 200:
            enrich_from_html_page(ctx, raw)


class JibeAdapter(BaseAdapter):
    method = "requests"

    def __init__(self, company: str, base: str, api_url: str) -> None:
        self.company = company
        self.base = base.rstrip("/")
        self.api_url = api_url

    def fetch(self, ctx: RunContext) -> AdapterResult:
        jobs: List[RawJob] = []
        seen: set[str] = set()
        last_code: Optional[int] = None

        for page in range(1, 8):
            params = {
                "page": str(page),
                "sortBy": "posted_date",
                "descending": "true",
                "country": "United States",
            }
            url = self.api_url + "?" + urllib.parse.urlencode(params)
            code, body = http_get(ctx, url)
            last_code = code
            if code != 200:
                break

            data = load_json_body(body)
            batch = data.get("jobs", []) if isinstance(data, dict) else []
            if not isinstance(batch, list) or not batch:
                break

            new_on_page = 0
            for item in batch:
                if not isinstance(item, dict):
                    continue
                data_obj = item.get("data", item) if isinstance(item.get("data"), dict) else item
                req_id = str(data_obj.get("req_id") or data_obj.get("id") or "")
                key = req_id or canonical_from_jibe(item, self.base)
                if not key or key in seen:
                    continue
                seen.add(key)
                new_on_page += 1

                job_url = canonical_from_jibe(item, self.base)
                location = normalize_location(data_obj.get("location") or data_obj.get("city") or data_obj.get("locations"))
                posted_raw = first_text(data_obj.get("posted_date"), data_obj.get("postedDate"))
                posted = parse_date(posted_raw)
                desc = html_to_text(str(data_obj.get("description") or data_obj.get("summary") or ""))

                raw = RawJob(
                    company=self.company,
                    source_method=self.method,
                    title=first_text(data_obj.get("title")),
                    url=job_url,
                    job_id=req_id,
                    requisition_id=req_id,
                    location=location or "United States",
                    posted_raw=posted_raw,
                    posted_date=posted,
                    description=" ".join([str(data_obj.get("title") or ""), desc]).strip(),
                    raw=data_obj,
                )
                self._enrich_detail(ctx, raw)
                jobs.append(raw)
                if len(jobs) >= ctx.limit:
                    break

            if len(jobs) >= ctx.limit or new_on_page == 0:
                break
            time.sleep(REQUEST_DELAY_SECONDS)

        return AdapterResult(Health(self.company, self.method, status_from(last_code, len(jobs)), len(jobs)), jobs)

    def _enrich_detail(self, ctx: RunContext, raw: RawJob) -> None:
        if raw.requisition_id and len(raw.description) < 200:
            detail_url = f"{self.api_url}/{raw.requisition_id}"
            code, body = http_get(ctx, detail_url)
            if code == 200:
                data = load_json_body(body)
                obj = data.get("data", data) if isinstance(data, dict) else {}
                if isinstance(obj, dict):
                    desc = html_to_text(str(obj.get("description") or obj.get("summary") or ""))
                    if desc:
                        raw.description = " ".join([raw.description, desc]).strip()
                    raw.location = normalize_location(obj.get("location") or obj.get("locations")) or raw.location
                    posted = parse_date(obj.get("posted_date") or obj.get("postedDate"))
                    if posted:
                        raw.posted_date = posted
        if len(raw.description) < 200:
            enrich_from_html_page(ctx, raw)


class CiscoAdapter(BaseAdapter):
    company = "Cisco"
    method = "requests"

    def fetch(self, ctx: RunContext) -> AdapterResult:
        parsed: List[Tuple[str, str]] = []
        seen: set[str] = set()
        last_code: Optional[int] = None

        for start in range(0, ctx.limit, 10):
            params = {"from": str(start), "s": "1", "country": "United States of America"}
            url = "https://careers.cisco.com/global/en/search-results?" + urllib.parse.urlencode(params)
            code, body = http_get(ctx, url)
            last_code = code
            if code != 200:
                break
            for title, link in parse_cisco_jobs(body):
                if link in seen:
                    continue
                seen.add(link)
                parsed.append((title, link))
            if len(parsed) >= ctx.limit:
                break
            time.sleep(REQUEST_DELAY_SECONDS)

        jobs: List[RawJob] = []
        for title, link in parsed[: ctx.limit]:
            seq_match = re.search(r"/job/([^/]+)/", link)
            job_id = seq_match.group(1) if seq_match else req_id_from_url(link)
            raw = RawJob(
                company=self.company,
                source_method=self.method,
                title=title,
                url=link,
                job_id=job_id,
                requisition_id=job_id,
                location="United States",
                posted_raw="Posted hidden",
                description=title,
            )
            enrich_from_html_page(ctx, raw)
            jobs.append(raw)

        return AdapterResult(Health(self.company, self.method, status_from(last_code, len(jobs)), len(jobs)), jobs)


class ArmAdapter(BaseAdapter):
    company = "Arm"
    method = "requests"

    def fetch(self, ctx: RunContext) -> AdapterResult:
        url = "https://careers.arm.com/search-jobs/?sort=posted_date"
        code, body = http_get(ctx, url)
        cards = parse_arm_cards(body)

        us_cards = [
            (title, link, location)
            for title, link, location in cards
            if is_us_text(location) or location in {"Austin, Texas", "San Jose, California"}
        ]
        if not us_cards:
            us_cards = cards

        seen: set[str] = set()
        jobs: List[RawJob] = []
        for title, link, location in us_cards:
            if link in seen:
                continue
            seen.add(link)
            req_id = req_id_from_url(link)
            raw = RawJob(
                company=self.company,
                source_method=self.method,
                title=title,
                url=link,
                job_id=req_id,
                requisition_id=req_id,
                location=location,
                posted_raw="Posted hidden",
                description=title,
            )
            enrich_from_html_page(ctx, raw)
            if not location_ok(raw):
                continue
            jobs.append(raw)
            if len(jobs) >= ctx.limit:
                break

        return AdapterResult(Health(self.company, self.method, status_from(code, len(jobs)), len(jobs)), jobs)


class OracleCEAdapter(BaseAdapter):
    company = "Texas Instruments"
    method = "requests"

    def fetch(self, ctx: RunContext) -> AdapterResult:
        finder = (
            "findReqs;siteNumber=CX,"
            "facetsList=LOCATIONS%3BWORK_LOCATIONS%3BTITLES%3BCATEGORIES%3BORGANIZATIONS%3BPOSTING_DATES%3BFLEX_FIELDS,"
            f"limit={ctx.limit},sortBy=POSTING_DATES_DESC"
        )
        url = (
            "https://edbz.fa.us2.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions?"
            "onlyData=true&expand=requisitionList.secondaryLocations,flexFieldsFacet.values,requisitionList.requisitionFlexFields&finder="
            + finder
        )
        code, body = http_get(ctx, url, accept="application/json,*/*")
        data = load_json_body(body)
        items = data.get("items", []) if isinstance(data, dict) else []
        batch: List[Dict[str, Any]] = []
        if items and isinstance(items[0], dict):
            req_list = items[0].get("requisitionList", [])
            batch = req_list if isinstance(req_list, list) else []

        us_batch = [
            job for job in batch
            if isinstance(job, dict) and is_us_text(job.get("PrimaryLocationCountry") or job.get("PrimaryLocation") or job.get("Locations"))
        ]
        selected = us_batch or [j for j in batch if isinstance(j, dict)]

        seen: set[str] = set()
        jobs: List[RawJob] = []
        for job in selected:
            req_id = str(job.get("Id") or "")
            if not req_id or req_id in seen:
                continue
            seen.add(req_id)
            job_url = f"https://careers.ti.com/job/{req_id}"
            location = first_text(job.get("PrimaryLocation"), job.get("Locations"))
            posted_raw = first_text(job.get("PostedDate"), job.get("PostingDate"))
            posted = parse_date(posted_raw)
            raw = RawJob(
                company=self.company,
                source_method=self.method,
                title=first_text(job.get("Title")),
                url=job_url,
                job_id=req_id,
                requisition_id=req_id,
                location=location,
                posted_raw=posted_raw,
                posted_date=posted,
                description=first_text(job.get("Title"), job.get("ShortDescriptionStr")),
                raw=job,
            )
            enrich_from_html_page(ctx, raw)
            jobs.append(raw)
            if len(jobs) >= ctx.limit:
                break

        return AdapterResult(Health(self.company, self.method, status_from(code, len(jobs)), len(jobs)), jobs)


class SonyAdapter(BaseAdapter):
    company = "Sony"
    method = "requests"

    def fetch(self, ctx: RunContext) -> AdapterResult:
        jobs: List[RawJob] = []
        seen: set[str] = set()

        wd_endpoint = "https://sonyglobal.wd1.myworkdayjobs.com/wday/cxs/sonyglobal/SonyGlobalCareers/jobs"
        wd_public = "https://sonyglobal.wd1.myworkdayjobs.com/SonyGlobalCareers"
        wd_adapter = WorkdayCXSAdapter("Sony", wd_endpoint, wd_public)
        wd_result = wd_adapter.fetch(ctx)
        for raw in wd_result.raw_jobs:
            if raw.url not in seen:
                seen.add(raw.url)
                raw.company = self.company
                jobs.append(raw)

        ps_url = "https://careers.playstation.com/jobs?sortBy=posted_date"
        code, body = http_get(ctx, ps_url)
        if code == 200:
            decoded = body.replace("\\u002F", "/").replace("\\u002f", "/").replace("\\/", "/")
            links = re.findall(r'https://careers\.playstation\.com/[^"\'\\< ]+', decoded)
            links += [
                absolute(link, "https://careers.playstation.com")
                for link in re.findall(r'href=["\']([^"\']*/jobs/[^"\']+)["\']', decoded, flags=re.I)
            ]
            titles = re.findall(r'"title"\s*:\s*"([^"]{3,160})"', decoded)
            for idx, link in enumerate(links):
                if "/jobs/" not in link or link in seen:
                    continue
                seen.add(link)
                title = clean_text(titles[idx]) if idx < len(titles) else title_from_url(link)
                raw = RawJob(
                    company=self.company,
                    source_method=self.method,
                    title=title,
                    url=link,
                    job_id=req_id_from_url(link),
                    requisition_id=req_id_from_url(link),
                    location="United States",
                    posted_raw="Posted hidden",
                    description=title,
                )
                enrich_from_html_page(ctx, raw)
                jobs.append(raw)
                if len(jobs) >= ctx.limit:
                    break

        jobs = jobs[: ctx.limit]
        status = "ok" if jobs else "parser_failed"
        return AdapterResult(Health(self.company, self.method, status, len(jobs)), jobs)


def build_adapters() -> List[BaseAdapter]:
    return [
        CiscoAdapter(),
        JibeAdapter("AMD", "https://careers.amd.com", "https://careers.amd.com/api/jobs"),
        WorkdayCXSAdapter(
            "Broadcom",
            "https://broadcom.wd1.myworkdayjobs.com/wday/cxs/broadcom/External_Career/jobs",
            "https://broadcom.wd1.myworkdayjobs.com/External_Career",
        ),
        WorkdayCXSAdapter(
            "Intel",
            "https://intel.wd1.myworkdayjobs.com/wday/cxs/intel/External/jobs",
            "https://intel.wd1.myworkdayjobs.com/External",
        ),
        ArmAdapter(),
        WorkdayCXSAdapter(
            "Marvell",
            "https://marvell.wd1.myworkdayjobs.com/wday/cxs/marvell/MarvellCareers/jobs",
            "https://marvell.wd1.myworkdayjobs.com/MarvellCareers",
        ),
        OracleCEAdapter(),
        WorkdayCXSAdapter(
            "NXP",
            "https://nxp.wd3.myworkdayjobs.com/wday/cxs/nxp/careers/jobs",
            "https://nxp.wd3.myworkdayjobs.com/careers",
        ),
        JibeAdapter("Garmin", "https://careers.garmin.com", "https://careers.garmin.com/api/jobs"),
        SonyAdapter(),
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
        return raw.company in {"Arm", "Sony", "Garmin", "Cisco", "AMD"}
    if re.search(r"\bus,\s*[a-z]", text):
        return True
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
    if raw.company in {"AMD", "Broadcom", "Intel", "Cisco", "NXP", "Marvell"}:
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

    print(f"Part 2 search: limit={ctx.limit}, days={ctx.days}, cutoff={ctx.cutoff.isoformat()}")
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
    check("parse date days ago", parse_date("Posted 5 Days Ago") == dt.date.today() - dt.timedelta(days=5))

    cisco_body = (
        '"country":"United States of America","title":"Firmware Engineer",'
        '"jobSeqNo":"123456789"'
    )
    cisco_jobs = parse_cisco_jobs(cisco_body)
    check("cisco parser", len(cisco_jobs) == 1 and "123456789" in cisco_jobs[0][1])

    jibe_job = {"data": {"req_id": "86759", "title": "UEFI Engineer", "meta_data": {"canonical_url": "https://careers.amd.com/jobs/86759"}}}
    check("jibe canonical", canonical_from_jibe(jibe_job, "https://careers.amd.com") == "https://careers.amd.com/jobs/86759")

    facet_fixture = {
        "facets": [
            {
                "facetParameter": "Country",
                "values": [{"descriptor": "United States of America", "id": "abc123"}],
            }
        ]
    }
    ids = workday_us_ids_for_facet(facet_fixture["facets"][0])
    check("workday us ids", ids == ["abc123"])

    arm_html = (
        '<a class="job-card__title" href="/job/firmware-engineer/12345">Firmware Engineer</a>'
        '<span class="location">Austin, Texas</span>'
    )
    arm_cards = parse_arm_cards(arm_html)
    check("arm parser", len(arm_cards) == 1 and arm_cards[0][0] == "Firmware Engineer")

    check("ti url", req_id_from_url("https://careers.ti.com/job/12345") == "12345")
    check("official url amd", is_official_url("AMD", "https://careers.amd.com/jobs/86759"))
    check("term boundary", not term_in_text("ros", "cross-functional debugging"))
    check("term phrase", term_in_text("device driver", "Linux device driver development"))

    ctx = RunContext(limit=5, days=3)
    profile = {"keywords_include": ["firmware", "embedded linux", "kernel", "device driver"]}
    good = RawJob(
        company="AMD",
        source_method="requests",
        title="UEFI/BIOS Firmware Engineer",
        url="https://careers.amd.com/careers-home/jobs/86859",
        job_id="86859",
        location="Austin, TX, US",
        posted_date=dt.date.today(),
        description="Embedded Linux kernel device driver firmware UEFI BIOS C C++",
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

    existing = {"https://careers.amd.com/jobs/86859"}
    dup = dataclasses.replace(good, url="https://careers.amd.com/jobs/86859")
    check("dedupe url", is_duplicate(dup, existing, set()))

    if failures:
        print("Self-test failures:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("Self-tests passed.")
    return 0


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Part 2 official-source job search.")
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
