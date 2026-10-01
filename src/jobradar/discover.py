"""Discover company job boards at scale from the Common Crawl URL index.

Common Crawl publishes a CDX index of every URL it crawled. Querying it for
the hosted job-board domains of Greenhouse, Lever and Ashby yields thousands
of company board slugs, which are then validated against each platform's
public API (keeping only boards that currently have open roles).
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

import httpx

from jobradar.sources import ENDPOINTS, Board, Platform

log = logging.getLogger(__name__)

CDX_SERVER = "https://index.commoncrawl.org"

HOSTS: dict[str, Platform] = {
    "boards.greenhouse.io": "greenhouse",
    "job-boards.greenhouse.io": "greenhouse",
    "jobs.lever.co": "lever",
    "jobs.ashbyhq.com": "ashby",
}

# Path segments on these hosts that are not company boards
RESERVED = {"embed", "api", "v1", "static", "assets", "favicon.ico", "robots.txt", "sitemap.xml", "jobs", "search"}
_SLUG = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
RETRYABLE = {429, 500, 502, 503, 504}


def slug_from_url(url: str) -> tuple[Platform, str] | None:
    """'https://jobs.lever.co/acme/123?x=y' -> ('lever', 'acme')."""
    match = re.match(r"^https?://([^/]+)/([^/?#]+)", url.strip())
    if not match:
        return None
    host, segment = match.group(1).lower(), match.group(2).lower()
    platform = HOSTS.get(host)
    if platform is None or segment in RESERVED or not _SLUG.match(segment):
        return None
    return platform, segment


def _get_with_retry(client: httpx.Client, url: str, params: dict[str, Any], attempts: int = 4,
                    backoff_s: float = 2.0) -> httpx.Response:
    for attempt in range(attempts):
        try:
            response = client.get(url, params=params)
            if response.status_code not in RETRYABLE:
                response.raise_for_status()
                return response
        except httpx.TransportError:
            if attempt == attempts - 1:
                raise
        if attempt < attempts - 1:
            time.sleep(backoff_s * 2**attempt)
    response.raise_for_status()
    return response


def latest_crawl(client: httpx.Client) -> str:
    collections = _get_with_retry(client, f"{CDX_SERVER}/collinfo.json", {}).json()
    return str(collections[0]["id"])


def crawl_urls(client: httpx.Client, crawl: str, host: str, backoff_s: float = 2.0) -> Iterator[str]:
    """Yield every URL Common Crawl captured under `host`, page by page."""
    endpoint = f"{CDX_SERVER}/{crawl}-index"
    base = {"url": f"{host}/*", "output": "json"}
    meta = _get_with_retry(client, endpoint, {**base, "showNumPages": "true"}, backoff_s=backoff_s).json()
    pages = int(meta["pages"])
    for page in range(pages):
        yield from _page_urls(client, endpoint, {**base, "fl": "url", "page": str(page)}, backoff_s)


def _page_urls(client: httpx.Client, endpoint: str, params: dict[str, Any], backoff_s: float,
               attempts: int = 4) -> list[str]:
    """One CDX page as URLs. The index server sometimes answers 200 with an HTML error page;
    those are retried, and any stray malformed line is skipped rather than aborting the crawl."""
    for attempt in range(attempts):
        text = _get_with_retry(client, endpoint, params, backoff_s=backoff_s).text
        if text.lstrip().startswith("<"):
            log.warning("index returned an HTML page for %s (attempt %d)", params, attempt + 1)
            time.sleep(backoff_s * 2**attempt)
            continue
        urls = []
        for line in text.splitlines():
            try:
                urls.append(json.loads(line)["url"])
            except (ValueError, KeyError, TypeError):
                continue
        return urls
    log.warning("giving up on %s after %d attempts", params, attempts)
    return []


def candidate_boards(urls: Iterable[str]) -> set[tuple[Platform, str]]:
    found: set[tuple[Platform, str]] = set()
    for url in urls:
        parsed = slug_from_url(url)
        if parsed:
            found.add(parsed)
    return found


@dataclass(frozen=True)
class ValidatedBoard:
    board: Board
    open_roles: int


def _count_roles(platform: Platform, payload: Any) -> int:
    if platform == "lever":
        return len(payload) if isinstance(payload, list) else 0
    return len(payload.get("jobs", [])) if isinstance(payload, dict) else 0


def validate(
    client: httpx.Client, candidates: Iterable[tuple[Platform, str]], workers: int = 16
) -> list[ValidatedBoard]:
    """Keep boards whose public API responds with at least one open role."""

    def check(candidate: tuple[Platform, str]) -> ValidatedBoard | None:
        platform, slug = candidate
        try:
            response = _get_with_retry(client, ENDPOINTS[platform].format(slug=slug), {}, attempts=2, backoff_s=1.0)
            roles = _count_roles(platform, response.json())
        except (httpx.HTTPError, ValueError):
            return None
        return ValidatedBoard(Board(platform, slug, slug), roles) if roles else None

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = [r for r in pool.map(check, sorted(candidates)) if r]
    return sorted(results, key=lambda v: (-v.open_roles, v.board.platform, v.board.slug))


def discover(client: httpx.Client, crawl: str | None = None, hosts: Iterable[str] = HOSTS,
             limit: int | None = None) -> tuple[list[ValidatedBoard], dict[str, int]]:
    crawl = crawl or latest_crawl(client)
    stats: dict[str, int] = {}
    urls: list[str] = []
    for host in hosts:
        try:
            host_urls = list(crawl_urls(client, crawl, host))
        except httpx.HTTPError as exc:
            log.warning("skipping %s: %s", host, exc)
            host_urls = []
        stats[f"urls:{host}"] = len(host_urls)
        urls.extend(host_urls)
    candidates = sorted(candidate_boards(urls))
    stats["candidates"] = len(candidates)
    if limit is not None:
        candidates = candidates[:limit]
    boards = validate(client, candidates)
    stats["validated"] = len(boards)
    return boards, stats
