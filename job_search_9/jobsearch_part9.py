#!/usr/bin/env python3
"""
Part 9 job-search automation.

This script implements the repeatable /jobsearch flow for job_search_9 only:
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
import http.cookiejar
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
    "Infineon": ["semiconductor", "embedded", "mcu", "automotive", "power"],
    "STMicroelectronics": ["semiconductor", "embedded", "mcu", "automotive", "sensor"],
    "Microchip": ["semiconductor", "embedded", "mcu", "fpga", "firmware"],
    "Lattice Semiconductor": ["fpga", "semiconductor", "embedded", "programmable logic"],
    "Synaptics": ["semiconductor", "touch", "display", "embedded", "firmware"],
    "Teledyne FLIR": ["thermal imaging", "camera", "embedded", "sensor", "defense"],
    "Hanwha Vision": ["video surveillance", "camera", "embedded", "security", "iot"],
    "Alarm.com": ["smart home", "iot", "embedded", "security", "firmware"],
    "SimpliSafe": ["smart home", "security", "iot", "embedded", "firmware"],
    "iRobot": ["robotics", "vacuum", "embedded", "firmware", "sensors"],
}

US_LOCATION_TEXT = ("united states", "united states of america", "usa", "us,", "us ")

OFFICIAL_DOMAINS = {
    "Infineon": ("jobs.infineon.com", "infineon.com"),
    "STMicroelectronics": ("stmicroelectronics.eightfold.ai", "st.com"),
    "Microchip": ("jobs.smartrecruiters.com", "api.smartrecruiters.com", "microchip.com"),
    "Lattice Semiconductor": ("careers-latticesemi.icims.com", "latticesemi.com"),
    "Synaptics": ("careers.synaptics.com", "synaptics.com"),
    "Teledyne FLIR": ("flir.wd1.myworkdayjobs.com", "flir.com"),
    "Hanwha Vision": ("workforcenow.adp.com", "hanwhavisionamerica.com"),
    "Alarm.com": ("boards-api.greenhouse.io", "job-boards.greenhouse.io", "boards.greenhouse.io", "alarm.com"),
    "SimpliSafe": ("boards-api.greenhouse.io", "job-boards.greenhouse.io", "boards.greenhouse.io", "simplisafe.com"),
    "iRobot": ("irobot.wd503.myworkdayjobs.com", "irobot.com"),
}


ICIMS_JOB_CARD = re.compile(
    r'<a href="(https://careers-latticesemi\.icims\.com/jobs/\d+/[^"]+/job(?:\?[^"]*)?)"[^>]*>.*?<h3[^>]*>\s*(.*?)\s*</h3>',
    re.I | re.S,
)
SYNAPTICS_JOB_LINK = re.compile(
    r'href="(/jobs/\d+-[^"]+)"[^>]*>([^<]{3,120})</a>',
    re.I,
)

WORKABLE_ROW = re.compile(
    r"^\|\s*(?P<title>[^|]+?)\s*\|\s*(?P<department>[^|]+?)\s*\|\s*(?P<location>[^|]+?)\s*\|"
    r"\s*(?P<type>[^|]*?)\s*\|\s*(?P<salary>[^|]*?)\s*\|\s*(?P<posted>[^|]*?)\s*\|"
    r"\s*\[View\]\((?P<details>https://apply\.workable\.com/[^)]+/jobs/view/(?P<shortcode>[A-F0-9]+)\.md)\)\s*\|",
    re.M,
)


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
        if attempt or ctx.search_cache:
            time.sleep(REQUEST_DELAY_SECONDS * (2 ** attempt))
        req = urllib.request.Request(url, headers=req_headers)
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


def oracle_list_url(host: str, site: str, offset: int, limit: int) -> str:
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


def smartrecruiters_public_url(job: Dict[str, Any], public_company: str) -> str:
    job_id = str(job.get("id") or "")
    if job_id:
        return f"https://jobs.smartrecruiters.com/{public_company}/{job_id}"
    ref = str(job.get("refNumber") or "")
    name = first_text(job.get("name"))
    if ref and name:
        return f"https://jobs.smartrecruiters.com/{public_company}/{ref}-{slugify(name)}"
    return str(job.get("ref") or "")


def parse_workable_markdown(body: str, board_slug: str) -> List[Dict[str, str]]:
    jobs: List[Dict[str, str]] = []
    for match in WORKABLE_ROW.finditer(body):
        shortcode = match.group("shortcode")
        jobs.append(
            {
                "title": clean_text(match.group("title")),
                "location": clean_text(match.group("location")),
                "posted": clean_text(match.group("posted")),
                "shortcode": shortcode,
                "url": f"https://apply.workable.com/{board_slug}/j/{shortcode}/",
            }
        )
    jobs.sort(key=lambda job: job.get("posted") or "", reverse=True)
    return jobs


def extract_json_array(text: str, key: str) -> List[Any]:
    decoded = html.unescape(text)
    marker = f'"{key}":'
    start = decoded.find(marker)
    if start < 0:
        return []
    arr_start = decoded.find("[", start)
    if arr_start < 0:
        return []
    depth = 0
    for index in range(arr_start, len(decoded)):
        char = decoded[index]
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                payload = load_json_body(decoded[arr_start : index + 1])
                return payload if isinstance(payload, list) else []
    return []


def eightfold_job_url(job: Dict[str, Any], base: str) -> str:
    raw = str(job.get("publicUrl") or job.get("positionUrl") or job.get("canonicalPositionUrl") or "")
    if raw:
        return absolute(raw, base)
    job_id = str(job.get("id") or "")
    return f"{base.rstrip('/')}/careers/job/{job_id}" if job_id else base


def mediatek_opener() -> urllib.request.OpenerDirector:
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    warmup = urllib.request.Request(
        "https://careers.mediatek.com/en/jobs",
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*", "Accept-Language": "en-US,en;q=0.9"},
    )
    opener.open(warmup, timeout=TIMEOUT).read()
    return opener


def mediatek_parse_detail(body: str, job_id: str) -> Tuple[str, List[str]]:
    title_match = re.search(r"<title>([^<|]+)", body, flags=re.I)
    title = clean_text(html.unescape(title_match.group(1))) if title_match else ""
    related = [value for value in re.findall(r"MUS[0-9A-Z]{10,20}", body) if value != job_id]
    return title, related


def mediatek_fetch_detail(opener: urllib.request.OpenerDirector, job_id: str) -> Tuple[Optional[int], str, str, List[str]]:
    url = f"https://careers.mediatek.com/en/jobs/{job_id}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*", "Accept-Language": "en-US,en;q=0.9"},
    )
    try:
        with opener.open(req, timeout=TIMEOUT) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            title, related = mediatek_parse_detail(body, job_id)
            return resp.status, body, title, related
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        title, related = mediatek_parse_detail(body, job_id)
        return exc.code, body, title, related
    except Exception:
        return None, "", "", []


US_STATE_TEXT = (
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut",
    "delaware", "florida", "georgia", "hawaii", "idaho", "illinois", "indiana", "iowa",
    "kansas", "kentucky", "louisiana", "maine", "maryland", "massachusetts", "michigan",
    "minnesota", "mississippi", "missouri", "montana", "nebraska", "nevada", "new hampshire",
    "new jersey", "new mexico", "new york", "north carolina", "north dakota", "ohio",
    "oklahoma", "oregon", "pennsylvania", "rhode island", "south carolina", "south dakota",
    "tennessee", "texas", "utah", "vermont", "virginia", "washington", "west virginia",
    "wisconsin", "wyoming",
)


US_STATE_ABBR = (
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga", "hi", "id",
    "il", "in", "ia", "ks", "ky", "la", "me", "md", "ma", "mi", "mn", "ms",
    "mo", "mt", "ne", "nv", "nh", "nj", "nm", "ny", "nc", "nd", "oh", "ok",
    "or", "pa", "ri", "sc", "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv",
    "wi", "wy",
)


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

    any_matches: List[Tuple[str, List[str]]] = []
    for facet in iter_workday_facets(data.get("facets", [])):
        param = str(facet.get("facetParameter") or "")
        ids = workday_us_ids_for_facet(facet)
        if param and ids:
            any_matches.append((param, ids))
    if any_matches:
        param, ids = any_matches[0]
        return code, param, ids
    return code, "", []


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


def greenhouse_location_text(job: Dict[str, Any]) -> str:
    parts = [str((job.get("location") or {}).get("name") or "")]
    parts.extend(str(office.get("name") or "") for office in job.get("offices", []) if isinstance(office, dict))
    return " ".join(parts)


def greenhouse_sort_key(job: Dict[str, Any]) -> str:
    return str(job.get("updated_at") or job.get("created_at") or job.get("first_published") or "")


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


class GreenhouseAdapter(BaseAdapter):
    method = "requests"

    def __init__(self, company: str, board: str, public_url_template: str = "") -> None:
        self.company = company
        self.board = board
        self.public_url_template = public_url_template

    def _public_url(self, item: Dict[str, Any]) -> str:
        job_id = str(item.get("id") or "")
        if self.public_url_template and job_id:
            return self.public_url_template.format(id=job_id)
        return str(item.get("absolute_url") or "")

    def fetch(self, ctx: RunContext) -> AdapterResult:
        url = f"https://boards-api.greenhouse.io/v1/boards/{self.board}/jobs?content=true"
        code, body = http_get(ctx, url)
        data = load_json_body(body)
        items = data.get("jobs", []) if isinstance(data, dict) else []
        items = items if isinstance(items, list) else []
        items.sort(key=greenhouse_sort_key, reverse=True)

        us_items = [item for item in items if isinstance(item, dict) and is_us_text(greenhouse_location_text(item))]
        selected = us_items or [item for item in items if isinstance(item, dict)]

        jobs: List[RawJob] = []
        seen: set[str] = set()
        for item in selected:
            job_id = str(item.get("id") or "")
            key = job_id or str(item.get("absolute_url") or "")
            if not key or key in seen:
                continue
            seen.add(key)

            offices = item.get("offices") if isinstance(item.get("offices"), list) else []
            office_locations = "; ".join(
                normalize_location(o.get("location") or o.get("name"))
                for o in offices
                if isinstance(o, dict)
            )
            loc = normalize_location(item.get("location"))
            if office_locations:
                loc = f"{loc}; {office_locations}" if loc else office_locations
            posted = parse_date(item.get("first_published") or item.get("updated_at"))
            desc = html_to_text(str(item.get("content") or ""))
            raw = RawJob(
                company=self.company,
                source_method=self.method,
                title=str(item.get("title") or ""),
                url=self._public_url(item),
                job_id=job_id,
                requisition_id=str(item.get("requisition_id") or item.get("internal_job_id") or ""),
                location=loc,
                posted_raw=str(item.get("first_published") or item.get("updated_at") or ""),
                posted_date=posted,
                description=" ".join([str(item.get("title") or ""), desc]).strip(),
                raw=item,
            )
            jobs.append(raw)
            if len(jobs) >= ctx.limit:
                break

        return AdapterResult(Health(self.company, self.method, status_from(code, len(jobs)), len(jobs)), jobs)


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
        items = items if isinstance(items, list) else []
        items = [item for item in items if isinstance(item, dict) and item.get("isListed") is not False]
        items.sort(key=lambda job: str(job.get("publishedAt") or ""), reverse=True)

        us_items = [item for item in items if is_us_text(ashby_location_text(item))]
        selected = us_items or items

        jobs: List[RawJob] = []
        seen: set[str] = set()
        for item in selected:
            job_id = str(item.get("id") or "")
            job_url = str(item.get("jobUrl") or item.get("applyUrl") or "")
            key = job_id or job_url
            if not key or key in seen:
                continue
            seen.add(key)

            location = normalize_location(item.get("location"))
            secondary = ashby_location_text(item)
            if secondary and secondary not in location:
                location = f"{location}; {secondary}" if location else secondary
            desc = html_to_text(str(item.get("descriptionPlain") or item.get("descriptionHtml") or ""))
            posted = parse_date(item.get("publishedAt"))
            raw = RawJob(
                company=self.company,
                source_method=self.method,
                title=str(item.get("title") or ""),
                url=job_url,
                job_id=job_id,
                requisition_id=job_id,
                location=location or "United States",
                work_mode=str(item.get("workplaceType") or ("remote" if item.get("isRemote") else "")),
                employment_type=str(item.get("employmentType") or ""),
                posted_raw=str(item.get("publishedAt") or ""),
                posted_date=posted,
                description=" ".join([
                    str(item.get("title") or ""),
                    str(item.get("department") or ""),
                    str(item.get("team") or ""),
                    desc,
                ]).strip(),
                raw=item,
            )
            jobs.append(raw)
            if len(jobs) >= ctx.limit:
                break

        return AdapterResult(Health(self.company, self.method, status_from(code, len(jobs)), len(jobs)), jobs)


class EightfoldPCSAdapter(BaseAdapter):
    method = "requests"

    def __init__(self, company: str, base: str, domain: str, paginate: bool = False) -> None:
        self.company = company
        self.base = base.rstrip("/")
        self.domain = domain
        self.paginate = paginate

    def _positions_from_api(self, ctx: RunContext) -> Tuple[Optional[int], List[Dict[str, Any]]]:
        jobs: List[Dict[str, Any]] = []
        last_code: Optional[int] = None
        step = 10 if self.paginate else ctx.limit
        for start in range(0, ctx.limit, step):
            params = {
                "domain": self.domain,
                "query": "",
                "location": "United States",
                "start": str(start),
                "num": str(min(step, ctx.limit - start)),
            }
            url = self.base + "/api/pcsx/search?" + urllib.parse.urlencode(params)
            code, body = http_get(ctx, url, headers={"Referer": self.base + "/careers"})
            last_code = code
            if code != 200:
                break
            data = load_json_body(body)
            batch: List[Dict[str, Any]] = []
            if isinstance(data, dict) and isinstance(data.get("data"), dict):
                batch = data["data"].get("positions", [])
            batch = batch if isinstance(batch, list) else []
            if not batch:
                break
            jobs.extend(batch)
            if len(jobs) >= ctx.limit or not self.paginate:
                break
            time.sleep(REQUEST_DELAY_SECONDS)
        return last_code, jobs

    def _raw_jobs(self, ctx: RunContext, positions: List[Dict[str, Any]]) -> List[RawJob]:
        jobs: List[RawJob] = []
        seen: set[str] = set()
        for pos in positions:
            if not isinstance(pos, dict):
                continue
            title = first_text(pos.get("name"))
            if "do not apply" in title.lower() or "do no apply" in title.lower():
                continue
            jid = str(pos.get("id") or pos.get("displayJobId") or pos.get("positionUrl") or "")
            if not jid or jid in seen:
                continue
            seen.add(jid)
            posted = parse_date(pos.get("postedTs") or pos.get("creationTs") or pos.get("t_update"))
            location = normalize_location(pos.get("locations") or pos.get("standardizedLocations") or pos.get("location"))
            raw = RawJob(
                company=self.company,
                source_method=self.method,
                title=title,
                url=eightfold_job_url(pos, self.base),
                job_id=jid,
                requisition_id=str(pos.get("displayJobId") or ""),
                location=location or "United States",
                posted_raw=str(pos.get("postedTs") or pos.get("creationTs") or pos.get("t_update") or ""),
                posted_date=posted,
                description=title,
                raw=pos,
            )
            enrich_from_html_page(ctx, raw)
            jobs.append(raw)
            if len(jobs) >= ctx.limit:
                break
        return jobs

    def fetch(self, ctx: RunContext) -> AdapterResult:
        last_code, positions = self._positions_from_api(ctx)
        jobs = self._raw_jobs(ctx, positions)
        return AdapterResult(Health(self.company, self.method, status_from(last_code, len(jobs)), len(jobs)), jobs)


class STMicroEightfoldAdapter(BaseAdapter):
    company = "STMicroelectronics"
    method = "requests"
    base = "https://stmicroelectronics.eightfold.ai"
    domain = "stmicroelectronics.com"

    def fetch(self, ctx: RunContext) -> AdapterResult:
        params = {"domain": self.domain, "location": "United States", "start": "0", "num": str(ctx.limit)}
        code, body = http_get(ctx, self.base + "/api/pcsx/search?" + urllib.parse.urlencode(params), headers={"Referer": self.base + "/careers"})
        positions: List[Dict[str, Any]] = []
        if code == 200:
            data = load_json_body(body)
            if isinstance(data, dict) and isinstance(data.get("data"), dict):
                raw = data["data"].get("positions", [])
                positions = raw if isinstance(raw, list) else []

        last_code = code
        if not positions:
            page_params = {"domain": self.domain, "location": "United States", "start": "0"}
            last_code, page_body = http_get(ctx, self.base + "/careers?" + urllib.parse.urlencode(page_params), accept="text/html,*/*", headers={"Referer": self.base + "/careers"})
            positions = extract_json_array(page_body, "positions")

        us_positions = []
        for pos in positions:
            if not isinstance(pos, dict):
                continue
            locs = pos.get("locations") or [pos.get("location")]
            if isinstance(locs, list) and locs and not any(is_us_text(loc) for loc in locs):
                continue
            us_positions.append(pos)
        us_positions.sort(key=lambda job: str(job.get("t_update") or job.get("postedTs") or ""), reverse=True)
        selected = us_positions or [p for p in positions if isinstance(p, dict)]

        jobs: List[RawJob] = []
        seen: set[str] = set()
        for pos in selected:
            jid = str(pos.get("id") or pos.get("canonicalPositionUrl") or "")
            if not jid or jid in seen:
                continue
            seen.add(jid)
            title = first_text(pos.get("name"))
            posted = parse_date(pos.get("t_update") or pos.get("postedTs"))
            raw = RawJob(
                company=self.company,
                source_method=self.method,
                title=title,
                url=eightfold_job_url(pos, self.base),
                job_id=jid,
                requisition_id=str(pos.get("displayJobId") or ""),
                location=normalize_location(pos.get("locations") or pos.get("location")) or "United States",
                posted_raw=str(pos.get("t_update") or pos.get("postedTs") or ""),
                posted_date=posted,
                description=title,
                raw=pos,
            )
            enrich_from_html_page(ctx, raw)
            jobs.append(raw)
            if len(jobs) >= ctx.limit:
                break

        return AdapterResult(Health(self.company, self.method, status_from(last_code, len(jobs)), len(jobs)), jobs)


class ICIMSAdapter(BaseAdapter):
    company = "Lattice Semiconductor"
    method = "requests"
    search_url = "https://careers-latticesemi.icims.com/jobs/search?ss=1&in_iframe=1"

    def fetch(self, ctx: RunContext) -> AdapterResult:
        code, body = http_get(ctx, self.search_url, accept="text/html,*/*")
        items: List[Dict[str, str]] = []
        for match in ICIMS_JOB_CARD.finditer(body):
            raw_url = re.sub(r"\?in_iframe=1$", "", match.group(1))
            title = clean_text(match.group(2))
            if title and raw_url:
                items.append({"title": title, "url": raw_url})

        jobs: List[RawJob] = []
        seen: set[str] = set()
        for item in items:
            url = item.get("url") or ""
            if not url or url in seen:
                continue
            seen.add(url)
            raw = RawJob(
                company=self.company,
                source_method=self.method,
                title=item.get("title") or "",
                url=url,
                job_id=url.rsplit("/", 2)[-2] if "/jobs/" in url else url,
                location="United States",
                description=item.get("title") or "",
                raw=item,
            )
            enrich_from_html_page(ctx, raw)
            jobs.append(raw)
            if len(jobs) >= ctx.limit:
                break

        return AdapterResult(Health(self.company, self.method, status_from(code, len(jobs)), len(jobs)), jobs)


class SynapticsHTMLAdapter(BaseAdapter):
    company = "Synaptics"
    method = "requests"

    def fetch(self, ctx: RunContext) -> AdapterResult:
        urls = [
            "https://careers.synaptics.com/search/jobs/in/country/united-states",
            "https://careers.synaptics.com/search/engineering/jobs",
        ]
        items: List[Dict[str, str]] = []
        last_code: Optional[int] = None
        for url in urls:
            code, body = http_get(ctx, url, accept="text/html,*/*")
            last_code = code
            if code != 200:
                continue
            for match in SYNAPTICS_JOB_LINK.finditer(body):
                title = clean_text(match.group(2))
                job_url = absolute(match.group(1), "https://careers.synaptics.com")
                if title and job_url:
                    items.append({"title": title, "url": job_url})
            if items:
                break

        status = status_from(last_code, len(items))
        if last_code == 403:
            status = "blocked"

        jobs: List[RawJob] = []
        seen: set[str] = set()
        for item in items:
            url = item.get("url") or ""
            if not url or url in seen:
                continue
            seen.add(url)
            raw = RawJob(
                company=self.company,
                source_method=self.method,
                title=item.get("title") or "",
                url=url,
                job_id=url,
                location="United States",
                description=item.get("title") or "",
                raw=item,
            )
            enrich_from_html_page(ctx, raw)
            jobs.append(raw)
            if len(jobs) >= ctx.limit:
                break

        return AdapterResult(Health(self.company, self.method, status, len(jobs)), jobs)


class ADPWorkforceAdapter(BaseAdapter):
    company = "Hanwha Vision"
    method = "requests"
    api_base = "https://workforcenow.adp.com/mascsr/default/careercenter/public/events/staffing/v1/job-requisitions"
    adp_headers = {
        "Accept-Language": "en_US",
        "locale": "en_US",
        "X-Requested-With": "XMLHttpRequest",
        "x-forwarded-host": "workforcenow.adp.com",
    }

    def fetch(self, ctx: RunContext) -> AdapterResult:
        batch: List[Dict[str, Any]] = []
        last_code: Optional[int] = None
        for skip in range(0, ctx.limit, 50):
            params = {
                "cid": "787e0fab-b518-411a-9af8-dd168e00705a",
                "client": "samsop",
                "ccId": "19000101_000001",
                "lang": "en_US",
                "locale": "en_US",
                "$skip": str(skip),
                "$top": str(min(50, ctx.limit - skip)),
                "timeStamp": str(int(time.time() * 1000)),
                "userQuery": "",
            }
            code, body = http_get(ctx, self.api_base + "?" + urllib.parse.urlencode(params), headers=self.adp_headers)
            last_code = code
            if code != 200:
                break
            data = load_json_body(body)
            page = data.get("jobRequisitions", []) if isinstance(data, dict) else []
            page = page if isinstance(page, list) else []
            if not page:
                break
            batch.extend(page)
            if len(batch) >= ctx.limit:
                break
            time.sleep(REQUEST_DELAY_SECONDS)

        us_batch = []
        for job in batch:
            if not isinstance(job, dict):
                continue
            locs = job.get("requisitionLocations", [])
            loc_text = " ".join(
                str(loc.get("address", {}).get("cityName") or "")
                + " "
                + str(loc.get("address", {}).get("countrySubdivisionLevel1", {}).get("codeValue") or "")
                + " "
                + str(loc.get("address", {}).get("countryCode") or "")
                for loc in locs if isinstance(loc, dict)
            )
            if loc_text.strip() and not is_us_text(loc_text):
                continue
            us_batch.append(job)

        us_batch.sort(key=lambda job: str(job.get("postDate") or ""), reverse=True)
        selected = us_batch or [j for j in batch if isinstance(j, dict)]

        jobs: List[RawJob] = []
        seen: set[str] = set()
        for job in selected:
            item_id = str(job.get("itemID") or "")
            if not item_id or item_id in seen:
                continue
            seen.add(item_id)
            title = first_text(job.get("requisitionTitle"))
            url = f"{self.api_base}/{item_id}"
            posted = parse_date(job.get("postDate"))
            raw = RawJob(
                company=self.company,
                source_method=self.method,
                title=title,
                url=url,
                job_id=item_id,
                requisition_id=item_id,
                location="United States",
                posted_raw=str(job.get("postDate") or ""),
                posted_date=posted,
                description=title,
                raw=job,
            )
            enrich_from_html_page(ctx, raw)
            jobs.append(raw)
            if len(jobs) >= ctx.limit:
                break

        return AdapterResult(Health(self.company, self.method, status_from(last_code, len(jobs)), len(jobs)), jobs)


class SmartRecruitersAdapter(BaseAdapter):
    method = "requests"

    def __init__(self, company: str, company_slug: str, public_company: str) -> None:
        self.company = company
        self.company_slug = company_slug
        self.public_company = public_company

    def fetch(self, ctx: RunContext) -> AdapterResult:
        batch: List[Dict[str, Any]] = []
        last_code: Optional[int] = None
        for offset in range(0, ctx.limit, 20):
            params = {"limit": str(min(20, ctx.limit - offset)), "offset": str(offset)}
            url = f"https://api.smartrecruiters.com/v1/companies/{self.company_slug}/postings?" + urllib.parse.urlencode(params)
            code, body = http_get(ctx, url, accept="application/json,*/*")
            last_code = code
            if code != 200:
                break
            data = load_json_body(body)
            page = data.get("content", []) if isinstance(data, dict) else []
            if not isinstance(page, list) or not page:
                break
            batch.extend(page)
            if len(batch) >= ctx.limit:
                break
            time.sleep(REQUEST_DELAY_SECONDS)

        batch.sort(key=lambda job: str(job.get("releasedDate") or ""), reverse=True)
        us_batch = [
            job for job in batch
            if isinstance(job, dict)
            and (
                is_us_text((job.get("location") or {}).get("fullLocation"))
                or is_us_text((job.get("location") or {}).get("country"))
            )
        ]
        selected = us_batch or [j for j in batch if isinstance(j, dict)]

        seen: set[str] = set()
        jobs: List[RawJob] = []
        for job in selected:
            key = str(job.get("id") or job.get("uuid") or job.get("refNumber") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            loc = ""
            if isinstance(job.get("location"), dict):
                loc = first_text(job["location"].get("fullLocation"), job["location"].get("city"))
            posted = parse_date(job.get("releasedDate"))
            desc = html_to_text(str(job.get("jobAd") or ""))
            raw = RawJob(
                company=self.company,
                source_method=self.method,
                title=first_text(job.get("name")),
                url=smartrecruiters_public_url(job, self.public_company),
                job_id=key,
                requisition_id=str(job.get("refNumber") or ""),
                location=loc,
                posted_raw=str(job.get("releasedDate") or ""),
                posted_date=posted,
                description=" ".join([first_text(job.get("name")), desc]).strip(),
                raw=job,
            )
            if len(raw.description) < 200 and job.get("id"):
                detail_url = f"https://api.smartrecruiters.com/v1/companies/{self.company_slug}/postings/{job['id']}"
                dcode, dbody = http_get(ctx, detail_url, accept="application/json,*/*")
                if dcode == 200:
                    detail = load_json_body(dbody)
                    if isinstance(detail, dict):
                        raw.description = " ".join([raw.description, html_to_text(str(detail.get("jobAd") or ""))]).strip()
            if len(raw.description) < 200:
                enrich_from_html_page(ctx, raw)
            jobs.append(raw)
            if len(jobs) >= ctx.limit:
                break

        return AdapterResult(Health(self.company, self.method, status_from(last_code, len(jobs)), len(jobs)), jobs)


def build_adapters() -> List[BaseAdapter]:
    return [
        EightfoldPCSAdapter("Infineon", "https://jobs.infineon.com", "infineon.com", paginate=True),
        STMicroEightfoldAdapter(),
        SmartRecruitersAdapter("Microchip", "Microchip", "Microchip"),
        ICIMSAdapter(),
        SynapticsHTMLAdapter(),
        WorkdayCXSAdapter(
            "Teledyne FLIR",
            "https://flir.wd1.myworkdayjobs.com/wday/cxs/flir/flircareers/jobs",
            "https://flir.wd1.myworkdayjobs.com/flircareers",
        ),
        ADPWorkforceAdapter(),
        GreenhouseAdapter("Alarm.com", "alarmcom"),
        GreenhouseAdapter("SimpliSafe", "simplisafe"),
        WorkdayCXSAdapter(
            "iRobot",
            "https://irobot.wd503.myworkdayjobs.com/wday/cxs/irobot/iRobot/jobs",
            "https://irobot.wd503.myworkdayjobs.com/iRobot",
        ),
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
        return raw.company in {"Applied Intuition", "Skydio", "Waabi", "Torc Robotics", "Zipline"}
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
        "atlanta",
        "morrisville",
        "westford",
        "culver city",
        "hillsboro",
        "phoenix",
        "dallas",
    ]
    return any(signal in text for signal in us_signals)


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
    if raw.company in {"Boston Dynamics", "Skydio", "Aurora", "Figure AI", "Waabi", "Torc Robotics"}:
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

    print(f"Part 9 search: limit={ctx.limit}, days={ctx.days}, cutoff={ctx.cutoff.isoformat()}")
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

    gh_job = {
        "id": 12345,
        "title": "Embedded Linux Engineer",
        "location": {"name": "Home based - Americas"},
        "updated_at": "2026-06-18T00:00:00Z",
        "absolute_url": "https://boards.greenhouse.io/canonical/jobs/12345",
        "content": "<p>kernel embedded firmware</p>",
    }
    check("greenhouse americas", is_us_text(greenhouse_location_text(gh_job)))
    check("greenhouse sort", greenhouse_sort_key(gh_job) == "2026-06-18T00:00:00Z")

    ashby_job = {
        "location": "San Francisco",
        "address": {"postalAddress": {"addressLocality": "San Francisco", "addressRegion": "CA", "addressCountry": "US"}},
    }
    check("ashby location ca", is_us_text(ashby_location_text(ashby_job)))
    check("state abbr", is_us_text("San Francisco, CA"))

    lever_job = {
        "id": "abc",
        "text": "Systems Software Engineer",
        "hostedUrl": "https://jobs.lever.co/example/abc",
        "createdAt": 1718745600000,
        "country": "US",
        "categories": {"location": "Toronto, ON"},
        "descriptionPlain": "embedded linux firmware",
    }
    check("lever us country", is_us_text(lever_job.get("country")))

    facet_fixture = {
        "facets": [
            {
                "facetParameter": "Location_Country",
                "values": [{"descriptor": "United States of America", "id": "abc123"}],
            }
        ]
    }
    ids = workday_us_ids_for_facet(facet_fixture["facets"][0])
    check("workday us ids", ids == ["abc123"])

    loc_raw = RawJob("Cognex", "requests", "t", "https://x", location="US, Massachusetts, Bedford")
    check("location us state city", location_ok(loc_raw))

    check("official url serve", is_official_url("Alarm.com", "https://boards.greenhouse.io/alarmcom/jobs/123"))
    check("term boundary", not term_in_text("ros", "cross-functional debugging"))
    check("term phrase", term_in_text("device driver", "Linux device driver development"))

    ctx = RunContext(limit=5, days=3)
    profile = {"keywords_include": ["firmware", "embedded linux", "kernel", "device driver"]}
    good = RawJob(
        company="iRobot",
        source_method="requests",
        title="Embedded Firmware Engineer",
        url="https://irobot.wd503.myworkdayjobs.com/iRobot/job/Bedford/Embedded-Firmware_R123",
        job_id="R123",
        location="Bedford, MA, US",
        posted_date=dt.date.today(),
        description="Embedded Linux platform software drivers control plane data plane C C++",
    )
    bad = dataclasses.replace(good, title="Financial Analyst", description="finance planning")
    no_sponsor = dataclasses.replace(good, description="This role is not eligible for immigration sponsorship.")
    check("good role not weak", not weak_role_match(good, profile))
    check("bad role weak", weak_role_match(bad, profile))
    check("no sponsorship reject", "no_sponsorship" in hard_reject_reasons(no_sponsor, ctx))
    check("date hidden", date_status(dataclasses.replace(good, posted_date=None), ctx) == DATE_HIDDEN)

    existing = {"https://irobot.wd503.myworkdayjobs.com/iRobot/job/Bedford/Embedded-Firmware_R123"}
    dup = dataclasses.replace(good, url="https://irobot.wd503.myworkdayjobs.com/iRobot/job/Bedford/Embedded-Firmware_R123")
    check("dedupe url", is_duplicate(dup, existing, set()))

    if failures:
        print("Self-test failures:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("Self-tests passed.")
    return 0


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Part 9 official-source job search.")
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
