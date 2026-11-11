"""Pydantic request and response schemas for companies."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

_VALID_COUNTRY_CODES = {
    "AZ",
    "TR",
    "ID",
    "RU",
    "US",
    "GB",
    "DE",
    "FR",
    "AE",
    "SA",
    "KZ",
    "UA",
    "UZ",
    "GE",
    "AM",
    "BY",
    "TM",
    "KG",
    "TJ",
    "MD",
    "PL",
    "CZ",
    "RO",
    "HU",
    "RS",
    "HR",
    "BA",
    "ME",
    "MK",
    "AL",
    "CN",
    "JP",
    "KR",
    "IN",
    "PK",
    "BD",
    "PH",
    "VN",
    "TH",
    "MY",
    "BR",
    "AR",
    "MX",
    "CO",
    "PE",
    "CL",
    "VE",
    "EC",
    "BO",
    "PY",
    "EG",
    "MA",
    "NG",
    "ZA",
    "KE",
    "ET",
    "TZ",
    "GH",
    "SN",
    "CI",
}


class CompanyBase(BaseModel):
    name: str | None = Field(default=None, max_length=150)
    description: str | None = None
    country: str | None = Field(default=None, max_length=100)
    city: str | None = Field(default=None, max_length=100)
    district: str | None = Field(default=None, max_length=100)


class CompanyCreate(CompanyBase):
    name: str = Field(min_length=1, max_length=150)


class CompanyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=150)
    country: str = Field(min_length=1, max_length=100)
    city: str = Field(min_length=1, max_length=100)
    district: str | None = Field(default=None, max_length=100)
    country_code: str | None = Field(default=None, min_length=2, max_length=2)

    @field_validator("country_code")
    @classmethod
    def validate_country_code(cls, v: str | None) -> str | None:
        if v and v.upper() not in _VALID_COUNTRY_CODES:
            raise ValueError(f"Invalid ISO 3166-1 alpha-2 country code: {v!r}")
        return v.upper() if v else v


class CompanyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_user_id: int
    name: str
    description: str | None = None
    logo_object_key: str | None = None
    # Not a column (BE-08): the public address of the logo, for <img src>, or None without
    # one. service.to_company_out() fills it in from logo_object_key.
    logo_url: str | None = None
    status: str
    country: str | None = None
    city: str | None = None
    district: str | None = None
    country_code: str | None = None
    created_at: datetime
    updated_at: datetime
