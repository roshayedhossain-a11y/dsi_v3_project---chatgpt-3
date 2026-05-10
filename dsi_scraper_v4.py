#!/usr/bin/env python3
"""
DSI Ultimate V4: Global Remote Engineering Hiring Signal Collector

Hard promise:
- ONE artifact CSV only: output/FINAL_USE_THIS_ONLY_YYYY-MM-DD.csv
- No rejected/secondary/debug CSV files uploaded.
- Strict ICP only. No weak remote. No unknown headcount. No regional remote.
- Failures like 404/403/429 are handled quietly and never become output rows.

DSI ICP:
- Company headcount 10 to 200 only.
- English comfortable first world or global SaaS/product market.
- Fresh remote worldwide engineering/developer jobs.
- No country restriction. No work authorization restriction. No agency posts.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import requests
import tldextract
import yaml
from bs4 import BeautifulSoup
from dateutil import parser as dateparser
from rapidfuzz import fuzz

ROOT = Path(__file__).resolve().parent
SOURCES_FILE = ROOT / "sources.yml"
OUTPUT_DIR = ROOT / "output"
CACHE_DIR = ROOT / ".cache"
TODAY = datetime.now(timezone.utc)
DATE_STR = TODAY.strftime("%Y-%m-%d")
FINAL_FILE = OUTPUT_DIR / f"FINAL_USE_THIS_ONLY_{DATE_STR}.csv"
MAX_RUNTIME_SECONDS = int(os.environ.get("DSI_MAX_RUNTIME_SECONDS", "540"))
START_TIME = time.time()

TARGET_MARKETS = {
    "United States", "Canada", "United Kingdom", "Ireland", "Australia", "New Zealand", "Singapore",
    "Netherlands", "Germany", "Switzerland", "Sweden", "Norway", "Denmark", "Finland", "UAE",
}
STRICT_HEADCOUNT = {"10 to 50", "51 to 100", "101 to 200"}
JOB_BOARD_DOMAINS = {
    "weworkremotely.com", "remoteok.com", "remotive.com", "jobicy.com", "arbeitnow.com", "himalayas.app",
    "remote.co", "workingnomads.com", "nodesk.co", "freshremote.work", "python.org",
}

FINAL_COLUMNS = [
    "collected_date", "company", "company_domain", "company_website", "company_headcount_bucket", "company_hq_country",
    "job_title", "role_family", "seniority", "location", "dsi_icp_score", "posted_date", "days_old",
    "source", "source_type", "source_trust_score", "job_url", "global_remote_evidence", "restriction_evidence",
    "timezone_evidence", "tech_stack_detected", "score_reasons", "description_summary"
]

ROLE_FAMILY_PATTERNS = {
    "backend": ["backend", "back end", "back-end"],
    "frontend": ["frontend", "front end", "front-end"],
    "fullstack": ["full stack", "fullstack", "full-stack"],
    "software": ["software engineer", "software developer", "product engineer", "application developer"],
    "mobile": ["mobile", "android", "ios", "swift", "kotlin", "flutter", "react native"],
    "devops": ["devops", "site reliability", "sre", "infrastructure engineer", "platform engineer", "cloud engineer", "kubernetes"],
    "qa_automation": ["qa engineer", "quality engineer", "test engineer", "automation engineer", "sdet"],
    "data_engineering": ["data engineer", "analytics engineer", "etl", "data platform"],
    "ai_ml": ["machine learning", "ml engineer", "ai engineer", "llm engineer", "applied ai", "applied ml"],
    "security_engineering": ["security engineer", "cloud security", "application security", "appsec"],
    "developer": ["developer", "python", "java developer", "node", "react developer", "golang", "ruby", "php", "rails", "typescript"],
}
NON_CORE_REJECT = [
    "customer support engineer", "technical support engineer", "support engineer", "help desk", "it support",
    "solutions engineer", "solution engineer", "solutions architect", "sales engineer", "pre sales", "presales",
    "engineering manager", "director of engineering", "vp engineering", "head of engineering", "manager, engineering",
    "product manager", "project manager", "program manager", "scrum master", "business analyst", "data analyst",
    "ux designer", "ui designer", "graphic designer", "product designer", "recruiter", "talent acquisition",
    "intern", "student", "trainee", "apprentice", "werkstudent", "praktikum", "business developer", "marketing",
    "sales", "account executive", "operations", "finance", "legal", "hr", "human resources", "technical writer",
]
AGENCY_TERMS = [
    "recruitment", "recruiting", "staffing", "headhunt", "placement agency", "talent marketplace", "talent solutions",
    "talent group", "talent agency", "hiring agency", "it staffing", "tech staffing", "staff augmentation", "body shop",
    "manpower", "randstad", "adecco", "hays", "michael page", "robert half", "kelly services", "insight global",
    "teksystems", "tek systems", "modis", "cybercoders", "cooper lomaz", "spectrum it", "lorien", "direct sourcing", "wing assistant",
]
ANON_TERMS = ["confidential", "undisclosed", "anonymous", "our client", "private client"]

STRONG_GLOBAL_PATTERNS = [
    r"\bworldwide\b", r"\bwork from anywhere\b", r"\banywhere in the world\b", r"\bremote anywhere\b",
    r"\bglobal remote\b", r"\bglobally remote\b", r"\bremote globally\b", r"\bopen globally\b",
    r"\bopen to candidates worldwide\b", r"\bopen to applicants worldwide\b", r"\bno location restriction\b",
    r"\blocation independent\b", r"\bglobally distributed\b", r"\bfully distributed\b", r"\bhire from anywhere\b",
    r"\ball countries\b", r"\bany country\b", r"\bopen to all locations\b", r"\bworking remotely from anywhere\b",
]
LOCATION_STRONG_PATTERNS = [
    r"^worldwide$", r"^anywhere$", r"^global$", r"remote\s*[-/,()]*\s*worldwide", r"remote\s*[-/,()]*\s*global",
    r"remote\s*[-/,()]*\s*anywhere", r"work from anywhere", r"anywhere in the world", r"no location restriction",
]
WEAK_REMOTE_PATTERNS = [
    r"\bremote\b", r"\bfully remote\b", r"\b100% remote\b", r"\bremote first\b", r"\bremote-first\b",
    r"\bdistributed\b", r"\basync\b", r"\bhome office\b", r"\bvirtual\b", r"\bflexible location\b",
]
HARD_REJECT_PATTERNS = [
    r"\bunited states only\b", r"\bus only\b", r"\busa only\b", r"\bus based only\b", r"\bus-based only\b",
    r"\bmust be in the us\b", r"\bmust be located in the us\b", r"\bmust reside in the us\b", r"\bus residents only\b",
    r"\bus citizen\b", r"\bus citizens only\b", r"\bremote\s*[-,(/]*\s*us\b", r"\bremote us only\b",
    r"\bnorth america\b", r"\bamericas only\b", r"\bremote\s*[-,(/]*\s*north america\b", r"\bremote\s*[-,(/]*\s*americas\b",
    r"\buk only\b", r"\buk-based only\b", r"\bunited kingdom only\b", r"\buk residents only\b", r"\bremote\s*[-,(/]*\s*uk\b",
    r"\bcanada only\b", r"\bcanada-based only\b", r"\bcanadian residents only\b", r"\bremote\s*[-,(/]*\s*canada\b",
    r"\beu only\b", r"\beurope only\b", r"\beuropean union only\b", r"\beu-based only\b", r"\bremote in europe\b", r"\bremote\s*[-,(/]*\s*europe\b",
    r"\bemea\b", r"\bapac\b", r"\blatam\b", r"\blatin america\b", r"\bremote\s*[-,(/]*\s*latam\b",
    r"\baustralia only\b", r"\bnew zealand only\b", r"\bindia only\b", r"\bgermany only\b", r"\bfrance only\b", r"\bspain only\b", r"\bpoland only\b", r"\bportugal only\b", r"\bromania only\b", r"\bserbia only\b", r"\bukraine only\b",
    r"\bwork authorization required\b", r"\bauthorized to work in\b", r"\bmust be authorized to work\b", r"\blegally authorized to work\b", r"\bright to work in\b", r"\bwork permit required\b",
    r"\bno visa sponsorship\b", r"\bvisa sponsorship not available\b", r"\bvisa sponsorship is not available\b", r"\bnot able to sponsor\b", r"\bunable to sponsor\b", r"\bcannot sponsor\b", r"\bsponsorship not provided\b",
    r"\bmust have work authorization\b", r"\beligible to work in\b", r"\bmust be eligible to work in\b",
    r"\bmust be based in\b", r"\bmust live in\b", r"\bmust be located in\b", r"\bapplicants must be based in\b", r"\bapplicants must reside\b", r"\bmust reside in\b",
    r"\bmust be a citizen of\b", r"\bcitizenship required\b", r"\brestricted to residents of\b", r"\bonly open to residents\b", r"\bonly available in\b", r"\bhiring only in\b",
    r"\bhybrid\b", r"\bonsite\b", r"\bon-site\b", r"\boffice required\b", r"\bmust commute\b",
]
LOCATION_REJECT_TERMS = [
    "united states", "usa", "u.s.", "us", "canada", "united kingdom", "uk", "north america", "americas", "europe", "emea", "apac", "latam", "latin america",
    "germany", "france", "spain", "poland", "portugal", "romania", "serbia", "ukraine", "india", "australia", "new zealand",
    "brazil", "mexico", "argentina", "colombia", "chile", "ireland", "netherlands", "sweden", "norway", "denmark", "finland", "singapore",
    "berlin", "london", "new york", "san francisco", "toronto", "austin", "dublin", "bengaluru", "bangalore", "seattle", "sydney", "melbourne",
]
TECH_TERMS = [
    "python", "javascript", "typescript", "react", "node", "node.js", "java", "php", "ruby", "rails", "golang", "go",
    "rust", "kotlin", "swift", "flutter", "aws", "gcp", "azure", "kubernetes", "docker", "terraform", "postgres",
    "postgresql", "mysql", "mongodb", "redis", "graphql", "rest api", "microservice", "ci/cd", "kafka", "spark", "llm", "machine learning", "ai", "data pipeline",
]

@dataclass
class RawJob:
    source: str
    source_type: str
    trust_score: int
    company: str
    title: str
    location: str
    url: str
    posted: Optional[datetime]
    description: str
    job_type: str = ""
    ats_job_id: str = ""
    company_meta: Dict[str, Any] = None

class PatientHTTP:
    def __init__(self, timeout: int = 18, debug: bool = False):
        self.session = requests.Session()
        self.timeout = timeout
        self.debug = debug
        self.last_request_by_domain: Dict[str, float] = {}
        self.session.headers.update({
            "User-Agent": "DSI-Remote-Hiring-Collector/4.1 (+https://www.dsinnovators.com/; public job research)",
            "Accept": "application/json, application/xml, text/xml, text/html, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
        })

    def expired(self) -> bool:
        return time.time() - START_TIME > MAX_RUNTIME_SECONDS

    def get(self, url: str, min_delay: float = 0.35, retries: int = 2, cache_hours: int = 12) -> Tuple[Optional[requests.Response], str]:
        if self.expired():
            return None, "runtime_limit"
        CACHE_DIR.mkdir(exist_ok=True)
        key = hashlib.sha1(url.encode("utf-8")).hexdigest()
        cache_path = CACHE_DIR / f"{key}.json"
        if cache_path.exists():
            try:
                blob = json.loads(cache_path.read_text("utf-8"))
                if time.time() - blob.get("ts", 0) < cache_hours * 3600:
                    resp = requests.Response()
                    resp.status_code = 200
                    resp._content = blob.get("body", "").encode("utf-8", errors="ignore")
                    resp.headers["Content-Type"] = blob.get("content_type", "")
                    resp.url = url
                    return resp, "200_cache"
            except Exception:
                pass
        domain = urlparse(url).netloc.lower()
        elapsed = time.time() - self.last_request_by_domain.get(domain, 0)
        if elapsed < min_delay:
            time.sleep(min_delay - elapsed + random.uniform(0.05, 0.20))
        self.last_request_by_domain[domain] = time.time()
        for attempt in range(retries + 1):
            if self.expired():
                return None, "runtime_limit"
            try:
                r = self.session.get(url, timeout=self.timeout, allow_redirects=True)
                if r.status_code == 200:
                    ctype = r.headers.get("Content-Type", "")[:120]
                    text = r.text if len(r.text) < 2_500_000 else r.text[:2_500_000]
                    try:
                        cache_path.write_text(json.dumps({"ts": time.time(), "body": text, "content_type": ctype}), "utf-8")
                    except Exception:
                        pass
                    return r, "200"
                if r.status_code == 429:
                    retry_after = r.headers.get("Retry-After")
                    wait_s = int(retry_after) if retry_after and retry_after.isdigit() else min(60, 8 * (attempt + 1))
                    time.sleep(wait_s + random.uniform(0, 1.0))
                    continue
                if r.status_code in (403, 404, 410):
                    return None, str(r.status_code)
                if 500 <= r.status_code < 600 and attempt < retries:
                    time.sleep(2 * (attempt + 1))
                    continue
                return None, str(r.status_code)
            except Exception as e:
                if attempt < retries:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                return None, f"exception:{type(e).__name__}"
        return None, "failed"

# ---------- helpers ----------
def clean_text(x: Any) -> str:
    if x is None:
        return ""
    s = str(x)
    if "<" in s and ">" in s:
        s = BeautifulSoup(s, "html.parser").get_text(" ")
    return re.sub(r"\s+", " ", s).strip()

def lower(x: Any) -> str:
    return clean_text(x).lower()

def parse_date(raw: Any) -> Optional[datetime]:
    if raw in (None, ""):
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    if isinstance(raw, (int, float)):
        try:
            val = raw / 1000 if raw > 1e12 else raw
            return datetime.fromtimestamp(val, tz=timezone.utc)
        except Exception:
            return None
    try:
        dt = dateparser.parse(str(raw))
        if not dt:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None

def fmt_date(dt: Optional[datetime]) -> str:
    return dt.strftime("%Y-%m-%d") if dt else ""

def days_old(dt: Optional[datetime]) -> int:
    if not dt:
        return 999
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0, (TODAY - dt).days)

def domain_from_url(url: str) -> str:
    if not url:
        return ""
    ext = tldextract.extract(url)
    if not ext.domain or not ext.suffix:
        return ""
    return f"{ext.domain}.{ext.suffix}".lower()

def normalized_company(name: str) -> str:
    s = lower(name)
    s = re.sub(r"\b(inc|llc|ltd|limited|gmbh|bv|pty|co|company|corp|corporation)\b", "", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()

def title_norm(title: str) -> str:
    s = lower(title)
    s = re.sub(r"\b(senior|sr|lead|principal|staff|junior|jr|mid|remote|worldwide|global|ii|iii|iv)\b", "", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()

def evidence(patterns: Iterable[str], text: str) -> str:
    for p in patterns:
        m = re.search(p, text, flags=re.I)
        if m:
            return m.group(0)[:140]
    return ""

def role_family(title: str) -> str:
    t = lower(title)
    for bad in NON_CORE_REJECT:
        if bad in t:
            return "reject"
    for fam, pats in ROLE_FAMILY_PATTERNS.items():
        for p in pats:
            if p in t:
                return fam
    return "reject"

def seniority(title: str) -> str:
    t = lower(title)
    if any(x in t for x in ["principal"]): return "principal"
    if any(x in t for x in ["staff"]): return "staff"
    if any(x in t for x in ["lead", "tech lead", "technical lead"]): return "lead"
    if any(x in t for x in ["senior", "sr.", "sr "]): return "senior"
    if any(x in t for x in ["junior", "jr.", "intern", "trainee"]): return "reject"
    return "mid_or_unspecified"

def is_agency_or_anon(company: str) -> bool:
    c = lower(company)
    return any(x in c for x in AGENCY_TERMS) or any(x in c for x in ANON_TERMS) or not c

def restriction_status(title: str, location: str, desc: str) -> Tuple[bool, str]:
    loc = lower(location)
    combined = f"{lower(title)} {loc} {lower(desc[:4500])}"
    ev = evidence(HARD_REJECT_PATTERNS, combined)
    if ev:
        return True, ev
    if loc:
        strong_loc = evidence(LOCATION_STRONG_PATTERNS, loc)
        if not strong_loc:
            for place in LOCATION_REJECT_TERMS:
                if re.search(rf"\b{re.escape(place)}\b", loc):
                    return True, place
    return False, "no country restriction found"

def global_remote_status(location: str, desc: str) -> Tuple[str, str]:
    loc = lower(location)
    desc_l = lower(desc[:5000])
    ev_loc = evidence(LOCATION_STRONG_PATTERNS, loc)
    if ev_loc:
        return "proven_worldwide", ev_loc
    ev = evidence(STRONG_GLOBAL_PATTERNS, f"{loc} {desc_l}")
    if ev:
        return "proven_worldwide", ev
    if evidence(WEAK_REMOTE_PATTERNS, f"{loc} {desc_l}"):
        return "weak_remote", evidence(WEAK_REMOTE_PATTERNS, f"{loc} {desc_l}") or "remote"
    return "reject_unknown_location", "no global remote proof"

def timezone_evidence(desc: str) -> str:
    d = lower(desc[:5000])
    for phrase in ["async", "asynchronous", "flexible hours", "work your own hours", "timezone flexible", "distributed team", "remote-first", "remote first"]:
        if phrase in d:
            return phrase
    return ""

def tech_stack(desc: str) -> str:
    d = lower(desc[:7000])
    found = []
    for term in TECH_TERMS:
        if re.search(rf"\b{re.escape(term)}\b", d):
            found.append(term)
    return ", ".join(sorted(set(found))[:14])

def source_meta(src: Dict[str, Any]) -> Dict[str, Any]:
    meta = dict(src.get("company_meta") or {})
    for key in ["company_domain", "company_website", "company_name"]:
        if src.get(key) and not meta.get(key):
            meta[key] = src.get(key)
    return meta

def make_job(src: Dict[str, Any], company: str, title: str, location: str, url: str, posted: Any, desc: str, job_type: str = "", job_id: str = "") -> RawJob:
    return RawJob(
        source=src.get("name", src.get("type", "unknown")),
        source_type=src.get("source_type_label", src.get("type", "unknown")),
        trust_score=int(src.get("trust_score", 5)),
        company=clean_text(company or src.get("company_name", "")),
        title=clean_text(title),
        location=clean_text(location),
        url=clean_text(url),
        posted=parse_date(posted),
        description=clean_text(desc),
        job_type=clean_text(job_type),
        ats_job_id=str(job_id or ""),
        company_meta=source_meta(src),
    )

def extract_meta_registry(sources: List[Dict[str, Any]]) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    by_domain, by_name = {}, {}
    for s in sources:
        meta = source_meta(s)
        d = meta.get("company_domain") or domain_from_url(meta.get("company_website", ""))
        if d:
            by_domain[d.lower()] = meta
        n = normalized_company(meta.get("company_name") or s.get("company_name") or "")
        if n:
            by_name[n] = meta
    return by_domain, by_name

# ---------- fetchers ----------
def fetch_remotive(http: PatientHTTP, src: Dict[str, Any]) -> List[RawJob]:
    out = []
    for cat in src.get("categories", ["software-dev"]):
        r, _ = http.get(f"https://remotive.com/api/remote-jobs?category={cat}&limit={src.get('limit', 500)}", min_delay=src.get("delay_seconds", 0.8))
        if not r: continue
        try: data = r.json()
        except Exception: continue
        for j in data.get("jobs", []):
            out.append(make_job(src, j.get("company_name", ""), j.get("title", ""), j.get("candidate_required_location", ""), j.get("url", ""), j.get("publication_date"), j.get("description", ""), j.get("job_type", ""), j.get("id", "")))
    return out

def fetch_jobicy(http: PatientHTTP, src: Dict[str, Any]) -> List[RawJob]:
    out = []
    for ind in src.get("industries", ["engineering"]):
        r, _ = http.get(f"https://jobicy.com/api/v2/remote-jobs?count={src.get('limit', 50)}&industry={ind}", min_delay=src.get("delay_seconds", 0.8))
        if not r: continue
        try: data = r.json()
        except Exception: continue
        for j in data.get("jobs", []):
            out.append(make_job(src, j.get("companyName", ""), j.get("jobTitle", ""), j.get("jobGeo", ""), j.get("url", ""), j.get("pubDate"), j.get("jobDescription", ""), j.get("jobType", ""), j.get("id", "")))
    return out

def fetch_remoteok(http: PatientHTTP, src: Dict[str, Any]) -> List[RawJob]:
    r, _ = http.get("https://remoteok.com/api", min_delay=src.get("delay_seconds", 1.5), retries=3)
    if not r: return []
    try: data = r.json()
    except Exception: return []
    out = []
    for j in data[1:] if isinstance(data, list) else []:
        out.append(make_job(src, j.get("company", ""), j.get("position", ""), j.get("location", ""), j.get("url", ""), j.get("epoch"), j.get("description", ""), "", j.get("id", "")))
    return out

def fetch_arbeitnow(http: PatientHTTP, src: Dict[str, Any]) -> List[RawJob]:
    out = []
    for page in range(1, int(src.get("max_pages", 5)) + 1):
        r, _ = http.get(f"https://arbeitnow.com/api/job-board-api?page={page}", min_delay=src.get("delay_seconds", 0.8))
        if not r: continue
        try: data = r.json()
        except Exception: continue
        items = data.get("data", [])
        if not items: break
        for j in items:
            if not j.get("remote"):
                continue
            out.append(make_job(src, j.get("company_name", ""), j.get("title", ""), j.get("location", ""), j.get("url", ""), j.get("created_at"), j.get("description", ""), ", ".join(j.get("job_types") or []), j.get("slug", "")))
    return out

def fetch_himalayas(http: PatientHTTP, src: Dict[str, Any]) -> List[RawJob]:
    out = []
    for q in src.get("queries", ["engineer"]):
        r, _ = http.get(f"https://himalayas.app/jobs/api?q={requests.utils.quote(q)}&limit={src.get('limit', 100)}&remote=true", min_delay=src.get("delay_seconds", 0.8))
        if not r: continue
        try: data = r.json()
        except Exception: continue
        for j in data.get("jobs", []):
            loc = j.get("locationRestrictions", "") or j.get("location", "") or ""
            if isinstance(loc, list): loc = ", ".join(loc)
            company = j.get("companyName", "") or (j.get("company") or {}).get("name", "")
            out.append(make_job(src, company, j.get("title", ""), loc, j.get("applicationLink", "") or j.get("jobUrl", ""), j.get("createdAt"), j.get("description", ""), j.get("employmentType", ""), j.get("id", "")))
    return out

def fetch_rss(http: PatientHTTP, src: Dict[str, Any]) -> List[RawJob]:
    r, _ = http.get(src["url"], min_delay=src.get("delay_seconds", 0.8))
    if not r: return []
    try:
        from xml.etree import ElementTree as ET
        root = ET.fromstring(r.content)
    except Exception:
        return []
    out = []
    for item in root.findall("./channel/item"):
        raw_title = clean_text(item.findtext("title", ""))
        link = clean_text(item.findtext("link", ""))
        desc = item.findtext("description", "") or ""
        posted = item.findtext("pubDate", "") or item.findtext("date", "") or ""
        company, title = "", raw_title
        if src.get("title_format") == "company_colon_title" and ":" in raw_title:
            company, title = [x.strip() for x in raw_title.split(":", 1)]
        company = company or src.get("default_company", "")
        # Fetch full page for evidence only. If blocked, use RSS description.
        full_desc = desc
        if link and src.get("fetch_detail", True):
            detail, _ = http.get(link, min_delay=src.get("detail_delay_seconds", 0.5), retries=1)
            if detail:
                full_desc = detail.text
        out.append(make_job(src, company, title, src.get("default_location", "Remote"), link, posted, full_desc, "", link))
    return out

def fetch_greenhouse(http: PatientHTTP, src: Dict[str, Any]) -> List[RawJob]:
    board = src["board"]
    r, _ = http.get(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true", min_delay=src.get("delay_seconds", 0.45))
    if not r: return []
    try: data = r.json()
    except Exception: return []
    out = []
    for j in data.get("jobs", []):
        loc_obj = j.get("location") or {}
        loc = loc_obj.get("name", "") if isinstance(loc_obj, dict) else str(loc_obj)
        out.append(make_job(src, src.get("company_name", board), j.get("title", ""), loc, j.get("absolute_url", ""), j.get("updated_at"), j.get("content", ""), "", j.get("id", "")))
    return out

def fetch_lever(http: PatientHTTP, src: Dict[str, Any]) -> List[RawJob]:
    board = src["board"]
    r, _ = http.get(f"https://api.lever.co/v0/postings/{board}?mode=json", min_delay=src.get("delay_seconds", 0.45))
    if not r: return []
    try: data = r.json()
    except Exception: return []
    if not isinstance(data, list): return []
    out = []
    for j in data:
        cats = j.get("categories") or {}
        loc = cats.get("location") or cats.get("allLocations") or ""
        if isinstance(loc, list): loc = ", ".join(loc)
        desc = j.get("descriptionPlain") or j.get("description") or ""
        out.append(make_job(src, src.get("company_name", board), j.get("text", ""), loc, j.get("hostedUrl", ""), j.get("createdAt"), desc, cats.get("commitment", ""), j.get("id", "")))
    return out

def fetch_ashby(http: PatientHTTP, src: Dict[str, Any]) -> List[RawJob]:
    board = src["board"]
    boards_to_try = [board]
    if "." in board:
        boards_to_try.append(board.replace(".", ""))
    out = []
    for b in boards_to_try:
        r, _ = http.get(f"https://jobs.ashbyhq.com/api/non-user-facing/job-board/{b}/posting-group/published", min_delay=src.get("delay_seconds", 0.45))
        if not r: continue
        try: data = r.json()
        except Exception: continue
        for j in data.get("jobPostings", []):
            out.append(make_job(src, src.get("company_name", board), j.get("title", ""), j.get("locationName", "") or j.get("location", ""), j.get("jobUrl", "") or j.get("applyUrl", ""), j.get("publishedAt"), j.get("descriptionHtml", "") or j.get("description", ""), j.get("employmentType", ""), j.get("id", "")))
        if out:
            break
    return out

def fetch_smartrecruiters(http: PatientHTTP, src: Dict[str, Any]) -> List[RawJob]:
    company = src["board"]
    r, _ = http.get(f"https://api.smartrecruiters.com/v1/companies/{company}/postings?limit=100", min_delay=src.get("delay_seconds", 0.6))
    if not r: return []
    try: data = r.json()
    except Exception: return []
    out = []
    for j in data.get("content", []) or []:
        loc_obj = j.get("location") or {}
        loc = loc_obj.get("city", "") or loc_obj.get("region", "") or loc_obj.get("country", "") or ""
        detail_url = (j.get("ref") or "")
        desc = ""
        if detail_url:
            d, _ = http.get(detail_url, min_delay=src.get("delay_seconds", 0.6), retries=1)
            if d:
                try:
                    jd = d.json(); desc = jd.get("jobAd", {}).get("sections", {}).get("jobDescription", "") or jd.get("description", "")
                    loc2 = jd.get("location", {}) or {}
                    loc = loc or loc2.get("city", "") or loc2.get("country", "") or ""
                except Exception:
                    desc = d.text
        out.append(make_job(src, src.get("company_name", company), j.get("name", ""), loc, j.get("applyUrl", "") or j.get("releasedDate", "") or j.get("ref", ""), j.get("releasedDate"), desc, "", j.get("id", "")))
    return out

def discover_ats_links(html: str, base_url: str) -> List[Tuple[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"])
        if any(x in href for x in ["boards.greenhouse.io", "job-boards.greenhouse.io", "jobs.lever.co", "jobs.ashbyhq.com"]):
            links.append(href)
    text = html
    for pat in [r"https?://boards\.greenhouse\.io/[^\s\"'<>]+", r"https?://job-boards\.greenhouse\.io/[^\s\"'<>]+", r"https?://jobs\.lever\.co/[^\s\"'<>]+", r"https?://jobs\.ashbyhq\.com/[^\s\"'<>]+"]:
        links.extend(re.findall(pat, text))
    out = []
    seen = set()
    for href in links:
        p = urlparse(href)
        parts = [x for x in p.path.strip("/").split("/") if x]
        if not parts: continue
        slug = parts[0]
        typ = ""
        if "greenhouse" in p.netloc: typ = "greenhouse"
        elif "lever" in p.netloc: typ = "lever"
        elif "ashby" in p.netloc: typ = "ashby"
        key = (typ, slug)
        if typ and key not in seen:
            seen.add(key); out.append(key)
    return out

def fetch_company_career(http: PatientHTTP, src: Dict[str, Any]) -> List[RawJob]:
    # Source discovery only. It reduces guessed ATS 404s by reading the company's own career page first.
    urls = src.get("career_urls") or [src.get("career_url") or src.get("company_website") or ""]
    out = []
    for u in urls:
        if not u: continue
        r, _ = http.get(u, min_delay=src.get("delay_seconds", 0.5), retries=1)
        if not r: continue
        for typ, slug in discover_ats_links(r.text, u):
            child = dict(src)
            child["type"] = typ
            child["board"] = slug
            child["name"] = f"{src.get('company_name', slug)} discovered {typ}"
            child["source_type_label"] = "official_company_discovered_ats"
            child["trust_score"] = max(int(src.get("trust_score", 9)), 9)
            fetcher = FETCHERS.get(typ)
            if fetcher:
                out.extend(fetcher(http, child))
        if out:
            break
    return out

FETCHERS = {
    "remotive_api": fetch_remotive,
    "jobicy_api": fetch_jobicy,
    "remoteok_api": fetch_remoteok,
    "arbeitnow_api": fetch_arbeitnow,
    "himalayas_api": fetch_himalayas,
    "rss": fetch_rss,
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "ashby": fetch_ashby,
    "smartrecruiters": fetch_smartrecruiters,
    "company_career": fetch_company_career,
}

# ---------- scoring / row ----------
def metadata_for_job(job: RawJob, by_domain: Dict[str, Dict[str, Any]], by_name: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    meta = dict(job.company_meta or {})
    url_domain = domain_from_url(meta.get("company_website", "")) or domain_from_url(job.url)
    # Never treat job board domain as company domain.
    if url_domain in JOB_BOARD_DOMAINS:
        url_domain = ""
    if url_domain and url_domain in by_domain:
        meta.update(by_domain[url_domain])
    n = normalized_company(job.company)
    if n and n in by_name:
        meta.update(by_name[n])
    return meta

def score_job(job: RawJob, fam: str, global_ev: str, restriction_ev: str, tz_ev: str, tech: str, meta: Dict[str, Any]) -> Tuple[int, str]:
    score = 0; reasons = []
    score += 30; reasons.append("proven remote worldwide +30")
    if restriction_ev == "no country restriction found": score += 15; reasons.append("no country restriction found +15")
    if tz_ev: score += 5; reasons.append("timezone or async friendly +5")
    if meta.get("headcount_bucket") in STRICT_HEADCOUNT: score += 20; reasons.append("headcount 10-200 +20")
    if meta.get("hq_country") in TARGET_MARKETS or meta.get("target_market_fit") == "yes": score += 10; reasons.append("target English/global SaaS market +10")
    if meta.get("company_type") or "saas" in lower(job.description) or "software" in lower(job.description): score += 5; reasons.append("software/product company +5")
    score += 15; reasons.append("core DSI engineering role +15")
    age = days_old(job.posted)
    if age <= 7: score += 10; reasons.append("posted within 7 days +10")
    elif age <= 14: score += 7; reasons.append("posted within 14 days +7")
    elif age <= 21: score += 5; reasons.append("posted within 21 days +5")
    elif age <= 30: score += 2; reasons.append("posted within 30 days +2")
    if job.trust_score >= 9: score += 10; reasons.append("official ATS/company career source +10")
    elif job.trust_score >= 6: score += 6; reasons.append("trusted remote board +6")
    if tech: score += 3; reasons.append("tech stack detected +3")
    return min(score, 100), " | ".join(reasons)

def normalize_url(url: str) -> str:
    try:
        p = urlparse(url)
        return f"{p.scheme}://{p.netloc}{p.path}".rstrip("/").lower()
    except Exception:
        return url.lower().strip()

def row_from_job(job: RawJob, by_domain: Dict[str, Dict[str, Any]], by_name: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not job.url or is_agency_or_anon(job.company): return None
    fam = role_family(job.title)
    if fam == "reject": return None
    sen = seniority(job.title)
    if sen == "reject": return None
    age = days_old(job.posted)
    if age > 30: return None
    restricted, restriction_ev = restriction_status(job.title, job.location, job.description)
    if restricted: return None
    remote_class, global_ev = global_remote_status(job.location, job.description)
    if remote_class != "proven_worldwide": return None
    meta = metadata_for_job(job, by_domain, by_name)
    head_bucket = meta.get("headcount_bucket", "unknown")
    if head_bucket not in STRICT_HEADCOUNT: return None
    if not (meta.get("hq_country") in TARGET_MARKETS or meta.get("target_market_fit") == "yes"): return None
    domain = meta.get("company_domain") or domain_from_url(meta.get("company_website", ""))
    if not domain or domain in JOB_BOARD_DOMAINS: return None
    tz = timezone_evidence(job.description)
    tech = tech_stack(job.description)
    score, reasons = score_job(job, fam, global_ev, restriction_ev, tz, tech, meta)
    if score < 80: return None
    return {
        "collected_date": DATE_STR,
        "company": job.company or meta.get("company_name", ""),
        "company_domain": domain,
        "company_website": meta.get("company_website", f"https://{domain}"),
        "company_headcount_bucket": head_bucket,
        "company_hq_country": meta.get("hq_country", ""),
        "job_title": job.title,
        "role_family": fam,
        "seniority": sen,
        "location": job.location,
        "dsi_icp_score": score,
        "posted_date": fmt_date(job.posted),
        "days_old": age,
        "source": job.source,
        "source_type": job.source_type,
        "source_trust_score": job.trust_score,
        "job_url": job.url,
        "global_remote_evidence": global_ev,
        "restriction_evidence": restriction_ev,
        "timezone_evidence": tz,
        "tech_stack_detected": tech,
        "score_reasons": reasons,
        "description_summary": clean_text(job.description)[:260],
        "_url": normalize_url(job.url), "_company_key": domain, "_title_norm": title_norm(job.title), "_role_family": fam,
    }

def dedupe(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []; seen_urls = set()
    for row in sorted(rows, key=lambda r: (-int(r.get("dsi_icp_score", 0)), r.get("company", ""))):
        u = row.get("_url", "")
        if u and u in seen_urls: continue
        dup = False
        for old in out:
            if row["_company_key"] == old["_company_key"] and row["_role_family"] == old["_role_family"]:
                if fuzz.ratio(row["_title_norm"], old["_title_norm"]) >= 92:
                    dup = True; break
        if dup: continue
        seen_urls.add(u); out.append(row)
    for r in out:
        for k in ["_url", "_company_key", "_title_norm", "_role_family"]: r.pop(k, None)
    return out

def load_sources() -> List[Dict[str, Any]]:
    with SOURCES_FILE.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return [s for s in data.get("sources", []) if s.get("enabled", True)]

def run(debug: bool = False) -> List[Dict[str, Any]]:
    OUTPUT_DIR.mkdir(exist_ok=True)
    sources = load_sources()
    by_domain, by_name = extract_meta_registry(sources)
    http = PatientHTTP(debug=debug)
    raw: List[RawJob] = []
    attempted = 0; successful = 0
    for src in sources:
        if http.expired(): break
        fetcher = FETCHERS.get(src.get("type"))
        if not fetcher: continue
        attempted += 1
        try:
            jobs = fetcher(http, src)
            if jobs:
                successful += 1; raw.extend(jobs)
        except Exception:
            # Do not poison output or show scary errors. GitHub logs stay clean unless debug is on.
            if debug:
                print(f"DEBUG failed source: {src.get('name')}", file=sys.stderr)
        time.sleep(float(src.get("post_source_delay", 0.05)) + random.uniform(0.01, 0.05))
    rows = []
    for j in raw:
        r = row_from_job(j, by_domain, by_name)
        if r: rows.append(r)
    final = dedupe(rows)
    final = sorted(final, key=lambda r: (-int(r["dsi_icp_score"]), r["days_old"], r["company"]))
    with FINAL_FILE.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FINAL_COLUMNS)
        writer.writeheader(); writer.writerows([{k: row.get(k, "") for k in FINAL_COLUMNS} for row in final])
    print("="*72)
    print("DSI V4 COMPLETE")
    print("="*72)
    print(f"Sources attempted       : {attempted}")
    print(f"Sources with raw jobs   : {successful}")
    print(f"Raw jobs collected      : {len(raw)}")
    print(f"Final strict ICP rows   : {len(final)}")
    print(f"Unique final sources    : {len(set(r['source'] for r in final)) if final else 0}")
    print(f"Output                  : {FINAL_FILE}")
    if len(final) == 0:
        print("WARNING: zero strict rows. This means today's public data did not prove headcount 10-200 + worldwide remote + fresh engineering role.")
    elif len(set(r['source'] for r in final)) < 10:
        print("WARNING: source diversity still low. Add more VERIFIED company career sources in sources.yml.")
    print("="*72)
    return final

def self_test() -> None:
    reject_locs = ["Remote, Germany", "Remote in Europe", "Remote US only", "United States", "Canada", "UK", "EMEA", "LATAM", "APAC", "Hybrid", "Onsite", "Remote (North America)", "North America", "Toronto, Canada", "Austin, TX", "Berlin", "Must be based in Spain", "Must reside in Canada"]
    for loc in reject_locs:
        restricted, ev = restriction_status("Senior Backend Engineer", loc, "")
        assert restricted, f"Should reject location: {loc}, got {ev}"
    reject_descs = ["Work authorization required", "Visa sponsorship not available", "Legally authorized to work in the US", "Candidates must be based in Germany"]
    for desc in reject_descs:
        restricted, ev = restriction_status("Senior Backend Engineer", "Remote", desc)
        assert restricted, f"Should reject desc: {desc}, got {ev}"
    accept_locs = ["Worldwide", "Remote Worldwide", "Anywhere", "Work from anywhere", "Anywhere in the world", "Global remote", "Open globally", "No location restriction", "Location independent", "Globally distributed"]
    for loc in accept_locs:
        restricted, _ = restriction_status("Senior Backend Engineer", loc, "")
        rc, ev = global_remote_status(loc, "")
        assert not restricted and rc == "proven_worldwide", f"Should accept strong global: {loc} got {rc} {ev}"
    weak_locs = ["Remote", "Fully remote", "Distributed", "Remote first", "Async"]
    for loc in weak_locs:
        rc, _ = global_remote_status(loc, "")
        assert rc == "weak_remote", f"Should be weak, not strict: {loc}"
    bad_titles = ["Customer Support Engineer", "Sales Engineer", "Engineering Manager", "Recruiter", "Intern"]
    for title in bad_titles:
        assert role_family(title) == "reject", f"Should reject title: {title}"
    good_titles = ["Senior Backend Engineer", "Full Stack Developer", "DevOps Engineer", "QA Automation Engineer", "Machine Learning Engineer"]
    for title in good_titles:
        assert role_family(title) != "reject", f"Should accept title: {title}"
    print("V4 self-test passed")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        self_test()
    else:
        run(debug=args.debug)
