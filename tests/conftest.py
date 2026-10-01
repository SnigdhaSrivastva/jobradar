from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from jobradar.profile import FactBank, Profile, load_fact_bank, load_profile
from jobradar.sources import Job

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def make_job(title: str = "Senior Backend Engineer", description: str = "", **kw: Any) -> Job:
    defaults: dict[str, Any] = {
        "platform": "greenhouse", "company": "Acme", "job_id": "1", "title": title, "location": "New York, NY",
        "remote": False, "url": "https://example.com/1", "description": description,
        "posted_at": datetime(2026, 9, 1, tzinfo=UTC),
    }
    defaults.update(kw)
    return Job(**defaults)


@pytest.fixture
def profile() -> Profile:
    return load_profile(ROOT / "example" / "profile.yaml")


@pytest.fixture
def bank() -> FactBank:
    return load_fact_bank(ROOT / "example" / "factbank.yaml")
