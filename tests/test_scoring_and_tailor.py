from __future__ import annotations

import pytest
from conftest import make_job

from jobradar.profile import FactBank, Profile
from jobradar.scoring import WEIGHTS, required_years, score
from jobradar.tailor import tailor, verify_grounded

STRONG = """We build event-driven distributed systems in Java and Python with Kafka, Postgres and Redis
on AWS and Kubernetes. You have 5+ years of experience shipping backend services."""


def test_strong_match_scores_high_with_reasons(profile: Profile) -> None:
    fit = score(make_job("Senior Backend Engineer", STRONG, remote=True), profile)
    assert fit.total >= 80
    assert {"Java", "Python", "Kafka", "SQL", "Redis", "AWS", "Kubernetes"} <= set(fit.matched_skills)
    assert fit.missing_core == []
    assert fit.required_years == 5
    assert fit.total == pytest.approx(sum(fit.parts.values()), abs=0.2)
    assert all(fit.parts[k] <= WEIGHTS[k] for k in WEIGHTS)


def test_weak_match_scores_low_and_lists_missing_core_skills(profile: Profile) -> None:
    fit = score(make_job("Graphic Designer", "Figma and Illustrator.", location="Berlin"), profile)
    assert fit.total < 30
    assert set(fit.missing_core) == {"Java", "Python"}


@pytest.mark.parametrize("title", ["Software Engineering Intern", "Engineering Manager, Payments", "iOS Engineer"])
def test_avoided_titles_are_excluded(profile: Profile, title: str) -> None:
    fit = score(make_job(title, STRONG), profile)
    assert fit.total == 0
    assert fit.excluded


def test_avoid_list_matches_whole_words_only(profile: Profile) -> None:
    fit = score(make_job("Internal Tools Engineer", STRONG), profile)
    assert fit.excluded is None
    assert fit.total > 50


def test_seniority_tapers_when_requirement_exceeds_experience(profile: Profile) -> None:
    within = score(make_job(description="5+ years of experience"), profile).parts["seniority"]
    stretch = score(make_job(description="7+ years of experience"), profile).parts["seniority"]
    far = score(make_job(description="10+ years of experience"), profile).parts["seniority"]
    assert within > stretch > far == 0


@pytest.mark.parametrize(("text", "expected"), [
    ("5+ years of backend experience", 5),
    ("3-5 years in data engineering; 8 years preferred", 3),
    ("at least 4 yrs", 4),
    ("Founded 150 years ago, we value people", None),
    ("no requirement here", None),
])
def test_required_years(text: str, expected: int | None) -> None:
    assert required_years(text) == expected


def test_skill_terms_respect_word_boundaries(profile: Profile) -> None:
    fit = score(make_job(description="We use JavaScript and Sparkle and Dockerless deploys."), profile)
    assert "Java" not in fit.matched_skills
    assert "Spark" not in fit.matched_skills
    assert "Docker" not in fit.matched_skills


def test_aliases_count_as_matches(profile: Profile) -> None:
    fit = score(make_job(description="Experience with k8s, ETL and PostgreSQL."), profile)
    assert {"Kubernetes", "Data pipelines", "SQL"} <= set(fit.matched_skills)


def test_remote_or_preferred_location_scores_location(profile: Profile) -> None:
    assert score(make_job(location="Remote - US", remote=True), profile).parts["location"] == WEIGHTS["location"]
    assert score(make_job(location="New York, NY"), profile).parts["location"] == WEIGHTS["location"]
    assert score(make_job(location="Tokyo, Japan"), profile).parts["location"] == 0


def test_tailoring_selects_only_verified_bullets_ranked_by_relevance(profile: Profile, bank: FactBank) -> None:
    job = make_job(description="Kafka, Java and distributed systems at scale; Python and SQL pipelines.")
    resume = tailor(job, profile, bank, max_bullets=3)

    assert verify_grounded(resume, bank)
    assert resume.bullets[0].text.startswith("Built Kafka consumers")
    assert len(resume.bullets) == 3
    assert "kafka" in resume.emphasized_skills


def test_tailoring_reports_skills_no_bullet_evidences(profile: Profile) -> None:
    fact = {"text": "Wrote Python services for internal tooling.", "skills": ["Python"]}
    bank = FactBank.model_validate({"facts": [fact]})
    resume = tailor(make_job(description="Python and Kafka"), profile, bank)
    assert [f.text for f in resume.bullets] == ["Wrote Python services for internal tooling."]
    assert resume.uncovered_skills == ["kafka"]


def test_grounding_check_rejects_edited_bullets(profile: Profile, bank: FactBank) -> None:
    resume = tailor(make_job(description="Kafka and Java"), profile, bank)
    tampered = type(resume)(resume.job_key, [type(resume.bullets[0])(text="Invented Kafka.")],
                            resume.emphasized_skills, resume.uncovered_skills)
    assert not verify_grounded(tampered, bank)
