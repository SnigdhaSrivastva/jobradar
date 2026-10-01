"""Explainable fit scoring: every point in the 0-100 score traces back to a reason."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from jobradar.profile import Profile, Skill
from jobradar.sources import Job

WEIGHTS = {"title": 30.0, "skills": 45.0, "seniority": 15.0, "location": 10.0}

_YEARS = re.compile(r"(\d{1,2})\s*(?:\+|plus)?\s*(?:-\s*\d{1,2}\s*)?(?:years?|yrs?)\b", re.IGNORECASE)


@dataclass
class FitScore:
    total: float
    parts: dict[str, float]
    matched_skills: list[str] = field(default_factory=list)
    missing_core: list[str] = field(default_factory=list)
    required_years: int | None = None
    reasons: list[str] = field(default_factory=list)
    excluded: str | None = None


def _mentions(text: str, term: str) -> bool:
    # Word-boundary match that also handles terms like "C++", "Node.js" or "CI/CD"
    pattern = r"(?<![\w+#.])" + re.escape(term.lower()) + r"(?![\w+#])"
    return re.search(pattern, text) is not None


def required_years(description: str) -> int | None:
    """Smallest 'N+ years' requirement mentioned, ignoring implausible values."""
    values = [int(m.group(1)) for m in _YEARS.finditer(description)]
    plausible = [v for v in values if 1 <= v <= 20]
    return min(plausible) if plausible else None


def skill_matches(job: Job, skills: list[Skill]) -> list[Skill]:
    text = f"{job.title}\n{job.description}".lower()
    return [s for s in skills if any(_mentions(text, t) for t in s.terms)]


def score(job: Job, profile: Profile) -> FitScore:
    title = job.title.lower()
    for avoid in profile.avoid_titles:
        if re.search(rf"\b{re.escape(avoid)}\b", title):  # whole words: "intern" must not match "internal"
            return FitScore(0.0, dict.fromkeys(WEIGHTS, 0.0), excluded=f"title contains '{avoid}'")

    parts: dict[str, float] = {}
    reasons: list[str] = []

    # Title: full credit if every word of a target title appears, partial for overlap
    best = 0.0
    for target in profile.target_titles:
        words = target.split()
        hit = sum(1 for w in words if re.search(rf"\b{re.escape(w)}\b", title)) / len(words)
        best = max(best, hit)
    parts["title"] = WEIGHTS["title"] * best
    reasons.append(f"title match {best:.0%}")

    # Skills: weighted share of the profile's skills that the posting mentions
    matched = skill_matches(job, profile.skills)
    total_weight = sum(s.weight for s in profile.skills)
    parts["skills"] = WEIGHTS["skills"] * sum(s.weight for s in matched) / total_weight
    missing_core = [s.name for s in profile.skills if s.core and s not in matched]
    reasons.append(f"{len(matched)}/{len(profile.skills)} skills mentioned")

    # Seniority: full credit when the requirement is within reach, tapering after that
    needed = required_years(job.description)
    if needed is None:
        parts["seniority"] = WEIGHTS["seniority"] * 0.7
        reasons.append("no years requirement stated")
    else:
        gap = needed - profile.years_experience
        fraction = 1.0 if gap <= 0 else max(0.0, 1.0 - gap / 3)
        parts["seniority"] = WEIGHTS["seniority"] * fraction
        reasons.append(f"asks {needed}+ yrs, have {profile.years_experience:g}")

    # Location: remote, or one of the preferred locations
    location = job.location.lower()
    if job.remote and profile.remote_ok:
        parts["location"] = WEIGHTS["location"]
        reasons.append("remote")
    elif any(loc in location for loc in profile.locations):
        parts["location"] = WEIGHTS["location"]
        reasons.append(f"location {job.location}")
    else:
        parts["location"] = 0.0
        reasons.append(f"location {job.location or 'unknown'} not preferred")

    return FitScore(
        total=round(sum(parts.values()), 1),
        parts={k: round(v, 1) for k, v in parts.items()},
        matched_skills=[s.name for s in matched],
        missing_core=missing_core,
        required_years=needed,
        reasons=reasons,
    )
