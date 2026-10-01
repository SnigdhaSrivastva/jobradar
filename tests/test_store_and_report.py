from __future__ import annotations

import json

import pytest
from conftest import make_job

from jobradar.profile import Profile
from jobradar.report import render
from jobradar.scoring import score
from jobradar.store import Store


@pytest.fixture
def store() -> Store:
    return Store()


def scored(profile: Profile, *jobs):  # type: ignore[no-untyped-def]
    return [(j, score(j, profile)) for j in jobs]


def test_upsert_is_idempotent_and_tracks_new_vs_updated(store: Store, profile: Profile) -> None:
    jobs = [make_job(job_id="1"), make_job(job_id="2", title="Data Engineer")]
    first = store.upsert(scored(profile, *jobs), {"Acme"}, now="2026-09-01T00:00:00+00:00")
    second = store.upsert(scored(profile, *jobs), {"Acme"}, now="2026-09-02T00:00:00+00:00")

    assert first == {"new": 2, "updated": 0, "closed": 0}
    assert second == {"new": 0, "updated": 2, "closed": 0}
    assert store.counts() == {"total": 2, "active": 2, "companies": 1}


def test_postings_missing_from_a_fetched_board_are_closed(store: Store, profile: Profile) -> None:
    store.upsert(scored(profile, make_job(job_id="1"), make_job(job_id="2")), {"Acme"}, now="2026-09-01T00:00:00+00:00")
    summary = store.upsert(scored(profile, make_job(job_id="1")), {"Acme"}, now="2026-09-02T00:00:00+00:00")

    assert summary["closed"] == 1
    assert [r["key"] for r in store.top()] == ["greenhouse:Acme:1"]


def test_boards_that_failed_to_fetch_do_not_close_their_jobs(store: Store, profile: Profile) -> None:
    store.upsert(scored(profile, make_job(job_id="1", company="Down")), {"Down"}, now="2026-09-01T00:00:00+00:00")
    summary = store.upsert([], set(), now="2026-09-02T00:00:00+00:00")
    assert summary["closed"] == 0
    assert store.counts()["active"] == 1


def test_status_survives_refreshes(store: Store, profile: Profile) -> None:
    job = make_job(job_id="1")
    store.upsert(scored(profile, job), {"Acme"})
    store.set_status(job.key, "applied")
    store.upsert(scored(profile, job), {"Acme"})
    assert store.top()[0]["status"] == "applied"


def test_invalid_status_or_unknown_job_is_rejected(store: Store) -> None:
    with pytest.raises(ValueError, match="status must be one of"):
        store.set_status("x", "hired-instantly")
    with pytest.raises(KeyError):
        store.set_status("greenhouse:Acme:404", "applied")


def test_top_orders_by_score(store: Store, profile: Profile) -> None:
    store.upsert(scored(profile,
                        make_job(job_id="weak", title="Graphic Designer", description="Figma"),
                        make_job(job_id="strong", description="Java Python Kafka distributed systems AWS",
                                 remote=True)),
                 {"Acme"})
    rows = store.top()
    assert [r["key"].split(":")[-1] for r in rows] == ["strong", "weak"]
    assert rows[0]["score"] > rows[1]["score"]


def test_report_embeds_data_safely(store: Store, profile: Profile) -> None:
    store.upsert(scored(profile, make_job(job_id="1", title="Backend </script><script>alert(1)</script> Engineer")),
                 {"Acme"})
    page = render(store.top(), store.counts(), errors={"lever:x": "HTTPError"})

    data = page.split('<script id="data" type="application/json">', 1)[1].split("</script>", 1)[0]
    assert "</script>" not in data
    assert json.loads(data)[0]["title"].startswith("Backend </script>")
    assert "boards unavailable" in page


def test_report_marks_roles_first_seen_in_the_last_day(store: Store, profile: Profile) -> None:
    from datetime import UTC, datetime
    store.upsert(scored(profile, make_job(job_id="old")), {"Acme"}, now="2026-09-01T00:00:00+00:00")
    store.upsert(scored(profile, make_job(job_id="old"), make_job(job_id="fresh")), {"Acme"},
                 now="2026-09-10T00:00:00+00:00")
    page = render(store.top(), store.counts(), now=datetime(2026, 9, 10, 1, tzinfo=UTC))
    data = json.loads(page.split('<script id="data" type="application/json">', 1)[1].split("</script>", 1)[0])
    assert sorted(j["new"] for j in data) == [False, True]  # "fresh" is new, "old" is not
    assert "new in the last 24h" in page
