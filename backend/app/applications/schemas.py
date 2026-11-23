"""Pydantic request and response schemas for job applications (BE-28)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.applications.constants import COVER_NOTE_MAX_LENGTH, STATUS_NOTE_MAX_LENGTH

ApplicationStatus = Literal[
    "submitted",
    "viewed",
    "shortlisted",
    "rejected",
    "contacted",
    "hired",
    "withdrawn",
]


class ApplyRequest(BaseModel):
    """Optional cover note sent when applying to an open job."""

    model_config = ConfigDict(extra="forbid")

    cover_note: str | None = Field(default=None, max_length=COVER_NOTE_MAX_LENGTH)

    @field_validator("cover_note")
    @classmethod
    def _normalize_cover_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class StatusUpdateRequest(BaseModel):
    """Employer status transition request with an optional audit note."""

    model_config = ConfigDict(extra="forbid")

    status: ApplicationStatus
    note: str | None = Field(default=None, max_length=STATUS_NOTE_MAX_LENGTH)

    @field_validator("note")
    @classmethod
    def _normalize_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class ApplicationOut(BaseModel):
    """Serialized application with joined job, company, applicant, and video metadata."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int
    applicant_id: int
    company_id: int
    intro_video_id: int | None
    status: ApplicationStatus
    cover_note: str | None
    conversation_id: int | None
    applied_at: datetime
    updated_at: datetime
    viewed_at: datetime | None
    job_title: str | None = None
    company_name: str | None = None
    applicant_first_name: str | None = None
    applicant_last_name: str | None = None
    applicant_position: str | None = None
    applicant_avatar_url: str | None = None
    intro_video_url: str | None = None


class ApplicationsPage(BaseModel):
    """Cursor-paginated list of applications."""

    items: list[ApplicationOut]
    next_cursor: int | None
