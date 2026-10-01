from __future__ import annotations

from pathlib import Path

import pytest
from conftest import ROOT, make_job

from jobradar import cli
from jobradar.profile import load_profile
from jobradar.scoring import score
from jobradar.store import Store


@pytest.fixture
def db(tmp_path: Path) -> Path:
    path = tmp_path / "jobs.sqlite"
    store = Store(path)
    profile = load_profile(ROOT / "example" / "profile.yaml")
    job = make_job(job_id="42", description="Kafka, Java and Python distributed systems; 5+ years.", remote=True)
    store.upsert([(job, score(job, profile))], {"Acme"})
    store.close()
    return path


def run(db: Path, *args: str) -> int:
    return cli.main(["--db", str(db), "--profile", str(ROOT / "example" / "profile.yaml"), *args])


def test_top_tailor_status_and_report(db: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(db, "top", "-n", "5") == 0
    assert "greenhouse:Acme:42" in capsys.readouterr().out

    assert run(db, "tailor", "greenhouse:Acme:42", "--facts", str(ROOT / "example" / "factbank.yaml")) == 0
    out = capsys.readouterr().out
    assert "Senior Backend Engineer @ Acme" in out
    assert "- Built Kafka consumers" in out

    assert run(db, "status", "greenhouse:Acme:42", "applied") == 0
    assert Store(db).top()[0]["status"] == "applied"

    page = tmp_path / "site" / "index.html"
    assert run(db, "report", "--out", str(page)) == 0
    assert "Senior Backend Engineer" in page.read_text(encoding="utf-8")


def test_tailor_unknown_job_returns_error(db: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(db, "tailor", "greenhouse:Acme:missing") == 2
    assert "unknown job" in capsys.readouterr().err


def test_board_lists_merge_and_dedupe(tmp_path: Path) -> None:
    curated = tmp_path / "curated.yaml"
    curated.write_text("boards:\n  - {platform: greenhouse, slug: stripe, company: Stripe}\n", encoding="utf-8")
    found = tmp_path / "found.yaml"
    found.write_text("boards:\n  - {platform: greenhouse, slug: Stripe}\n  - {platform: lever, slug: acme}\n",
                     encoding="utf-8")
    boards = cli.load_boards(curated, found)
    assert [(b.platform, b.slug, b.company) for b in boards] == [("greenhouse", "stripe", "Stripe"),
                                                                ("lever", "acme", "acme")]
