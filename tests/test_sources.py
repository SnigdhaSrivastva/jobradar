from __future__ import annotations

import httpx
import pytest
from conftest import fixture

from jobradar.sources import Board, fetch_all, html_to_text, parse_ashby, parse_greenhouse, parse_lever


def test_html_to_text_handles_double_escaped_greenhouse_markup() -> None:
    raw = "&lt;h2&gt;About&lt;/h2&gt;&lt;p&gt;We use &amp;amp; love &lt;strong&gt;Kafka&lt;/strong&gt;.&lt;/p&gt;"
    assert html_to_text(raw) == "About\n\nWe use & love Kafka."


def test_parse_greenhouse_real_payload() -> None:
    jobs = parse_greenhouse(fixture("greenhouse_stripe.json"), "Stripe")
    assert [j.title for j in jobs] == ["Abuse Research Engineer", "AI Engineer", "Android BSP Engineer"]
    job = jobs[0]
    assert job.key.startswith("greenhouse:Stripe:")
    assert job.url.startswith("https://")
    assert "<" not in job.description
    assert "&lt;" not in job.description
    assert job.posted_at is not None


def test_parse_lever_real_payload() -> None:
    jobs = parse_lever(fixture("lever_palantir.json"), "Palantir")
    assert len(jobs) == 3
    assert all(j.title.startswith("Backend Software Engineer") for j in jobs)
    assert all(j.posted_at is not None and j.posted_at.year >= 2020 for j in jobs)
    assert all(len(j.description) > 100 for j in jobs)


def test_parse_ashby_real_payload_with_salary_and_remote() -> None:
    jobs = parse_ashby(fixture("ashby_ramp.json"), "Ramp")
    titles = ["Security Engineer, Cloud", "Mobile Engineer, Android", "Software Engineer, Frontend"]
    assert [j.title for j in jobs] == titles
    assert any(j.salary for j in jobs)
    assert all(isinstance(j.remote, bool) for j in jobs)


def test_unlisted_ashby_jobs_are_skipped() -> None:
    data = fixture("ashby_ramp.json")
    data["jobs"][0]["isListed"] = False
    assert len(parse_ashby(data, "Ramp")) == 2


def test_fetch_all_isolates_failing_boards() -> None:
    payloads = {
        "boards-api.greenhouse.io": fixture("greenhouse_stripe.json"),
        "api.ashbyhq.com": fixture("ashby_ramp.json"),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.lever.co":
            return httpx.Response(503)
        return httpx.Response(200, json=payloads[request.url.host])

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = fetch_all(
        [
            Board("greenhouse", "stripe", "Stripe"),
            Board("lever", "palantir", "Palantir"),
            Board("ashby", "ramp", "Ramp"),
        ],
        client=client,
    )
    assert len(result.jobs) == 6
    assert list(result.errors) == ["lever:palantir"]
    assert "503" in result.errors["lever:palantir"]


@pytest.mark.parametrize("status", [404, 500])
def test_board_errors_are_reported_not_raised(status: int) -> None:
    client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(status)))
    result = fetch_all([Board("greenhouse", "nope", "Nope")], client=client)
    assert result.jobs == []
    assert "greenhouse:nope" in result.errors
