"""SQLite store: dedupes postings across runs, tracks first/last seen, closures and application status."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jobradar.scoring import FitScore
from jobradar.sources import Job

STATUSES = ("new", "saved", "applied", "interviewing", "offer", "rejected", "skipped")

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    key         TEXT PRIMARY KEY,
    platform    TEXT NOT NULL,
    company     TEXT NOT NULL,
    title       TEXT NOT NULL,
    location    TEXT NOT NULL,
    remote      INTEGER NOT NULL,
    url         TEXT NOT NULL,
    salary      TEXT,
    posted_at   TEXT,
    description TEXT NOT NULL,
    score       REAL NOT NULL,
    score_json  TEXT NOT NULL,
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    active      INTEGER NOT NULL DEFAULT 1,
    status      TEXT NOT NULL DEFAULT 'new',
    status_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_score ON jobs (active, score DESC);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        self.db.close()

    def upsert(
        self, scored: list[tuple[Job, FitScore]], fetched_companies: set[str], now: str | None = None
    ) -> dict[str, int]:
        """Insert new postings, refresh existing ones, and close postings that vanished from a fetched board.

        Status is never overwritten by a refresh, so tracking survives daily runs.
        """
        now = now or _now()
        existing = {r["key"] for r in self.db.execute("SELECT key FROM jobs")}
        seen: set[str] = set()
        with self.db:
            for job, fit in scored:
                seen.add(job.key)
                self.db.execute(
                    """INSERT INTO jobs (key, platform, company, title, location, remote, url, salary, posted_at,
                                         description, score, score_json, first_seen, last_seen, active)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                       ON CONFLICT (key) DO UPDATE SET
                         title = excluded.title, location = excluded.location, remote = excluded.remote,
                         url = excluded.url, salary = excluded.salary, description = excluded.description,
                         score = excluded.score, score_json = excluded.score_json,
                         last_seen = excluded.last_seen, active = 1""",
                    (job.key, job.platform, job.company, job.title, job.location, int(job.remote), job.url,
                     job.salary, job.posted_at.isoformat() if job.posted_at else None, job.description,
                     fit.total, json.dumps(asdict(fit)), now, now),
                )
            closed = 0
            for company in fetched_companies:
                cur = self.db.execute(
                    "UPDATE jobs SET active = 0 WHERE company = ? AND active = 1 AND last_seen < ?", (company, now)
                )
                closed += cur.rowcount
        return {"new": len(seen - existing), "updated": len(seen & existing), "closed": closed}

    def set_status(self, key: str, status: str) -> None:
        if status not in STATUSES:
            raise ValueError(f"status must be one of {', '.join(STATUSES)}")
        with self.db:
            cur = self.db.execute("UPDATE jobs SET status = ?, status_at = ? WHERE key = ?", (status, _now(), key))
        if cur.rowcount == 0:
            raise KeyError(key)

    def top(self, min_score: float = 0, limit: int = 200) -> list[dict[str, Any]]:
        rows = self.db.execute(
            """SELECT key, platform, company, title, location, remote, url, salary, posted_at, score, score_json,
                      first_seen, status
               FROM jobs WHERE active = 1 AND score >= ? ORDER BY score DESC, first_seen DESC LIMIT ?""",
            (min_score, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def get(self, key: str) -> sqlite3.Row | None:
        row: sqlite3.Row | None = self.db.execute("SELECT * FROM jobs WHERE key = ?", (key,)).fetchone()
        return row

    def counts(self) -> dict[str, int]:
        row = self.db.execute(
            "SELECT COUNT(*) AS total, SUM(active) AS active, COUNT(DISTINCT company) AS companies FROM jobs"
        ).fetchone()
        return {k: int(row[k] or 0) for k in ("total", "active", "companies")}
