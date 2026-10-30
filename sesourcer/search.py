"""Search public web indexes for LinkedIn profile pages.

LinkedIn blocks automated reads of its own site. This module never requests
linkedin.com. It reads result pages from public search engines, which already
list profile titles, snippets, and URLs, and it slows down when an index asks
it to.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlencode, urlparse

import httpx

from sesourcer.clean import decode_text
from sesourcer.profiles import canonical_profile_url

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
_CACHE_PATH = Path(os.environ.get("SESOURCER_CACHE", "/tmp/sesourcer-search-cache.json"))
_LOCK = threading.Lock()
_SUCCESS_TTL = 6 * 60 * 60


class SearchBlocked(Exception):
    """The public index refused the query (rate limit or a browser check)."""


class SearchError(Exception):
    """The public index could not be read."""


@dataclass
class SearchHit:
    title: str
    url: str
    snippet: str


def gather(queries: list[str], limit: int, sleep=time.sleep) -> tuple[list[SearchHit], list[str]]:
    """Run as few queries as needed and merge unique profile URLs."""
    warnings: list[str] = []
    found: dict[str, SearchHit] = {}
    providers = [("duckduckgo", fetch_duckduckgo), ("bing", fetch_bing)]
    provider_index = 0
    calls = 0
    max_calls = 6 if limit >= 15 else 4 if limit >= 8 else 3
    target = min(50, max(limit, int(limit * 1.4)))
    delay = float(os.environ.get("SESOURCER_SEARCH_DELAY", "3.0"))

    for query in queries:
        if len(found) >= target or calls >= max_calls:
            break
        if calls:
            sleep(delay)
        calls += 1
        hits, provider_index, stop = _fetch_with_backoff(
            query, providers, provider_index, warnings, sleep
        )
        if stop and not found:
            break
        if stop:
            warnings.append("Stopped early after the index rate-limited further searches.")
            break
        added = 0
        for hit in hits:
            key = canonical_profile_url(hit.url)
            if not key:
                continue
            previous = found.get(key)
            if previous is None or len(hit.snippet) > len(previous.snippet):
                found[key] = SearchHit(title=hit.title, url=key, snippet=hit.snippet)
                if previous is None:
                    added += 1
        if added == 0 and hits == []:
            continue
    if not found and not warnings:
        warnings.append("The public index returned no LinkedIn profile pages for these searches.")
    return list(found.values()), warnings


def fetch_duckduckgo(query: str) -> list[SearchHit]:
    url = "https://html.duckduckgo.com/html/?" + urlencode({"q": query})
    html = _get(url)
    if "anomaly.js" in html or 'id="challenge-form"' in html:
        raise SearchBlocked("DuckDuckGo asked for a browser check. Waiting before another search.")
    return parse_duckduckgo_html(html)


def fetch_bing(query: str) -> list[SearchHit]:
    url = "https://www.bing.com/search?" + urlencode({"format": "rss", "count": "10", "q": query})
    body = _get(url, accept="application/rss+xml, application/xml, text/xml, */*")
    if "captcha" in body.lower() or "unusual traffic" in body.lower():
        raise SearchBlocked("Bing asked for a browser check.")
    hits = parse_bing_rss(body)
    # A degraded response drops the site: operator and returns unrelated pages.
    if "<item>" in body.lower() and not hits:
        raise SearchBlocked("Bing did not return profile pages for this search.")
    return hits


def _fetch_with_backoff(query, providers, provider_index, warnings, sleep):
    """Try the current index, wait and retry once, then move to the backup."""
    attempts = 0
    while attempts < 4:
        attempts += 1
        name, fetch = providers[provider_index]
        try:
            return _cached_fetch(name, fetch, query), provider_index, False
        except SearchBlocked:
            if attempts == 1:
                warnings.append("A public index rate-limited the search. Waiting, then retrying.")
                sleep(8)
                continue
            if provider_index + 1 < len(providers):
                provider_index += 1
                warnings.append("The first public index rate-limited the search, so a backup index was used.")
                continue
            warnings.append("Public indexes are rate-limiting searches. Wait a minute and try again.")
            return [], provider_index, True
        except SearchError as exc:
            warnings.append(str(exc))
            return [], provider_index, False
    warnings.append("Public indexes are rate-limiting searches. Wait a minute and try again.")
    return [], provider_index, True


def parse_duckduckgo_html(html: str) -> list[SearchHit]:
    hits: list[SearchHit] = []
    seen: set[str] = set()
    anchors = list(
        re.finditer(
            r'<a\b[^>]*class="[^"]*result__a[^"]*"[^>]*>.*?</a>',
            html,
            flags=re.IGNORECASE | re.DOTALL,
        )
    )
    for index, anchor in enumerate(anchors):
        tag = anchor.group(0)
        href = _attr(tag, "href")
        title = decode_text(re.sub(r"^<a\b[^>]*>", "", tag, flags=re.I).rsplit("</a>", 1)[0])
        target = _duckduckgo_target(href)
        url = canonical_profile_url(target) if target else None
        if not url or url in seen:
            continue
        window_end = anchors[index + 1].start() if index + 1 < len(anchors) else anchor.end() + 2500
        window = html[anchor.end(): window_end]
        snippet_match = re.search(
            r'class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>',
            window,
            flags=re.IGNORECASE | re.DOTALL,
        )
        snippet = decode_text(snippet_match.group(1)) if snippet_match else ""
        seen.add(url)
        hits.append(SearchHit(title=title, url=url, snippet=snippet))
    return hits


def parse_bing_rss(xml: str) -> list[SearchHit]:
    hits: list[SearchHit] = []
    seen: set[str] = set()
    for item in re.findall(r"<item>(.*?)</item>", xml, flags=re.DOTALL | re.IGNORECASE):
        link = _xml_tag(item, "link")
        url = canonical_profile_url(link)
        if not url or url in seen:
            continue
        seen.add(url)
        hits.append(
            SearchHit(
                title=decode_text(_xml_tag(item, "title")),
                url=url,
                snippet=decode_text(_xml_tag(item, "description")),
            )
        )
    return hits


def _duckduckgo_target(href: str) -> str:
    if not href:
        return ""
    href = href.replace("&amp;", "&")
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    query = parse_qs(parsed.query)
    if "uddg" in query and query["uddg"]:
        return unquote(query["uddg"][0])
    if "linkedin.com/in/" in href:
        return href
    return ""


def _attr(tag: str, name: str) -> str:
    match = re.search(rf'{name}="([^"]*)"', tag, flags=re.IGNORECASE)
    return match.group(1) if match else ""


def _xml_tag(item: str, name: str) -> str:
    match = re.search(rf"<{name}>(.*?)</{name}>", item, flags=re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else ""


def _get(url: str, accept: str = "text/html") -> str:
    headers = {
        "User-Agent": _USER_AGENT,
        "Accept": accept,
        "Accept-Language": "en-GB,en;q=0.9",
    }
    try:
        with httpx.Client(timeout=15, follow_redirects=True) as client:
            response = client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        raise SearchError("The public index did not respond.") from exc
    if response.status_code in {202, 429, 403}:
        raise SearchBlocked("The public index rate-limited this search.")
    if response.status_code >= 400:
        raise SearchError(f"The public index returned HTTP {response.status_code}.")
    return response.text


def _cached_fetch(provider: str, fetch, query: str) -> list[SearchHit]:
    if os.environ.get("SESOURCER_NO_CACHE") == "1":
        return fetch(query)
    cached = _cache_get(provider, query)
    if cached is not None:
        return cached
    hits = fetch(query)
    if hits:
        _cache_put(provider, query, hits, _SUCCESS_TTL)
    return hits


def _cache_get(provider: str, query: str) -> list[SearchHit] | None:
    data = _read_cache()
    row = data.get(_key(provider, query))
    if not row:
        return None
    if time.time() - row.get("t", 0) > row.get("ttl", 0):
        return None
    return [SearchHit(**hit) for hit in row.get("hits", [])]


def _cache_put(provider: str, query: str, hits: list[SearchHit], ttl: int) -> None:
    with _LOCK:
        data = _read_cache()
        if len(data) > 200:
            oldest = sorted(data.items(), key=lambda item: item[1].get("t", 0))[:50]
            for key, _row in oldest:
                data.pop(key, None)
        data[_key(provider, query)] = {
            "t": time.time(),
            "ttl": ttl,
            "hits": [asdict(hit) for hit in hits],
        }
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_PATH.write_text(json.dumps(data), encoding="utf-8")


def _read_cache() -> dict:
    if not _CACHE_PATH.exists():
        return {}
    try:
        return json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _key(provider: str, query: str) -> str:
    return provider + "\n" + query
