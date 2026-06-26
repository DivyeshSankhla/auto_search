#!/usr/bin/env python3
"""
General job-site search automation.

Standalone script mirroring the company-parts pipeline:
fetch -> normalize -> filter -> score >= 70 -> dedupe vs jobs_found.md -> dry run / --append.

Site adapters (not company adapters). Company field = employer from listing or site name.
"""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import dataclasses
import datetime as dt
import email.utils
import html
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

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
DEFAULT_LOCATION = "United States"
TIMEOUT = 20
REQUEST_DELAY_SECONDS = 0.15
MAX_RETRIES = 3
MIN_JD_CHARS = 200

DATE_CONFIRMED_RECENT = "confirmed_recent"
DATE_OLD = "old"
DATE_HIDDEN = "posted_hidden_top_results"

PROFILE_QUERIES = [
    "embedded software engineer",
    "firmware engineer",
    "systems software engineer",
    "linux kernel engineer",
]

RANKED_TERMS = [
    "firmware", "embedded linux", "linux kernel", "kernel", "device driver",
    "device drivers", "systems software", "system software", "platform software",
    "embedded software", "operating systems", "networking", "connectivity",
    "performance", "robotics", "rtos", "bootloader", "uefi", "bios", "openbmc",
    "bmc", "tcp/ip", "c++", "embedded c",
]

US_LOCATION_TEXT = ("united states", "united states of america", "usa", "us,", "us ")

PLATFORM_DOMAINS: Dict[str, Tuple[str, ...]] = {
    "LinkedIn": ("linkedin.com",),
    "Indeed": ("indeed.com",),
    "Dice": ("dice.com",),
    "Built In": ("builtin.com",),
    "SimplyHired": ("simplyhired.com",),
    "RemoteOK": ("remoteok.com",),
    "We Work Remotely": ("weworkremotely.com",),
    "Remotive": ("remotive.com",),
    "Hacker News Who's Hiring": ("news.ycombinator.com", "ycombinator.com"),
    "Glassdoor": ("glassdoor.com",),
    "ZipRecruiter": ("ziprecruiter.com",),
    "Wellfound": ("wellfound.com", "angel.co"),
    "Monster": ("monster.com",),
    "Otta": ("otta.com", "app.otta.com", "welcometothejungle.com"),
}

EXTERNAL_URL_OK_SITES = {
    "RemoteOK", "We Work Remotely", "Remotive", "Hacker News Who's Hiring",
}

SITE_SLUGS: Dict[str, str] = {
    "linkedin": "LinkedIn",
    "indeed": "Indeed",
    "dice": "Dice",
    "builtin": "Built In",
    "simplyhired": "SimplyHired",
    "remoteok": "RemoteOK",
    "weworkremotely": "We Work Remotely",
    "wwr": "We Work Remotely",
    "remotive": "Remotive",
    "hn": "Hacker News Who's Hiring",
    "hn_whos_hiring": "Hacker News Who's Hiring",
    "glassdoor": "Glassdoor",
    "ziprecruiter": "ZipRecruiter",
    "wellfound": "Wellfound",
    "monster": "Monster",
    "otta": "Otta",
}

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
CapturedResponse = Tuple[int, str, str]
MONSTER_APP_CHUNK = "/assets/jobsui/_next/static/chunks/pages/_app-2d5c3c0d21a49478.js"
OTTA_FALLBACK_SEARCH = "https://www.welcometothejungle.com/en/jobs"


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
        self.page_cache: Dict[str, Tuple[Optional[int], str, str]] = {}


# --- utility helpers (part7 + unified tester) ---

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


def is_platform_url(url: str, site: str) -> bool:
    try:
        host = urllib.parse.urlparse(url).netloc.lower()
    except Exception:
        return False
    if not host:
        return False
    domains = PLATFORM_DOMAINS.get(site, ())
    return any(host == d or host.endswith("." + d) for d in domains)


def pick_query(explicit: Optional[str]) -> str:
    if explicit:
        return explicit.strip()
    return PROFILE_QUERIES[dt.date.today().toordinal() % len(PROFILE_QUERIES)]


def pick_queries(explicit: Optional[str]) -> List[str]:
    if explicit:
        return [explicit.strip()]
    return list(PROFILE_QUERIES)


def parse_sites_flag(sites_arg: Optional[str]) -> Optional[set[str]]:
    if not sites_arg or sites_arg.strip().lower() == "all":
        return None
    names: set[str] = set()
    for slug in sites_arg.split(","):
        slug = slug.strip().lower()
        if not slug:
            continue
        if slug in SITE_SLUGS:
            names.add(SITE_SLUGS[slug])
        else:
            names.add(slug)
    return names


def has_curl_cffi() -> bool:
    try:
        import curl_cffi  # noqa: F401
        return True
    except ImportError:
        return False


def has_playwright() -> bool:
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
        return True
    except ImportError:
        return False


def query_match(text: str, query: str) -> bool:
    hay = clean_text(text).lower()
    if not hay:
        return False
    tokens = [t for t in re.split(r"\s+", query.lower()) if len(t) > 2]
    return all(t in hay for t in tokens) if tokens else True


def query_match_loose(text: str, query: str) -> bool:
    hay = clean_text(text).lower()
    if not hay:
        return False
    if query_match(text, query):
        return True
    tokens = [t for t in re.split(r"\s+", query.lower()) if len(t) > 2]
    matched = sum(1 for token in tokens if token in hay)
    if matched >= min(2, len(tokens)):
        return True
    domain_terms = (
        "firmware", "embedded", "linux kernel", "kernel driver", "device driver",
        "systems software", "system software", "platform software", "rtos",
        "bootloader", "uefi", "bios",
    )
    role_terms = ("engineer", "developer", "software")
    return any(term in hay for term in domain_terms) and any(term in hay for term in role_terms)


def unique_rows(items: Iterable[JobRow], limit: int, key: str = "url") -> List[JobRow]:
    seen: set[str] = set()
    out: List[JobRow] = []
    for item in items:
        value = str(item.get(key) or "")
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(item)
        if len(out) >= limit:
            break
    return out


def round_robin_raw_batches(batches: Sequence[Sequence[RawJob]], limit: int) -> List[RawJob]:
    seen: set[str] = set()
    output: List[RawJob] = []
    max_length = max((len(batch) for batch in batches), default=0)
    for index in range(max_length):
        for batch in batches:
            if index >= len(batch):
                continue
            raw = batch[index]
            key = raw.url or raw.job_id
            if not key or key in seen:
                continue
            seen.add(key)
            output.append(raw)
            if len(output) >= limit:
                return output
    return output


def row_to_raw(site: str, method: str, row: JobRow, location: str = "") -> RawJob:
    company = clean_text(str(row.get("company") or row.get("employer") or site))
    title = clean_text(str(row.get("title") or ""))
    url = str(row.get("url") or "")
    job_id = str(row.get("job_id") or "")
    loc = clean_text(str(row.get("location") or location))
    desc = clean_text(str(row.get("description") or ""))
    posted_raw = clean_text(str(row.get("posted_raw") or row.get("posted") or ""))
    posted_date = parse_date(posted_raw) if posted_raw else None
    if not posted_date and row.get("posted_date"):
        posted_date = parse_date(row.get("posted_date"))
    return RawJob(
        company=company,
        source_method=method,
        title=title,
        url=url,
        job_id=job_id,
        requisition_id=job_id,
        location=loc,
        posted_raw=posted_raw,
        posted_date=posted_date,
        description=desc,
        raw={"source_site": site, **{k: v for k, v in row.items() if k not in {"title", "url"}}},
    )


def adapter_health(site: str, method: str, code: Optional[int], jobs: List[RawJob], note: str = "") -> Health:
    if jobs:
        missing_titles = sum(not job.title for job in jobs)
        missing_ids = sum(not job.job_id for job in jobs)
        quality = []
        if missing_titles:
            quality.append(f"{missing_titles} missing titles")
        if missing_ids and site in {"LinkedIn", "Indeed", "Dice"}:
            quality.append(f"{missing_ids} missing IDs")
        if quality:
            note = "; ".join(filter(None, (note, ", ".join(quality))))
    return Health(site, method, status_from(code, len(jobs)), len(jobs), note=note)


def http_get(
    ctx: RunContext,
    url: str,
    accept: str = "application/json,text/html,*/*",
    headers: Optional[Dict[str, str]] = None,
) -> Tuple[Optional[int], str]:
    if url in ctx.search_cache:
        return ctx.search_cache[url]
    req_headers = {
        "User-Agent": USER_AGENT,
        "Accept": accept,
        "Accept-Language": "en-US,en;q=0.9",
    }
    if headers:
        req_headers.update(headers)
    result: Tuple[Optional[int], str] = (None, "")
    for attempt in range(MAX_RETRIES):
        if attempt:
            time.sleep(REQUEST_DELAY_SECONDS * (2 ** attempt))
        req = urllib.request.Request(url, headers=req_headers)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                result = (resp.status, resp.read().decode("utf-8", errors="replace"))
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


def fetch_page(ctx: RunContext, url: str, prefer_curl: bool = False) -> Tuple[Optional[int], str, str]:
    cache_key = f"page:{prefer_curl}:{url}"
    if cache_key in ctx.page_cache:
        return ctx.page_cache[cache_key]
    if prefer_curl:
        code, body, method = curl_cffi_get(url)
        if method == "missing_curl_cffi":
            code, body = http_get(ctx, url)
            result = (code, body, "requests")
        else:
            result = (code, body, method)
    else:
        code, body = http_get(ctx, url)
        if code in {403, None} or (code == 200 and len(body) < 500):
            curl_code, curl_body, curl_method = curl_cffi_get(url)
            if curl_method != "missing_curl_cffi" and curl_code == 200 and len(curl_body) > len(body):
                result = (curl_code, curl_body, curl_method)
            else:
                result = (code, body, "requests")
        else:
            result = (code, body, "requests")
    ctx.page_cache[cache_key] = result
    return result


def parse_indeed_cards(body: str) -> List[JobRow]:
    jobs: List[JobRow] = []
    starts = list(re.finditer(r'data-jk="([a-f0-9]{16})"', body, flags=re.I))
    for idx, match in enumerate(starts):
        jk = match.group(1)
        end = starts[idx + 1].start() if idx + 1 < len(starts) else min(len(body), match.start() + 12000)
        card = body[match.start():end]
        title_match = re.search(r'<span[^>]*title="([^"]{3,160})"', card, flags=re.I)
        if not title_match:
            title_match = re.search(
                r'class="[^"]*jobTitle[^"]*"[\s\S]{0,600}?<span[^>]*>([^<]{3,160})</span>',
                card, flags=re.I,
            )
        title = clean_text(title_match.group(1)) if title_match else ""
        company_match = re.search(r'(?:data-testid="company-name"|class="[^"]*companyName[^"]*")[^>]*>([^<]{2,120})<', card, flags=re.I)
        location_match = re.search(r'(?:data-testid="text-location"|class="[^"]*companyLocation[^"]*")[^>]*>([^<]{2,120})<', card, flags=re.I)
        jobs.append({
            "title": title,
            "url": f"https://www.indeed.com/viewjob?jk={jk}",
            "job_id": jk,
            "company": clean_text(company_match.group(1)) if company_match else "",
            "location": clean_text(location_match.group(1)) if location_match else "",
        })
    return jobs


def parse_linkedin_cards(body: str) -> List[JobRow]:
    jobs: List[JobRow] = []
    starts = list(re.finditer(r'data-entity-urn="urn:li:jobPosting:(\d+)"', body))
    for idx, match in enumerate(starts):
        job_id = match.group(1)
        end = starts[idx + 1].start() if idx + 1 < len(starts) else min(len(body), match.start() + 15000)
        card = body[match.start():end]
        url_match = re.search(r'href="(https://www\.linkedin\.com/jobs/view/[^"?&]+)', card)
        title_match = re.search(r'base-search-card__title[^>]*>([\s\S]{0,300}?)</h3>', card, flags=re.I)
        company_match = re.search(r'base-search-card__subtitle[^>]*>[\s\S]{0,400}?<a[^>]*>([\s\S]{0,200}?)</a>', card, flags=re.I)
        location_match = re.search(r'job-search-card__location[^>]*>([\s\S]{0,200}?)</span>', card, flags=re.I)
        date_match = re.search(r'<time[^>]*datetime="([^"]+)"', card, flags=re.I)
        url = html.unescape(url_match.group(1)) if url_match else f"https://www.linkedin.com/jobs/view/{job_id}"
        jobs.append({
            "title": clean_text(title_match.group(1)) if title_match else "",
            "url": url,
            "job_id": job_id,
            "company": clean_text(company_match.group(1)) if company_match else "",
            "location": clean_text(location_match.group(1)) if location_match else "",
            "posted_date": date_match.group(1) if date_match else "",
        })
    return jobs


def is_us_text(value: Any) -> bool:
    text = clean_text(str(value or "")).lower()
    if not text:
        return False
    if any(token in text for token in US_LOCATION_TEXT) or text in {"us", "usa", "united states"}:
        return True
    if "north america" in text or "americas" in text:
        return True
    if re.search(r"(?<![a-z])u\.?s\.?a\.?(?![a-z])", text) or re.search(r"(?<![a-z])us(?![a-z])", text):
        return True
    if any(re.search(r"(?<![a-z])" + re.escape(state) + r"(?![a-z])", text) for state in US_STATE_TEXT):
        return True
    return any(re.search(r"(^|[\s,(])" + abbr + r"($|[\s,)])", text) for abbr in US_STATE_ABBR)


def parse_date(value: Any) -> Optional[dt.date]:
    if value is None:
        return None
    if isinstance(value, dt.date):
        return value
    if isinstance(value, (int, float)):
        try:
            ts = float(value)
            if ts > 1_000_000_000_000:
                ts = ts / 1000
            parsed = dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).date()
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
        return parse_date(int(text[:10]))
    for fmt in (
        "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S", "%b %d, %Y", "%B %d, %Y", "%b. %d, %Y", "%B %d %Y",
    ):
        try:
            return dt.datetime.strptime(text.replace("Z", "+0000"), fmt).date()
        except Exception:
            pass
    try:
        parsed_email_date = email.utils.parsedate_to_datetime(text)
        if parsed_email_date:
            return parsed_email_date.date()
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


def extract_jobposting_json_ld(body: str) -> Dict[str, Any]:
    for match in re.finditer(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', body, flags=re.I | re.S):
        raw = html.unescape(match.group(1)).strip()
        try:
            data = json.loads(raw)
        except Exception:
            continue
        nodes = data if isinstance(data, list) else [data]
        for node in nodes:
            if isinstance(node, dict) and node.get("@type") == "JobPosting":
                return node
    return {}


def extract_title_from_html(body: str) -> str:
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", body, flags=re.I | re.S)
    if h1:
        title = clean_text(h1.group(1))
        if title:
            return title
    title = re.search(r"<title[^>]*>(.*?)</title>", body, flags=re.I | re.S)
    return clean_text(title.group(1)) if title else ""


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
    return ""


def enrich_from_html_page(ctx: RunContext, raw: RawJob, prefer_curl: bool = False) -> None:
    if not raw.url:
        return
    cache_key = f"html:{raw.url}"
    if cache_key in ctx.detail_cache:
        body = ctx.detail_cache[cache_key]
        code = 200
    else:
        code, body, _ = fetch_page(ctx, raw.url, prefer_curl=prefer_curl)
        if code == 200:
            ctx.detail_cache[cache_key] = body
    if code != 200 or not body:
        return
    title = extract_title_from_html(body)
    if title and "can't find this page" not in title.lower() and "page not found" not in title.lower():
        raw.title = title
    jobposting = extract_jobposting_json_ld(body)
    posted_raw = str(jobposting.get("datePosted") or "")
    posted = parse_date(posted_raw) if posted_raw else None
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
    hiring = jobposting.get("hiringOrganization")
    if isinstance(hiring, dict) and hiring.get("name"):
        raw.company = clean_text(str(hiring["name"]))
    if raw.company in PLATFORM_DOMAINS or raw.company == str(raw.raw.get("source_site") or ""):
        company_match = re.search(r'"companyName"\s*:\s*"([^"]{2,160})"', body)
        if company_match:
            raw.company = clean_text(company_match.group(1))
    job_location = jobposting.get("jobLocation")
    if job_location:
        locations = job_location if isinstance(job_location, list) else [job_location]
        location_parts: List[str] = []
        for location in locations:
            if not isinstance(location, dict):
                continue
            address = location.get("address")
            if isinstance(address, dict):
                location_parts.append(", ".join(
                    clean_text(str(address.get(key) or ""))
                    for key in ("addressLocality", "addressRegion", "addressCountry")
                    if address.get(key)
                ))
        if any(location_parts):
            raw.location = "; ".join(part for part in location_parts if part)
    elif str(jobposting.get("jobLocationType") or "").upper() == "TELECOMMUTE":
        raw.location = raw.location or "Remote"
    description = str(jobposting.get("description") or "")
    if description:
        raw.description = clean_text(description)
    else:
        raw.description = extract_jd_from_html(body)


def playwright_search_jobs(
    url: str,
    url_patterns: Iterable[str],
    *,
    wait_selector: Optional[str] = None,
    scroll: bool = True,
    timeout_ms: int = 90000,
) -> Tuple[str, List[CapturedResponse], str, Optional[int]]:
    patterns = [p.lower() for p in url_patterns]
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
                if patterns and not any(p in response_url for p in patterns):
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
            if any("wellfound" in p for p in patterns):
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
        title = str(obj.get("title") or obj.get("jobTitle") or obj.get("position") or obj.get("name") or obj.get("role") or "")
        url = str(obj.get("url") or obj.get("jobUrl") or obj.get("job_url") or obj.get("absolute_url") or "")
        job_id = str(obj.get("jobId") or obj.get("job_id") or obj.get("slug") or obj.get("id") or "")
        company = str(obj.get("company") or obj.get("company_name") or obj.get("employer") or "")
        if title and url:
            jobs.append({"title": clean_text(title), "url": absolute(url, base_url) if base_url else url, "company": company})
        elif title and job_id and "monster" in base_url:
            jobs.append({"title": clean_text(title), "url": f"https://www.monster.com/job-openings/{job_id}", "job_id": job_id, "company": company})
        elif title and job_id and "otta.com" in base_url:
            jobs.append({"title": clean_text(title), "url": f"https://app.otta.com/jobs/{job_id}", "job_id": job_id, "company": company})
        elif title and job_id and "wellfound" in base_url:
            jobs.append({"title": clean_text(title), "url": absolute(f"/jobs/listing/{job_id}", base_url), "job_id": job_id, "company": company})
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
        data = load_json_body(body)
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
    for url in re.findall(r'href="(https://www\.welcometothejungle\.com/en/companies/[^"]+/jobs/[^"]+)"', html_body):
        slug = url.rstrip("/").split("/")[-1]
        jobs.append({"title": clean_text(slug.replace("-", " ")), "url": url})
    for path in re.findall(r'(/en/companies/[^"]+/jobs/[a-z0-9-]+)', html_body):
        url = absolute(path, "https://www.welcometothejungle.com")
        slug = url.rstrip("/").split("/")[-1]
        jobs.append({"title": clean_text(slug.replace("-", " ")), "url": url})
    return jobs


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


def collect_remoteok_jobs(data: Any, query: str, strict: bool) -> List[JobRow]:
    jobs: List[JobRow] = []
    if not isinstance(data, list):
        return jobs
    for row in data:
        if not isinstance(row, dict) or not row.get("id"):
            continue
        title = str(row.get("position") or row.get("title") or "")
        blob = title + " " + str(row.get("tags") or "") + " " + str(row.get("description") or "")
        if not query_match_loose(blob, query):
            continue
        jobs.append({
            "title": clean_text(title),
            "url": str(row.get("url") or row.get("apply_url") or f"https://remoteok.com/remote-jobs/{row.get('id')}"),
            "description": str(row.get("description") or ""),
            "job_id": str(row.get("id") or ""),
            "company": str(row.get("company") or "RemoteOK"),
            "location": str(row.get("location") or "Remote"),
            "posted_date": str(row.get("date") or ""),
        })
    return jobs


def hn_latest_whos_hiring_id(ctx: RunContext) -> Optional[str]:
    code, body = http_get(
        ctx,
        "https://hn.algolia.com/api/v1/search_by_date?" + urllib.parse.urlencode({
            "query": "who is hiring",
            "tags": "story",
            "hitsPerPage": 50,
        }),
        accept="application/json,*/*",
    )
    data = load_json_body(body)
    if not isinstance(data, dict):
        return None
    cutoff = dt.datetime.now(tz=dt.timezone.utc) - dt.timedelta(days=45)
    for hit in data.get("hits", []):
        if not isinstance(hit, dict):
            continue
        title = clean_text(str(hit.get("title") or ""))
        if not re.fullmatch(r"Ask HN: Who is hiring\? \([A-Za-z]+ \d{4}\)", title, flags=re.I):
            continue
        created = str(hit.get("created_at") or "")
        try:
            created_at = dt.datetime.fromisoformat(created.replace("Z", "+00:00"))
        except Exception:
            continue
        if created_at >= cutoff:
            return str(hit.get("objectID") or "")
    return None


def hn_fetch_item(ctx: RunContext, item_id: str) -> Dict[str, Any]:
    _, body = http_get(ctx, f"https://hacker-news.firebaseio.com/v0/item/{item_id}.json", accept="application/json,*/*")
    data = load_json_body(body)
    return data if isinstance(data, dict) else {}


class SiteAdapter:
    site_name = ""
    method = "requests"
    prefer_curl = False
    inline_description = False

    def fetch(self, ctx: RunContext, query: str, location: str) -> AdapterResult:
        raise NotImplementedError

    def rows_to_raw(self, ctx: RunContext, rows: List[JobRow], method: str, location: str) -> List[RawJob]:
        unique = unique_rows(rows, ctx.limit)
        return [row_to_raw(self.site_name, method, row, location) for row in unique]


class LinkedInAdapter(SiteAdapter):
    site_name = "LinkedIn"
    prefer_curl = True

    def fetch(self, ctx: RunContext, query: str, location: str) -> AdapterResult:
        jobs: List[JobRow] = []
        last_code: Optional[int] = None
        method = "requests"
        empty_pages = 0
        for start in range(0, max(ctx.limit * 2, 20), 10):
            params = urllib.parse.urlencode({"keywords": query, "location": location, "sortBy": "DD", "start": str(start)})
            code, body, method = fetch_page(
                ctx,
                "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?" + params,
                prefer_curl=True,
            )
            last_code = code
            if code != 200:
                fallback = "https://www.linkedin.com/jobs/search/?" + params
                code, body, method = fetch_page(ctx, fallback, prefer_curl=True)
                last_code = code
                if code != 200:
                    break
            batch = parse_linkedin_cards(body)
            if not batch:
                empty_pages += 1
                if empty_pages >= 2:
                    break
                continue
            jobs.extend(batch)
            if len(unique_rows(jobs, ctx.limit)) >= ctx.limit:
                break
            time.sleep(REQUEST_DELAY_SECONDS)
        raw_jobs = self.rows_to_raw(ctx, jobs, method, location)
        return AdapterResult(adapter_health(self.site_name, method, last_code, raw_jobs), raw_jobs)


class IndeedAdapter(SiteAdapter):
    site_name = "Indeed"
    prefer_curl = True

    def fetch(self, ctx: RunContext, query: str, location: str) -> AdapterResult:
        jobs: List[JobRow] = []
        last_code: Optional[int] = None
        method = "requests"
        empty_pages = 0
        for start in range(0, ctx.limit, 10):
            params = urllib.parse.urlencode({"q": query, "l": location, "sort": "date", "start": str(start)})
            code, body, method = fetch_page(ctx, "https://www.indeed.com/jobs?" + params, prefer_curl=True)
            last_code = code
            if code != 200:
                break
            batch = parse_indeed_cards(body)
            if not batch:
                empty_pages += 1
                if empty_pages >= 2:
                    break
                continue
            jobs.extend(batch)
            if len(unique_rows(jobs, ctx.limit)) >= ctx.limit:
                break
            time.sleep(REQUEST_DELAY_SECONDS)
        raw_jobs = self.rows_to_raw(ctx, jobs, method, location)
        return AdapterResult(adapter_health(self.site_name, method, last_code, raw_jobs), raw_jobs)


class DiceAdapter(SiteAdapter):
    site_name = "Dice"
    prefer_curl = True

    def fetch(self, ctx: RunContext, query: str, location: str) -> AdapterResult:
        jobs: List[JobRow] = []
        last_code: Optional[int] = None
        method = "requests"
        for page in range(1, 4):
            params = urllib.parse.urlencode(
                {"q": query, "location": location, "page": str(page), "pageSize": "20", "filters": "postedDate=ONE"}
            )
            code, body, method = fetch_page(ctx, "https://www.dice.com/jobs?" + params, prefer_curl=True)
            last_code = code
            if code != 200:
                break
            batch: List[JobRow] = []
            for url in re.findall(r'data-testid="job-search-job-detail-link"[^>]*href="([^"]+)"', body):
                job_id = url.rstrip("/").split("/")[-1]
                batch.append({"title": "", "url": url, "job_id": job_id})
            for url in re.findall(r'href="(https://www\.dice\.com/job-detail/[^"]+)"', body):
                batch.append({"title": "", "url": url})
            if not batch:
                break
            jobs.extend(batch)
            if len(jobs) >= ctx.limit:
                break
            time.sleep(REQUEST_DELAY_SECONDS)
        raw_jobs = self.rows_to_raw(ctx, jobs, method, location)
        return AdapterResult(adapter_health(self.site_name, method, last_code, raw_jobs), raw_jobs)


class BuiltInAdapter(SiteAdapter):
    site_name = "Built In"
    prefer_curl = True

    def fetch(self, ctx: RunContext, query: str, location: str) -> AdapterResult:
        jobs: List[JobRow] = []
        code: Optional[int] = None
        method = "requests"
        for page in range(1, max(2, (ctx.limit + 24) // 25 + 1)):
            params = urllib.parse.urlencode({"search": query, "page": str(page)})
            code, body, method = fetch_page(ctx, "https://builtin.com/jobs?" + params, prefer_curl=True)
            if code != 200:
                break
            batch = []
            for path in re.findall(r'(/job/[a-z0-9-]+/\d+)', body):
                slug = path.split("/")[2].replace("-", " ").title()
                batch.append({"title": slug, "url": absolute(path, "https://builtin.com")})
            before = len(unique_rows(jobs, ctx.limit))
            jobs.extend(batch)
            if not batch or len(unique_rows(jobs, ctx.limit)) == before or len(unique_rows(jobs, ctx.limit)) >= ctx.limit:
                break
        raw_jobs = self.rows_to_raw(ctx, jobs, method, "")
        return AdapterResult(adapter_health(self.site_name, method, code, raw_jobs), raw_jobs)


class SimplyHiredAdapter(SiteAdapter):
    site_name = "SimplyHired"
    prefer_curl = True

    def fetch(self, ctx: RunContext, query: str, location: str) -> AdapterResult:
        jobs: List[JobRow] = []
        code: Optional[int] = None
        method = "requests"
        for page in range(1, max(2, (ctx.limit + 19) // 20 + 1)):
            params = urllib.parse.urlencode({"q": query, "l": location, "sb": "dd", "pn": str(page)})
            code, body, method = fetch_page(ctx, "https://www.simplyhired.com/search?" + params, prefer_curl=True)
            if code != 200:
                break
            batch: List[JobRow] = []
            for match in re.finditer(r'href="(/job/[^"]+)"[^>]*>([^<]{3,160})</a>', body, flags=re.I):
                batch.append({"title": clean_text(match.group(2)), "url": absolute(match.group(1), "https://www.simplyhired.com")})
            if not batch:
                for path in re.findall(r'(/job/[a-z0-9-]+)', body):
                    batch.append({"title": "", "url": absolute(path, "https://www.simplyhired.com")})
            before = len(unique_rows(jobs, ctx.limit))
            jobs.extend(batch)
            if not batch or len(unique_rows(jobs, ctx.limit)) == before or len(unique_rows(jobs, ctx.limit)) >= ctx.limit:
                break
        raw_jobs = self.rows_to_raw(ctx, jobs, method, location)
        return AdapterResult(adapter_health(self.site_name, method, code, raw_jobs), raw_jobs)


class RemoteOKAdapter(SiteAdapter):
    site_name = "RemoteOK"
    inline_description = True

    def fetch(self, ctx: RunContext, query: str, location: str) -> AdapterResult:
        code, body = http_get(ctx, "https://remoteok.com/api", accept="application/json,*/*")
        data = load_json_body(body)
        jobs = collect_remoteok_jobs(data, query, strict=True)
        raw_jobs = self.rows_to_raw(ctx, jobs, "requests", location)
        return AdapterResult(adapter_health(self.site_name, "requests", code, raw_jobs), raw_jobs)


class WeWorkRemotelyAdapter(SiteAdapter):
    site_name = "We Work Remotely"
    inline_description = True

    def fetch(self, ctx: RunContext, query: str, location: str) -> AdapterResult:
        code, body = http_get(
            ctx,
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
                    desc = clean_text(item.findtext("description") or "")
                    posted = clean_text(item.findtext("pubDate") or "")
                    if not link or not query_match_loose(title + " " + desc, query):
                        continue
                    company, role = ("", title)
                    if ":" in title:
                        company, role = [clean_text(part) for part in title.split(":", 1)]
                    location_match = re.search(
                        r"\b(?:based in|remote[- ]?from|location[: ]+)\s*([^.;|]{2,100})",
                        title + " " + desc, flags=re.I,
                    )
                    jobs.append({
                        "title": role,
                        "url": link,
                        "description": desc,
                        "company": company,
                        "location": clean_text(location_match.group(1)) if location_match else "Remote",
                        "posted_date": posted,
                    })
            except ET.ParseError:
                pass
        raw_jobs = self.rows_to_raw(ctx, jobs, "requests", location)
        return AdapterResult(adapter_health(self.site_name, "requests", code, raw_jobs), raw_jobs)


class RemotiveAdapter(SiteAdapter):
    site_name = "Remotive"
    inline_description = True

    def fetch(self, ctx: RunContext, query: str, location: str) -> AdapterResult:
        code, body = http_get(ctx, "https://remotive.com/api/remote-jobs?category=software-dev", accept="application/json,*/*")
        data = load_json_body(body)
        jobs: List[JobRow] = []
        rows = data.get("jobs", []) if isinstance(data, dict) else []
        for row in rows:
            if not isinstance(row, dict):
                continue
            title = str(row.get("title") or "")
            blob = title + " " + str(row.get("tags") or "") + " " + str(row.get("description") or "")
            if not query_match_loose(blob, query):
                continue
            jobs.append({
                "title": clean_text(title),
                "url": str(row.get("url") or ""),
                "description": str(row.get("description") or ""),
                "job_id": str(row.get("id") or ""),
                "company": str(row.get("company_name") or "Remotive"),
                "location": str(row.get("candidate_required_location") or "Remote"),
                "posted_date": str(row.get("publication_date") or ""),
            })
        raw_jobs = self.rows_to_raw(ctx, jobs, "requests", location)
        return AdapterResult(adapter_health(self.site_name, "requests", code, raw_jobs), raw_jobs)


class HNWhosHiringAdapter(SiteAdapter):
    site_name = "Hacker News Who's Hiring"
    inline_description = True

    def fetch(self, ctx: RunContext, query: str, location: str) -> AdapterResult:
        thread_id = hn_latest_whos_hiring_id(ctx)
        if not thread_id:
            return AdapterResult(Health(self.site_name, "requests", "parser_failed", 0), [])
        story = hn_fetch_item(ctx, thread_id)
        kids = story.get("kids", []) if isinstance(story.get("kids"), list) else []
        jobs: List[JobRow] = []
        for kid in kids[:200]:
            comment = hn_fetch_item(ctx, str(kid))
            text = clean_text(re.sub(r"<[^>]+>", " ", str(comment.get("text") or "")))
            if not text or not query_match_loose(text, query):
                continue
            if not is_us_text(text) and "remote" not in text.lower():
                continue
            segments = [clean_text(segment) for segment in text.split("|") if clean_text(segment)]
            company = segments[0][:120] if segments else ""
            title = ""
            for segment in segments[1:6]:
                if len(segment) <= 180 and re.search(
                    r"\b(engineer|developer|software|firmware|embedded|kernel)\b", segment, flags=re.I,
                ):
                    title = segment
                    break
            if not title:
                title_match = re.search(
                    r"([A-Za-z0-9][^|]{0,80}(?:Engineer|Developer|Software|Firmware|Embedded)[^|]{0,60})",
                    text, flags=re.I,
                )
                title = clean_text(title_match.group(1)) if title_match else ""
            title = title[:180].strip(" ,;:-")
            if not title:
                continue
            jobs.append({
                "title": title,
                "url": f"https://news.ycombinator.com/item?id={kid}",
                "description": text,
                "job_id": str(kid),
                "company": company,
                "location": "Remote" if "remote" in text.lower() else location,
                "posted_date": dt.datetime.fromtimestamp(
                    float(comment.get("time") or story.get("time") or 0),
                    tz=dt.timezone.utc,
                ).date().isoformat() if (comment.get("time") or story.get("time")) else "",
            })
            if len(jobs) >= ctx.limit:
                break
            time.sleep(0.05)
        raw_jobs = self.rows_to_raw(ctx, jobs, "requests", location)
        return AdapterResult(adapter_health(self.site_name, "requests", 200 if jobs else 200, raw_jobs), raw_jobs)


class GlassdoorAdapter(SiteAdapter):
    site_name = "Glassdoor"
    prefer_curl = True

    def fetch(self, ctx: RunContext, query: str, location: str) -> AdapterResult:
        params = urllib.parse.urlencode({"keyword": query, "locT": "N", "locId": "1"})
        code, body, method = fetch_page(ctx, "https://www.glassdoor.com/Job/jobs.htm?" + params, prefer_curl=True)
        jobs: List[JobRow] = []
        for title, link in re.findall(r'"jobTitleText":"([^"]{3,120})"[\s\S]{0,400}?"jobLink":"([^"]+)"', body):
            if query_match_loose(title, query):
                jobs.append({"title": clean_text(title), "url": absolute(link, "https://www.glassdoor.com"), "location": location})
        if not jobs:
            for link in re.findall(r'(/job-listing/[^"\']+)', body):
                slug = clean_text(link.split("/")[-1].replace("-", " "))
                if query_match_loose(slug, query):
                    jobs.append({"title": slug, "url": absolute(link, "https://www.glassdoor.com"), "location": location})
        raw_jobs = self.rows_to_raw(ctx, jobs, method, location)
        return AdapterResult(adapter_health(self.site_name, method, code, raw_jobs), raw_jobs)


class ZipRecruiterAdapter(SiteAdapter):
    site_name = "ZipRecruiter"
    prefer_curl = True

    def fetch(self, ctx: RunContext, query: str, location: str) -> AdapterResult:
        jobs: List[JobRow] = []
        code: Optional[int] = None
        method = "requests"
        for page in range(1, max(2, (ctx.limit + 19) // 20 + 1)):
            params = urllib.parse.urlencode({"search": query, "location": location, "page": str(page)})
            code, body, method = fetch_page(ctx, "https://www.ziprecruiter.com/jobs-search?" + params, prefer_curl=True)
            if code != 200:
                break
            batch: List[JobRow] = []
            for match in re.finditer(
                r'\{[^{}]{0,1200}?"name":"([^"]{5,160})"[^{}]{0,1200}?"url":"(https://www\.ziprecruiter\.com/c/[^"]+)"[^{}]{0,1200}?\}',
                body,
            ):
                url = html.unescape(match.group(2))
                path = urllib.parse.urlparse(url).path
                company_match = re.search(r"/c/([^/]+)/Job/", path)
                location_match = re.search(r"/-in-([^/?]+)", path)
                batch.append({
                    "title": clean_text(match.group(1)),
                    "url": url,
                    "company": clean_text(urllib.parse.unquote(company_match.group(1)).replace("-", " ")) if company_match else "",
                    "location": clean_text(urllib.parse.unquote(location_match.group(1)).replace(",", ", ")) if location_match else "",
                })
            if not batch:
                for match in re.finditer(r'href="(https://www\.ziprecruiter\.com/[^"]+)"[^>]*>([^<]{3,160})</a>', body, flags=re.I):
                    batch.append({"title": clean_text(match.group(2)), "url": match.group(1)})
            before = len(unique_rows(jobs, ctx.limit))
            jobs.extend(batch)
            if not batch or len(unique_rows(jobs, ctx.limit)) == before or len(unique_rows(jobs, ctx.limit)) >= ctx.limit:
                break
        raw_jobs = self.rows_to_raw(ctx, jobs, method, location)
        return AdapterResult(adapter_health(self.site_name, method, code, raw_jobs), raw_jobs)


def monster_js_chunks(html_body: str) -> List[str]:
    chunks = re.findall(r'(/assets/jobsui/_next/static/chunks/[^"]+\.js)', html_body)
    if MONSTER_APP_CHUNK not in chunks:
        chunks.insert(0, MONSTER_APP_CHUNK)
    deduped: List[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        if chunk not in seen:
            seen.add(chunk)
            deduped.append(chunk)
    return deduped


def monster_runtime_config(html_body: str) -> Dict[str, str]:
    config: Dict[str, str] = {"locale": "en-us", "tenant_id": "", "site_id": "", "apigee": "https://appsapi.monster.io"}
    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>([\s\S]+?)</script>', html_body)
    if not match:
        return config
    data = load_json_body(match.group(1))
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
    return config


def monster_samsearch_api_key(app_js: str) -> str:
    idx = app_js.find("search-jobs/samsearch")
    windows = [app_js[max(0, idx - 8000): idx + 500]] if idx >= 0 else []
    windows.append(app_js)
    for window in windows:
        for pattern in (
            r'apikey:"([a-zA-Z0-9._-]{16,64})"',
            r'apiKey:"([a-zA-Z0-9._-]{16,64})"',
            r'"apiKey"\s*:\s*"([a-zA-Z0-9._-]{16,64})"',
        ):
            keys = re.findall(pattern, window, flags=re.I)
            if keys:
                return keys[-1]
    return ""


def parse_monster_samsearch_response(body: str) -> List[JobRow]:
    data = load_json_body(body)
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


class WellfoundAdapter(SiteAdapter):
    site_name = "Wellfound"
    prefer_curl = True

    def fetch(self, ctx: RunContext, query: str, location: str) -> AdapterResult:
        if not has_curl_cffi() and not has_playwright():
            return AdapterResult(Health(self.site_name, "skipped", "skipped", 0, note="missing curl_cffi/playwright"), [])
        params = urllib.parse.urlencode({"search": query, "location": location})
        search_url = "https://wellfound.com/jobs?" + params
        code, body, method = fetch_page(ctx, search_url, prefer_curl=True)
        jobs: List[JobRow] = parse_wellfound_dom(body)
        if not jobs:
            if not has_playwright():
                return AdapterResult(Health(self.site_name, "missing_playwright", "skipped", 0, note="playwright required"), [])
            html_body, captured, pw_method, page_status = playwright_search_jobs(
                search_url, ("wellfound.com/graphql", "wellfound.com", "angel.co"), wait_selector='a[href*="/jobs/"]',
            )
            if pw_method == "missing_playwright":
                return AdapterResult(Health(self.site_name, pw_method, "skipped", 0), [])
            method = pw_method
            if page_status:
                code = page_status
            jobs = merge_playwright_jobs(html_body, captured, dom_parser=parse_wellfound_dom, json_base="https://wellfound.com")
        raw_jobs = self.rows_to_raw(ctx, jobs, method, location)
        return AdapterResult(adapter_health(self.site_name, method, code, raw_jobs), raw_jobs)


class MonsterAdapter(SiteAdapter):
    site_name = "Monster"
    prefer_curl = True

    def fetch(self, ctx: RunContext, query: str, location: str) -> AdapterResult:
        if not has_curl_cffi() and not has_playwright():
            return AdapterResult(Health(self.site_name, "skipped", "skipped", 0, note="missing curl_cffi/playwright"), [])
        params = urllib.parse.urlencode({"q": query, "where": location, "sort": "dt.rv.di"})
        search_url = "https://www.monster.com/jobs/search?" + params
        code, body, method = fetch_page(ctx, search_url, prefer_curl=True)
        jobs: List[JobRow] = []
        match = re.search(r'<script id="__NEXT_DATA__"[^>]*>([\s\S]+?)</script>', body)
        if match:
            data = load_json_body(match.group(1))
            text = json.dumps(data) if isinstance(data, dict) else ""
            for title, url in re.findall(r'"jobTitle":"([^"]{3,120})"[\s\S]{0,300}?"jobUrl":"([^"]+)"', text):
                jobs.append({"title": clean_text(title), "url": url})
        if not jobs:
            jobs.extend(parse_monster_dom(body))
        if not jobs and has_playwright():
            html_body, captured, pw_method, page_status = playwright_search_jobs(
                search_url, ("appsapi.monster.io", "monster.com/jobs", "samsearch"),
                wait_selector='a[href*="/job-openings/"]',
            )
            if pw_method != "missing_playwright":
                method = pw_method
                if page_status:
                    code = page_status
                jobs = filter_job_rows(merge_playwright_jobs(html_body, captured, dom_parser=parse_monster_dom, json_base="https://www.monster.com"))
        if not jobs and code == 403:
            return AdapterResult(Health(self.site_name, method, "blocked", 0, note="DataDome/blocked"), [])
        raw_jobs = self.rows_to_raw(ctx, jobs, method, location)
        return AdapterResult(adapter_health(self.site_name, method, code, raw_jobs), raw_jobs)


class OttaAdapter(SiteAdapter):
    site_name = "Otta"
    prefer_curl = True

    def fetch(self, ctx: RunContext, query: str, location: str) -> AdapterResult:
        if not has_curl_cffi() and not has_playwright():
            return AdapterResult(Health(self.site_name, "skipped", "skipped", 0, note="missing curl_cffi/playwright"), [])
        params = urllib.parse.urlencode({"query": query, "location": location})
        search_url = "https://app.otta.com/search?" + params
        fallback_params = urllib.parse.urlencode({"query": query, "aroundQuery": location})
        fallback_url = OTTA_FALLBACK_SEARCH + "?" + fallback_params
        code, body, method = fetch_page(ctx, search_url, prefer_curl=True)
        jobs: List[JobRow] = []
        jobs.extend(parse_otto_dom(body))
        jobs.extend(decode_otto_apollo(body))
        if not jobs:
            if not has_playwright():
                return AdapterResult(Health(self.site_name, "missing_playwright", "skipped", 0, note="playwright required"), [])
            html_body, captured, pw_method, page_status = playwright_search_jobs(
                search_url, ("api.otta.com/graphql", "app.otta.com", "welcometothejungle.com", "algolia"),
                wait_selector='a[href*="/jobs/"]',
            )
            if pw_method == "missing_playwright":
                return AdapterResult(Health(self.site_name, pw_method, "skipped", 0), [])
            method = pw_method
            if page_status:
                code = page_status
            jobs = filter_job_rows(merge_playwright_jobs(
                html_body, captured, dom_parser=parse_otto_dom, json_base="https://app.otta.com",
                apollo_parser=decode_otto_apollo, extra_parser=parse_wttj_jobs,
            ))
        if not jobs:
            wttj_code, wttj_body, wttj_method = fetch_page(ctx, fallback_url, prefer_curl=True)
            jobs.extend(filter_job_rows(parse_wttj_jobs(wttj_body)))
            if jobs:
                method = wttj_method
                code = wttj_code
        unique = unique_rows(filter_job_rows(jobs), ctx.limit)
        for job in unique:
            if not job.get("title") and job.get("url"):
                job["title"] = clean_text(job["url"].rstrip("/").split("/")[-1].replace("-", " "))
        raw_jobs = self.rows_to_raw(ctx, unique, method, location)
        return AdapterResult(adapter_health(self.site_name, method, code, raw_jobs), raw_jobs)


def build_site_adapters() -> List[SiteAdapter]:
    return [
        LinkedInAdapter(),
        IndeedAdapter(),
        DiceAdapter(),
        BuiltInAdapter(),
        SimplyHiredAdapter(),
        RemoteOKAdapter(),
        WeWorkRemotelyAdapter(),
        RemotiveAdapter(),
        HNWhosHiringAdapter(),
        GlassdoorAdapter(),
        ZipRecruiterAdapter(),
        WellfoundAdapter(),
        MonsterAdapter(),
        OttaAdapter(),
    ]


INLINE_DESCRIPTION_SITES = {"RemoteOK", "We Work Remotely", "Remotive", "Hacker News Who's Hiring"}


def enrich_shortlisted(raw_jobs: Sequence[RawJob], ctx: RunContext) -> None:
    candidates: List[Tuple[RawJob, bool]] = []
    for raw in raw_jobs:
        site = str(raw.raw.get("source_site") or "")
        if site in INLINE_DESCRIPTION_SITES:
            continue
        if date_status(raw, ctx) == DATE_OLD:
            continue
        title = raw.title.lower()
        if title and not any(term in title for term in (
            "software", "firmware", "embedded", "kernel", "driver", "linux",
            "system", "platform", "connectivity", "network", "autonomy",
            "rtos", "bios", "uefi", "bootloader",
        )):
            continue
        if len(clean_text(raw.description)) >= MIN_JD_CHARS:
            continue
        prefer_curl = site in {"LinkedIn", "Indeed", "Dice", "Built In", "SimplyHired", "Glassdoor", "ZipRecruiter", "Wellfound", "Monster", "Otta"}
        candidates.append((raw, prefer_curl))
    if not candidates:
        return
    worker_count = min(6, len(candidates))
    with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as pool:
        futures = [
            pool.submit(enrich_from_html_page, ctx, raw, prefer_curl)
            for raw, prefer_curl in candidates
        ]
        for future in futures:
            try:
                future.result()
            except Exception:
                continue


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
    keys: List[str] = []
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
    site = str(raw.raw.get("source_site") or "")
    text = lower_text(raw.location, raw.url, raw.description)
    if site in {"RemoteOK", "We Work Remotely", "Remotive"}:
        location_text = lower_text(raw.location, raw.title)
        allowed_remote = (
            "united states", "usa", "u.s.", "remote - us", "remote us",
            "north america", "americas", "worldwide", "anywhere", "global",
        )
        foreign_only = (
            "brazil", "poland", "india", "canada", "mexico", "argentina",
            "europe", "emea", "latam", "latin america", "united kingdom",
            "uk only", "germany", "france", "spain", "portugal", "israel",
        )
        if any(signal in location_text for signal in allowed_remote):
            return True
        if any(signal in location_text for signal in foreign_only):
            return False
        description_location = lower_text(raw.description[:2500])
        if any(signal in description_location for signal in foreign_only) and not any(
            signal in description_location for signal in allowed_remote
        ):
            return False
        return location_text.strip() in {"", "remote"}
    if not text:
        return site not in {"", "LinkedIn", "Indeed"}
    if re.search(r"\bus,\s*[a-z]", text):
        return True
    if any(c in text for c in ("india", "karnataka", "canada", "waterloo", "london, uk", "united kingdom")):
        if not re.search(r"\b(us|usa|united states|remote - us|remote us)\b", text):
            us_city = re.search(r"\b(san jose|miami|mountain view|sunnyvale|seattle|austin|san francisco|cupertino|redmond)\b", text)
            if not us_city:
                return False
    if "canada" in text and not re.search(r"\b(us|usa|united states|remote - us|remote us|san jose|miami|mountain view|sunnyvale|seattle|austin)\b", text):
        return False
    if any(x in text for x in ("united states", "usa", "us;", " us", "remote - us", "remote us", "remote")):
        return True
    if is_us_text(text):
        return True
    state_signal = re.search(r"\b(ca|wa|tx|ny|ma|or|co|nc|fl|il|mi|ga|oh|pa|az|nv|va|dc)\b(?:[,; ]|$)", text)
    if state_signal:
        return True
    us_signals = [
        "palo alto", "cupertino", "sunnyvale", "mountain view", "san jose", "san francisco",
        "seattle", "redmond", "austin", "san diego", "santa clara", "atlanta", "dallas", "phoenix",
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
    title_text = lower_text(raw.title, raw.employment_type)
    policy_text = lower_text(raw.title, raw.location, raw.work_mode, raw.employment_type, raw.description)
    reasons: List[str] = []
    site = str(raw.raw.get("source_site") or raw.company or "")
    if not raw.url:
        reasons.append("missing_url")
    elif site not in EXTERNAL_URL_OK_SITES and not is_platform_url(raw.url, site):
        reasons.append("non_platform_source")
    if not location_ok(raw):
        reasons.append("location_mismatch")
    if date_status(raw, ctx) == DATE_OLD:
        reasons.append("old_posting")
    title_reject_patterns = {
        "internship": [r"\bintern(ship)?\b"],
        "part_time": [r"\bpart[- ]time\b", r"\bseasonal\b"],
    }
    for reason, patterns in title_reject_patterns.items():
        if any(re.search(pattern, title_text, flags=re.I) for pattern in patterns):
            reasons.append(reason)
    policy_reject_patterns = {
        "citizenship_required": [
            r"must be (a )?(u\.?s\.?|us) citizen", r"(u\.?s\.?|us) citizen required",
            r"citizenship required", r"(u\.?s\.?|us) person required",
        ],
        "clearance_required": [r"active .*clearance", r"security clearance required", r"top secret", r"ts/sci"],
        "no_sponsorship": [
            r"no sponsorship", r"will not sponsor", r"cannot sponsor",
            r"not eligible .*sponsorship", r"must not require sponsorship",
        ],
    }
    for reason, patterns in policy_reject_patterns.items():
        if any(re.search(pattern, policy_text, flags=re.I) for pattern in patterns):
            reasons.append(reason)
    role_bad = [
        "product manager", "program manager", "technical program manager", "tpm", "director",
        "sales", "recruiter", "legal", "facilities", "financial analyst", "technician",
        "manufacturing", "supply chain", "sdet", "engineer in test",
    ]
    if any(bad in title_text for bad in role_bad):
        reasons.append("non_target_role_family")
    if title_exceeds_experience_level(raw.title):
        reasons.append("experience_level_high")

    return sorted(set(reasons))


def term_hits(raw: RawJob, profile: Dict[str, Any]) -> List[str]:
    text = lower_text(raw.title, raw.description, raw.location)
    terms = list(RANKED_TERMS)
    terms.extend(str(x).lower() for x in profile.get("keywords_include", [])[:80])
    hits: List[str] = []
    seen: set[str] = set()
    for term in terms:
        t = term.lower().strip()
        if not t or len(t) < 2:
            continue
        if term_in_text(t, text) and t not in seen:
            seen.add(t)
            hits.append(t)
    return hits


def term_in_text(term: str, text: str) -> bool:
    escaped = re.escape(term)
    return bool(re.search(rf"(?<![a-z0-9+#./-]){escaped}(?![a-z0-9+#./-])", text))


def weak_role_match(raw: RawJob, profile: Dict[str, Any]) -> bool:
    hits = term_hits(raw, profile)
    title_text = raw.title.lower()
    target_title = any(
        term in title_text
        for term in (
            "firmware", "embedded", "kernel", "device driver", "driver",
            "systems software", "system software", "platform software",
            "operating system", "linux", "network software",
            "connectivity software", "autonomy software", "bootloader",
            "uefi", "bios", "openbmc", "bmc",
        )
    )
    if target_title and hits:
        return False
    generic_software_title = bool(re.search(r"\bsoftware (?:development )?engineer\b", title_text))
    core_text = lower_text(raw.description)
    core_terms = (
        "firmware", "embedded linux", "linux kernel", "kernel module",
        "device driver", "rtos", "bootloader", "u-boot", "device tree",
        "uefi", "bios", "openbmc", "bare metal",
    )
    core_hits = sum(1 for term in core_terms if term in core_text)
    if generic_software_title and core_hits >= 2:
        return False
    return True


def concerns_for(raw: RawJob, ctx: RunContext) -> List[str]:
    concerns: List[str] = []
    text = lower_text(raw.title, raw.description)
    if "sponsor" not in text and "visa" not in text:
        concerns.append("sponsorship not visible")
    if date_status(raw, ctx) == DATE_HIDDEN:
        concerns.append("posting date hidden")
    if re.search(r"\b(senior|sr\.|staff|principal|lead|architect)\b", raw.title, flags=re.I):
        concerns.append("seniority may be high")
    if any(term in text for term in ("export control", "e-verify", "background check")):
        concerns.append("authorization/export-control language needs review")
    return concerns or ["None visible"]


def score_job(raw: RawJob, profile: Dict[str, Any], ctx: RunContext) -> Tuple[int, str]:
    hits = term_hits(raw, profile)
    title = raw.title.lower()
    score = 55
    title_bonus = [
        "firmware", "embedded", "kernel", "device driver", "driver", "linux",
        "systems software", "system software", "platform software", "operating system",
        "bios", "uefi", "boot", "connectivity", "network", "robotics",
    ]
    score += min(24, len(hits) * 3)
    score += sum(3 for term in title_bonus if term in title)
    if date_status(raw, ctx) == DATE_CONFIRMED_RECENT:
        score += 8
    elif date_status(raw, ctx) == DATE_HIDDEN:
        score += 2
    if "sponsorship not visible" in concerns_for(raw, ctx):
        score -= 3
    if re.search(r"\b(principal|staff|lead|architect)\b", title):
        score -= 4
    score = max(0, min(100, score))
    shown = hits[:8]
    reason = "Matches " + ", ".join(shown) if shown else "Profile-adjacent platform posting"
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
            raw.raw["reject_reasons"] = ["duplicate_ledger"]
            rejected["duplicate_ledger"] += 1
            duplicate_count += 1
            continue
        add_seen(raw, run_seen)
        reasons = hard_reject_reasons(raw, ctx)
        if not reasons and weak_role_match(raw, profile):
            reasons.append("weak_role_match")
        if reasons:
            raw.raw["reject_reasons"] = sorted(set(reasons))
            for reason in reasons:
                rejected[reason] += 1
            continue
        score, reason = score_job(raw, profile, ctx)
        if score < 70:
            raw.raw["reject_reasons"] = ["low_score"]
            rejected["low_score"] += 1
            continue
        raw.raw["reject_reasons"] = []
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
    print("Site        | Method     | Status             | Count | Note")
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


def escape_cell(text: str) -> str:
    return str(text or "").replace("|", "\\|").replace("\n", " ").strip()


def format_ledger_section(jobs: Sequence[Job]) -> str:
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        "", f"## Run: {now} (general)", "",
        "| Job Title | Company | Location | Work Mode | Posted | Score | Job ID | URL | Match Reason | Concerns |",
        "|---|---|---|---|---|---:|---|---|---|---|",
    ]
    for job in jobs:
        posted = job.posted
        if job.date_status != DATE_CONFIRMED_RECENT:
            posted = f"{posted} ({job.date_status})"
        lines.append(
            "| " + " | ".join(escape_cell(x) for x in (
                job.title, job.company, job.location, job.work_mode, posted,
                str(job.score), job.job_id, job.url, job.match_reason, "; ".join(job.concerns),
            )) + " |"
        )
    return "\n".join(lines) + "\n"


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
        days = int(prefs.get("job_search_preferences", {}).get("job_posting_age_days") or DEFAULT_DAYS)
    ctx = RunContext(limit=args.limit, days=days, verbose=args.verbose)
    existing = ledger_index(ledger)
    queries = pick_queries(args.query)
    location = DEFAULT_LOCATION
    selected = parse_sites_flag(args.sites)

    print(f"General job search: queries={queries!r}, limit={ctx.limit}, days={ctx.days}, cutoff={ctx.cutoff.isoformat()}")
    print("Site adapters. Dry-run unless --append is set.")

    healths: List[Health] = []
    all_raw: List[RawJob] = []
    for adapter in build_site_adapters():
        if selected and adapter.site_name not in selected:
            continue
        if args.verbose:
            print(f"Fetching {adapter.site_name}...")
        query_batches: List[List[RawJob]] = []
        site_healths: List[Health] = []
        for query in queries:
            try:
                result = adapter.fetch(ctx, query, location)
            except Exception as exc:
                result = AdapterResult(Health(adapter.site_name, adapter.method, "failed", 0, note=str(exc)[:40]), [])
            site_healths.append(result.health)
            query_batches.append(result.raw_jobs)
            if (
                adapter.site_name in {"Wellfound", "Monster", "Otta"}
                and not result.raw_jobs
                and result.health.status != "ok"
            ):
                break
        site_raw = round_robin_raw_batches(query_batches, ctx.limit * len(queries))
        successful = [health for health in site_healths if health.status == "ok"]
        if successful:
            healths.append(Health(
                adapter.site_name,
                successful[0].method,
                "ok",
                len(site_raw),
                note=f"{len(queries)} queries",
            ))
        else:
            healths.append(site_healths[-1] if site_healths else Health(adapter.site_name, adapter.method, "failed", 0))
        all_raw.extend(site_raw)
        if args.verbose:
            print(f"  {adapter.site_name}: {healths[-1].status}, unique raw={len(site_raw)}")

    enrich_shortlisted(all_raw, ctx)
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
    if args.verbose:
        rejected_rows = [raw for raw in all_raw if raw.raw.get("reject_reasons")]
        print("\nRejected job details")
        if not rejected_rows:
            print("None")
        for raw in rejected_rows[:40]:
            reasons = ", ".join(str(reason) for reason in raw.raw.get("reject_reasons", []))
            print(f"- {raw.raw.get('source_site', raw.company)} | {raw.title or 'Untitled'} | {reasons}")
            print(f"  {raw.url}")
        if len(rejected_rows) > 40:
            print(f"... {len(rejected_rows) - 40} more rejected rows")
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
    indeed_fixture = (
        'data-jk="0123456789abcdef"><h2 class="jobTitle">'
        '<span title="Firmware Engineer">Firmware Engineer</span>'
    )
    linkedin_fixture = (
        'data-entity-urn="urn:li:jobPosting:1234567890">'
        '<a href="https://www.linkedin.com/jobs/view/firmware-engineer-1234567890">'
        '<h3 class="base-search-card__title">Firmware Engineer</h3>'
        '<h4 class="base-search-card__subtitle"><a>Acme</a></h4>'
        '<span class="job-search-card__location">Austin, TX</span>'
    )
    check("indeed cards", parse_indeed_cards(indeed_fixture)[0]["title"] == "Firmware Engineer")
    check("linkedin cards", parse_linkedin_cards(linkedin_fixture)[0]["job_id"] == "1234567890")
    check("linkedin title pairing", parse_linkedin_cards(
        linkedin_fixture + linkedin_fixture.replace("1234567890", "9876543210").replace("Firmware Engineer", "Kernel Engineer")
    )[1]["title"] == "Kernel Engineer")
    check("us text ca", is_us_text("San Francisco, CA"))
    check("platform url indeed", is_platform_url("https://www.indeed.com/viewjob?jk=abc", "Indeed"))
    check("platform url reject", not is_platform_url("https://evil.com/job", "Indeed"))
    check("legacy single query picker", pick_query(None) in PROFILE_QUERIES)
    check("default all queries", pick_queries(None) == PROFILE_QUERIES)
    check("explicit query", pick_query("custom query") == "custom query")
    check("loose query rejects people ops", not query_match_loose(
        "Manager of People Operations for a software company", "embedded software engineer"))
    check("loose query accepts embedded", query_match_loose(
        "Embedded C++ developer working on an RTOS", "embedded software engineer"))
    check("sites all", parse_sites_flag("all") is None)
    check("sites filter", "Indeed" in (parse_sites_flag("indeed,remoteok") or set()))
    check("build adapters", len(build_site_adapters()) == 14)
    check("site slugs", SITE_SLUGS["wwr"] == "We Work Remotely")

    ctx = RunContext(limit=5, days=3)
    profile = {"keywords_include": ["firmware", "embedded linux", "kernel"]}
    good = RawJob(
        company="Acme Corp",
        source_method="requests",
        title="Embedded Firmware Engineer",
        url="https://www.indeed.com/viewjob?jk=abc123",
        job_id="abc123",
        location="Chicago, IL, US",
        posted_date=dt.date.today(),
        description="Embedded Linux platform software drivers firmware kernel C C++",
        raw={"source_site": "Indeed"},
    )
    bad = dataclasses.replace(good, title="Financial Analyst", description="finance planning")
    no_sponsor = dataclasses.replace(good, description="This role will not sponsor visas.")
    check("good role not weak", not weak_role_match(good, profile))
    check("bad role weak", weak_role_match(bad, profile))
    check("hardware title weak", weak_role_match(dataclasses.replace(
        good, title="Senior Hardware Engineer", description="firmware FPGA I2C systems"), profile))
    check("generic software with core stack", not weak_role_match(dataclasses.replace(
        good, title="Software Engineer", description="Linux kernel device driver firmware development"), profile))
    check("no sponsorship reject", "no_sponsorship" in hard_reject_reasons(no_sponsor, ctx))
    check("grad bypass staff title", not title_exceeds_experience_level("New Grad Staff Engineer"))
    check("staff title filtered", title_exceeds_experience_level("Staff Firmware Engineer"))
    check("experience level reject", "experience_level_high" in hard_reject_reasons(
        dataclasses.replace(good, title="Principal Firmware Engineer"), ctx))
    check("grad bypass not rejected", "experience_level_high" not in hard_reject_reasons(
        dataclasses.replace(good, title="New Grad Software Engineer"), ctx))

    check("non platform reject", "non_platform_source" in hard_reject_reasons(
        dataclasses.replace(good, url="https://evil.com/x", raw={"source_site": "Indeed"}), ctx))
    check("external ok remoteok", "non_platform_source" not in hard_reject_reasons(
        dataclasses.replace(good, url="https://careers.example.com/job", raw={"source_site": "RemoteOK"}), ctx))
    check("date hidden", date_status(dataclasses.replace(good, posted_date=None), ctx) == DATE_HIDDEN)
    check("foreign remote rejected", not location_ok(dataclasses.replace(
        good, location="Brazil", raw={"source_site": "Remotive"})))
    check("worldwide remote accepted", location_ok(dataclasses.replace(
        good, location="Worldwide", raw={"source_site": "Remotive"})))
    check("footer intern does not reject", "internship" not in hard_reject_reasons(dataclasses.replace(
        good, description="Related searches include Hardware Intern jobs."), ctx))
    check("footer part time does not reject", "part_time" not in hard_reject_reasons(dataclasses.replace(
        good, description="Career guide: how to find part-time work."), ctx))

    existing = {"https://www.indeed.com/viewjob?jk=abc123"}
    dup = dataclasses.replace(good, url="https://www.indeed.com/viewjob?jk=abc123")
    check("dedupe url", is_duplicate(dup, existing, set()))

    score, _ = score_job(good, profile, ctx)
    check("score threshold", score >= 70)

    accepted, rejected, _ = classify_jobs([good], profile, ctx, set())
    check("classify accepts good", len(accepted) == 1)
    _, rejected_bad, _ = classify_jobs([bad], profile, ctx, set())
    check("classify rejects bad", sum(rejected_bad.values()) >= 1)

    remote_rows = collect_remoteok_jobs(
        [{"id": "1", "position": "Firmware Engineer", "description": "embedded linux", "url": "https://remoteok.com/x"}],
        "firmware engineer", strict=True,
    )
    check("remoteok parse", len(remote_rows) == 1)

    if failures:
        print("Self-test failures:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("Self-tests passed.")
    return 0


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="General job-site search automation.")
    parser.add_argument("--append", action="store_true", help="Append accepted jobs to jobsearchdocs/jobs_found.md")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Max raw results per site and query (default 50)")
    parser.add_argument("--days", type=int, default=None, help="Freshness window (default from preferences or 3)")
    parser.add_argument("--query", type=str, default=None, help="Run one search query (default: run all PROFILE_QUERIES)")
    parser.add_argument("--sites", type=str, default="all", help="Comma-separated site slugs or 'all'")
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
