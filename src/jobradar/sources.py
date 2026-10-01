"""Adapters for the official public job-board APIs of Greenhouse, Lever and Ashby.

All three publish read-only JSON endpoints for a company's open roles; no
authentication, no scraping, nothing is submitted.
"""

from __future__ import annotations

import html
import logging
import re
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

import httpx

log = logging.getLogger(__name__)

Platform = Literal["greenhouse", "lever", "ashby"]

ENDPOINTS: dict[Platform, str] = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true",
    "lever": "https://api.lever.co/v0/postings/{slug}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true",
}


@dataclass(frozen=True)
class Job:
    platform: Platform
    company: str
    job_id: str
    title: str
    location: str
    remote: bool
    url: str
    description: str
    posted_at: datetime | None
    salary: str | None = None

    @property
    def key(self) -> str:
        return f"{self.platform}:{self.company}:{self.job_id}"


@dataclass(frozen=True)
class Board:
    platform: Platform
    slug: str
    company: str


_TAG = re.compile(r"<[^>]+>")
_BLOCK = re.compile(r"</?(p|div|li|ul|ol|h[1-6]|br|tr)\b[^>]*>", re.IGNORECASE)


def html_to_text(raw: str) -> str:
    """Greenhouse double-escapes HTML; unescape until stable, keep block breaks, drop tags."""
    text = raw or ""
    for _ in range(3):
        unescaped = html.unescape(text)
        if unescaped == text:
            break
        text = unescaped
    text = _BLOCK.sub("\n", text)
    text = _TAG.sub("", text)
    text = re.sub(r"[^\S\n]+", " ", text)  # any whitespace except newlines, incl. NBSP
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _looks_remote(*parts: str | None) -> bool:
    return any(p and "remote" in p.lower() for p in parts)


def parse_greenhouse(data: dict[str, Any], company: str) -> list[Job]:
    jobs = []
    for j in data.get("jobs", []):
        location = (j.get("location") or {}).get("name") or ""
        jobs.append(Job(
            platform="greenhouse", company=company, job_id=str(j["id"]), title=j["title"].strip(),
            location=location, remote=_looks_remote(location), url=j["absolute_url"],
            description=html_to_text(j.get("content", "")),
            posted_at=_parse_iso(j.get("first_published") or j.get("updated_at")),
        ))
    return jobs


def parse_lever(data: list[dict[str, Any]], company: str) -> list[Job]:
    jobs = []
    for j in data:
        cats = j.get("categories") or {}
        location = cats.get("location") or ""
        sections = [j.get("descriptionPlain", "")]
        sections += [f"{s.get('text', '')}\n{html_to_text(s.get('content', ''))}" for s in j.get("lists", [])]
        sections.append(j.get("additionalPlain", ""))
        created = j.get("createdAt")
        jobs.append(Job(
            platform="lever", company=company, job_id=j["id"], title=j["text"].strip(), location=location,
            remote=j.get("workplaceType") == "remote" or _looks_remote(location), url=j["hostedUrl"],
            description="\n\n".join(s for s in sections if s).strip(),
            posted_at=datetime.fromtimestamp(created / 1000, tz=UTC) if created else None,
        ))
    return jobs


def parse_ashby(data: dict[str, Any], company: str) -> list[Job]:
    jobs = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        comp = j.get("compensation") or {}
        jobs.append(Job(
            platform="ashby", company=company, job_id=j["id"], title=j["title"].strip(),
            location=j.get("location") or "", remote=bool(j.get("isRemote")) or j.get("workplaceType") == "Remote",
            url=j["jobUrl"], description=j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml", "")),
            posted_at=_parse_iso(j.get("publishedAt")),
            salary=comp.get("scrapeableCompensationSalarySummary") or None,
        ))
    return jobs


PARSERS: dict[Platform, Callable[[Any, str], list[Job]]] = {
    "greenhouse": parse_greenhouse,
    "lever": parse_lever,
    "ashby": parse_ashby,
}


@dataclass
class FetchResult:
    jobs: list[Job]
    errors: dict[str, str]


RETRYABLE = {429, 500, 502, 503, 504}


def fetch_board(client: httpx.Client, board: Board, attempts: int = 3, backoff_s: float = 1.0) -> list[Job]:
    """Fetch one board, retrying rate limits and transient server errors with exponential backoff."""
    url = ENDPOINTS[board.platform].format(slug=board.slug)
    for attempt in range(attempts):
        try:
            response = client.get(url)
        except httpx.TransportError:
            if attempt == attempts - 1:
                raise
        else:
            if response.status_code not in RETRYABLE or attempt == attempts - 1:
                response.raise_for_status()
                return PARSERS[board.platform](response.json(), board.company)
        time.sleep(backoff_s * 2**attempt)
    raise RuntimeError("unreachable")


def fetch_all(boards: list[Board], client: httpx.Client | None = None, workers: int = 8) -> FetchResult:
    """Fetch boards concurrently. One failing board is reported, never fatal to the run."""
    client = client or httpx.Client(timeout=30.0, headers={"User-Agent": "jobradar (+https://github.com/SnigdhaSrivastva/jobradar)"})
    jobs: list[Job] = []
    errors: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch_board, client, b): b for b in boards}
        for future, board in futures.items():
            try:
                jobs.extend(future.result())
            except (httpx.HTTPError, KeyError, ValueError) as exc:
                errors[f"{board.platform}:{board.slug}"] = f"{type(exc).__name__}: {exc}"[:200]
                log.warning("board %s/%s failed: %s", board.platform, board.slug, exc)
    return FetchResult(jobs, errors)
