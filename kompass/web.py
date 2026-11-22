"""Polite HTTP helpers: timeouts, per-host rate limit, on-disk cache, readable text extraction."""
import hashlib
import json
import re
import time
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx
import yaml

from kompass.db import ROOT

CFG = yaml.safe_load((ROOT / "kompass" / "config.yaml").read_text())["http"]
CACHE = ROOT / "data" / "cache"
_last_hit: dict[str, float] = {}


class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer"}

    def __init__(self):
        super().__init__()
        self.parts, self._skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip and data.strip():
            self.parts.append(data.strip())


def html_to_text(html: str, max_chars: int = 6000) -> str:
    p = _Text()
    p.feed(html)
    return re.sub(r"\s+", " ", " ".join(p.parts))[:max_chars]


def get(url: str, *, as_json: bool = False, cache_hours: float = 24):
    """GET with cache + rate limit. Returns text/JSON, or None on any failure (caller decides)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    key = CACHE / (hashlib.sha1(url.encode()).hexdigest() + (".json" if as_json else ".txt"))
    if key.exists() and (time.time() - key.stat().st_mtime) < cache_hours * 3600:
        raw = key.read_text(encoding="utf-8")
        return json.loads(raw) if as_json else raw

    host = urlparse(url).netloc
    wait = CFG["min_seconds_between_requests_per_host"] - (time.time() - _last_hit.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    _last_hit[host] = time.time()
    try:
        r = httpx.get(url, timeout=CFG["timeout_seconds"], follow_redirects=True,
                      headers={"User-Agent": CFG["user_agent"]})
        if r.status_code != 200:
            return None
        key.write_text(r.text, encoding="utf-8")
        return r.json() if as_json else r.text
    except (httpx.HTTPError, ValueError):
        return None


def homepage_text(domain: str) -> tuple[str | None, str]:
    url = f"https://{domain}"
    html = get(url)
    return (html_to_text(html) if html else None), url
