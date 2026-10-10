"""Schema and validation helpers."""

from dataclasses import dataclass, field, asdict
from typing import List


@dataclass
class Person:
    id: str
    name: str
    company: str
    role: str
    skills: List[str] = field(default_factory=list)
    certifications: List[str] = field(default_factory=list)
    education: List[str] = field(default_factory=list)
    professional_experience: List[str] = field(default_factory=list)
    software: List[str] = field(default_factory=list)
    projects: List[str] = field(default_factory=list)
    profile_text: str = ""

    def build_profile_text(self) -> str:
        """Concatenate fields into a single string for embedding."""
        parts = [
            self.role,
            f"at {self.company}" if self.company else "",
            "Skills: " + ", ".join(self.skills) if self.skills else "",
            "Software: " + ", ".join(self.software) if self.software else "",
            "Certifications: " + ", ".join(self.certifications) if self.certifications else "",
            "Education: " + ", ".join(self.education) if self.education else "",
            "Professional Experience: " + ", ".join(self.professional_experience) if self.professional_experience else "",
            "Projects: " + ", ".join(self.projects) if self.projects else "",
        ]
        self.profile_text = ". ".join(p for p in parts if p)
        return self.profile_text

    def to_dict(self) -> dict:
        return asdict(self)


REQUIRED_FIELDS = ("id", "name", "company", "role")


def validate_record(record: dict) -> bool:
    """Validate that a record has the required non-empty string fields.

    Returns True if the record is a mapping containing all required
    fields with non-empty string values.
    """
    if not isinstance(record, dict):
        return False
    return all(
        isinstance(record.get(f), str) and record.get(f).strip()
        for f in REQUIRED_FIELDS
    )
