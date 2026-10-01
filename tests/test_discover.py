from __future__ import annotations

import json

import httpx
import pytest

from jobradar import discover as d


@pytest.mark.parametrize(("url", "expected"), [
    ("https://jobs.lever.co/acme/123?utm=x", ("lever", "acme")),
    ("https://boards.greenhouse.io/Stripe/jobs/42", ("greenhouse", "stripe")),
    ("https://job-boards.greenhouse.io/databricks", ("greenhouse", "databricks")),
    ("https://jobs.ashbyhq.com/ramp/abc/application", ("ashby", "ramp")),
    ("https://boards.greenhouse.io/embed/job_board?for=x", None),
    ("https://jobs.lever.co/", None),
    ("https://example.com/acme", None),
    ("https://jobs.lever.co/%E2%9C%93bad", None),
])
def test_slug_from_url(url: str, expected: tuple[str, str] | None) -> None:
    assert d.slug_from_url(url) == expected


def test_candidate_boards_dedupes_across_urls_and_hosts() -> None:
    urls = [
        "https://boards.greenhouse.io/acme/jobs/1",
        "https://job-boards.greenhouse.io/acme/jobs/2",
        "https://jobs.lever.co/acme",
        "https://jobs.lever.co/acme/9",
    ]
    assert d.candidate_boards(urls) == {("greenhouse", "acme"), ("lever", "acme")}


class FakeWeb:
    """Common Crawl CDX server (2 pages, one flaky) plus the three job-board APIs."""

    def __init__(self) -> None:
        self.cdx_calls = 0
        self.flaked = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        host, path, params = request.url.host, request.url.path, dict(request.url.params)
        if host == "index.commoncrawl.org":
            self.cdx_calls += 1
            if path == "/collinfo.json":
                return httpx.Response(200, json=[{"id": "CC-TEST-01"}, {"id": "CC-OLD"}])
            if params.get("showNumPages"):
                return httpx.Response(200, json={"pages": 2})
            if params.get("page") == "1" and not self.flaked:
                self.flaked = True
                return httpx.Response(503)
            urls = {
                ("jobs.lever.co/*", "0"): ["https://jobs.lever.co/alpha/1", "https://jobs.lever.co/ghost"],
                ("jobs.lever.co/*", "1"): ["https://jobs.lever.co/alpha/2", "https://jobs.lever.co/empty"],
                ("jobs.ashbyhq.com/*", "0"): ["https://jobs.ashbyhq.com/beta"],
                ("jobs.ashbyhq.com/*", "1"): [],
            }[(params["url"], params["page"])]
            return httpx.Response(200, text="\n".join(json.dumps({"url": u}) for u in urls))
        if host == "api.lever.co":
            slug = path.rsplit("/", 1)[-1]
            return {"alpha": httpx.Response(200, json=[{"id": "1"}, {"id": "2"}]),
                    "empty": httpx.Response(200, json=[])}.get(slug, httpx.Response(404))
        if host == "api.ashbyhq.com":
            return httpx.Response(200, json={"jobs": [{"id": "x"}]})
        return httpx.Response(404)


def test_discover_end_to_end_with_retries_and_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(d.time, "sleep", lambda _: None)
    web = FakeWeb()
    client = httpx.Client(transport=httpx.MockTransport(web.handler))

    boards, stats = d.discover(client, hosts=["jobs.lever.co", "jobs.ashbyhq.com"])

    found = [(b.board.platform, b.board.slug, b.open_roles) for b in boards]
    assert found == [("lever", "alpha", 2), ("ashby", "beta", 1)]
    assert stats["candidates"] == 4  # alpha, ghost, empty, beta
    assert stats["validated"] == 2  # ghost 404s, empty has no roles
    assert web.flaked, "the 503 on page 1 was retried"


def test_unreachable_host_is_skipped_not_fatal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(d.time, "sleep", lambda _: None)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "index.commoncrawl.org":
            return httpx.Response(504)
        return httpx.Response(404)

    boards, stats = d.discover(httpx.Client(transport=httpx.MockTransport(handler)), crawl="CC-X",
                               hosts=["jobs.lever.co"])
    assert boards == []
    assert stats["urls:jobs.lever.co"] == 0


def test_html_error_pages_are_retried_and_bad_lines_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(d.time, "sleep", lambda _: None)
    calls = {"page": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        if params.get("showNumPages"):
            return httpx.Response(200, json={"pages": 1})
        calls["page"] += 1
        if calls["page"] == 1:
            return httpx.Response(200, text="<html><body>504 Gateway Time-out</body></html>")
        good = json.dumps({"url": "https://jobs.lever.co/acme/1"})
        return httpx.Response(200, text=f'{good}\n{{"truncated": \n{json.dumps({"no_url": 1})}\n')

    urls = list(d.crawl_urls(httpx.Client(transport=httpx.MockTransport(handler)), "CC-X", "jobs.lever.co"))
    assert urls == ["https://jobs.lever.co/acme/1"]
    assert calls["page"] == 2
