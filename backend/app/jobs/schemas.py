"""Pydantic request and response schemas for jobs (BE-25)."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

JobInputStatus = Literal["draft", "open"]
JobStatus = Literal["draft", "open", "deleted"]
SalaryType = Literal["hourly", "daily", "weekly", "monthly"]
JobSchedule = Literal["full_time", "part_time", "internship"]
JobUrgency = Literal["normal", "urgent", "hot"]
JobSortBy = Literal["newest", "nearest"]

JobTitle = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
JobDescription = Annotated[str, StringConstraints(strip_whitespace=True)]
JobLocation = Annotated[str, StringConstraints(strip_whitespace=True, max_length=150)]
Latitude = Annotated[float, Field(ge=-90.0, le=90.0, allow_inf_nan=False)]
Longitude = Annotated[float, Field(ge=-180.0, le=180.0, allow_inf_nan=False)]
SalaryAmount = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2, allow_inf_nan=False)]
SalaryCurrency = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$", max_length=3)]


class JobCreate(BaseModel):
    """Payload to create a job posting under the caller's active company."""

    title: JobTitle
    description: JobDescription
    latitude: Latitude
    longitude: Longitude
    location: JobLocation
    status: JobInputStatus = "draft"
    salary_amount: SalaryAmount | None = None
    salary_type: SalaryType = "monthly"
    salary_currency: SalaryCurrency | None = None
    schedule: JobSchedule = "full_time"
    urgency: JobUrgency = "normal"


class JobUpdate(BaseModel):
    """Partial update for an owned job; omitted fields stay unchanged."""

    # Reject unknown fields and explicit "deleted" transitions via PATCH.
    model_config = ConfigDict(extra="forbid")

    title: JobTitle = None
    description: JobDescription = None
    latitude: Latitude = None
    longitude: Longitude = None
    location: JobLocation = None
    status: JobInputStatus = None
    salary_amount: SalaryAmount | None = None
    salary_type: SalaryType = None
    salary_currency: SalaryCurrency | None = None
    schedule: JobSchedule = None
    urgency: JobUrgency = None


class JobOut(BaseModel):
    """Serialized job response including company name and owner-visible counters."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: int
    company_name: str | None = None
    company_logo_url: str | None = None
    title: str
    description: str
    status: JobStatus
    latitude: float
    longitude: float
    location: str
    salary_amount: Decimal | None = None
    salary_type: SalaryType
    salary_currency: str | None = None
    schedule: JobSchedule
    urgency: JobUrgency
    views_count: int = 0
    applications_count: int = 0
    new_applications_count: int = 0
    distance_km: float | None = None
    created_by_id: int | None = None
    updated_by_id: int | None = None
    created_at: datetime
    updated_at: datetime


class JobsPage(BaseModel):
    """Cursor-paginated public job search response (BE-26)."""

    items: list[JobOut]
    next_cursor: int | None
