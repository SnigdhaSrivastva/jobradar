"""Grounded resume tailoring: choose and order verified bullets for a posting. Nothing is generated."""

from __future__ import annotations

from dataclasses import dataclass

from jobradar.profile import Fact, FactBank, Profile
from jobradar.scoring import skill_matches
from jobradar.sources import Job


@dataclass(frozen=True)
class TailoredResume:
    job_key: str
    bullets: list[Fact]
    emphasized_skills: list[str]
    uncovered_skills: list[str]


def tailor(job: Job, profile: Profile, bank: FactBank, max_bullets: int = 6) -> TailoredResume:
    """Rank fact-bank bullets by how many of the posting's skills they evidence.

    Ties keep fact-bank order, so the result is deterministic. Because output
    bullets are the fact-bank objects themselves, the resume can't claim
    anything that isn't already verified.
    """
    wanted = {s.name.lower() for s in skill_matches(job, profile.skills)}

    def relevance(fact: Fact) -> int:
        return sum(1 for s in fact.skills if s.lower() in wanted)

    ranked = sorted(enumerate(bank.facts), key=lambda item: (-relevance(item[1]), item[0]))
    chosen = [fact for _, fact in ranked if relevance(fact) > 0][:max_bullets]

    covered = {s.lower() for f in chosen for s in f.skills}
    return TailoredResume(
        job_key=job.key,
        bullets=chosen,
        emphasized_skills=sorted(s for s in wanted if s in covered),
        uncovered_skills=sorted(wanted - covered),
    )


def verify_grounded(resume: TailoredResume, bank: FactBank) -> bool:
    """True when every bullet appears verbatim in the fact bank."""
    allowed = {f.text for f in bank.facts}
    return all(b.text in allowed for b in resume.bullets)
