"""Candidate profile and fact bank, loaded from YAML."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator


class Skill(BaseModel):
    name: str
    weight: float = Field(default=1.0, gt=0, le=5)
    aliases: list[str] = []
    core: bool = False

    @property
    def terms(self) -> list[str]:
        return [self.name, *self.aliases]


class Profile(BaseModel):
    target_titles: list[str] = Field(min_length=1)
    avoid_titles: list[str] = []
    skills: list[Skill] = Field(min_length=1)
    years_experience: float = Field(ge=0)
    locations: list[str] = []
    remote_ok: bool = True

    @field_validator("target_titles", "avoid_titles", "locations")
    @classmethod
    def lower(cls, values: list[str]) -> list[str]:
        return [v.strip().lower() for v in values if v.strip()]


class Fact(BaseModel):
    """One verified, pre-written resume bullet. Tailoring only ever selects these, never rewrites them."""

    text: str = Field(min_length=10)
    skills: list[str] = []
    role: str = ""


class FactBank(BaseModel):
    facts: list[Fact] = Field(min_length=1)


def load_profile(path: str | Path) -> Profile:
    return Profile.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))


def load_fact_bank(path: str | Path) -> FactBank:
    return FactBank.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))
