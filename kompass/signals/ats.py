"""Public ATS job-board readers. Parsers are pure functions so they can be tested on fixtures.

Each returns a list of postings: {id, title, location, url, description, posted_at}
"""
import re
import xml.etree.ElementTree as ET
from html import unescape
from datetime import datetime, timezone

from kompass import web

ENDPOINTS = {
    "personio":   "https://{slug}.jobs.personio.de/xml",
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true",
    "lever":      "https://api.lever.co/v0/postings/{slug}?mode=json",
    "ashby":      "https://api.ashbyhq.com/posting-api/job-board/{slug}",
}


def _strip(html: str | None) -> str:
    # Greenhouse returns HTML-escaped content, so unescape before stripping tags
    text = unescape(unescape(html or ""))
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()[:4000]


def parse_personio(xml_text: str, slug: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    out = []
    for p in root.iter("position"):
        pid = (p.findtext("id") or "").strip()
        desc = " ".join(_strip(v.text) for v in p.iter("value"))
        out.append({"id": pid, "title": (p.findtext("name") or "").strip(),
                    "location": (p.findtext("office") or "").strip(),
                    "url": f"https://{slug}.jobs.personio.de/job/{pid}",
                    "description": desc, "posted_at": p.findtext("createdAt")})
    return out


def parse_greenhouse(data: dict) -> list[dict]:
    return [{"id": str(j["id"]), "title": j.get("title", ""),
             "location": (j.get("location") or {}).get("name", ""),
             "url": j.get("absolute_url", ""), "description": _strip(j.get("content")),
             "posted_at": j.get("updated_at")} for j in data.get("jobs", [])]


def parse_lever(data: list) -> list[dict]:
    out = []
    for j in data:
        ts = j.get("createdAt")
        posted = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).isoformat() if ts else None
        out.append({"id": j["id"], "title": j.get("text", ""),
                    "location": (j.get("categories") or {}).get("location", ""),
                    "url": j.get("hostedUrl", ""), "description": (j.get("descriptionPlain") or "")[:4000],
                    "posted_at": posted})
    return out


def parse_ashby(data: dict) -> list[dict]:
    return [{"id": j["id"], "title": j.get("title", ""), "location": j.get("location", ""),
             "url": j.get("jobUrl", ""), "description": (j.get("descriptionPlain") or "")[:4000],
             "posted_at": j.get("publishedAt")} for j in data.get("jobs", [])]


def fetch(provider: str, slug: str) -> list[dict] | None:
    """Live fetch. Returns None if the board is unreachable (logged by caller, never fatal)."""
    url = ENDPOINTS[provider].format(slug=slug)
    if provider == "personio":
        raw = web.get(url, cache_hours=6)
        return parse_personio(raw, slug) if raw else None
    data = web.get(url, as_json=True, cache_hours=6)
    if data is None:
        return None
    return {"greenhouse": parse_greenhouse, "lever": parse_lever, "ashby": parse_ashby}[provider](data)


def detect(domain: str) -> tuple[str, str] | None:
    """Guess the ATS by trying the domain stem as slug on each provider."""
    stem = domain.split(".")[0].replace("-", "")
    for slug in dict.fromkeys([domain.split(".")[0], stem]):
        for provider in ENDPOINTS:
            jobs = fetch(provider, slug)
            if jobs:
                return provider, slug
    return None
