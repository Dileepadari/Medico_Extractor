"""Request/response contracts.

`ExtractedReferralData` doubles as the schema handed to the model for structured
output, so every field description is written as an instruction to the model *and*
as user-facing API documentation.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class PatientDemographics(BaseModel):
    name: str = Field(default="", description="Patient's full name. Empty if not found.")
    dob: str = Field(default="", description="Patient's date of birth. Empty if not found.")
    phone: str = Field(default="", description="Patient's phone number. Empty if not found.")
    email: str = Field(default="", description="Patient's email address. Empty if not found.")


class PrimaryInsurance(BaseModel):
    member_id: str = Field(default="", description="Primary insurance member ID. Empty if not found.")
    group_id: str = Field(default="", description="Primary insurance group ID. Empty if not found.")
    insurance_name: str = Field(default="", description="Primary insurance provider name. Empty if not found.")
    plan_name: str = Field(default="", description="Primary insurance plan name. Empty if not found.")


class SecondaryInsurance(BaseModel):
    member_id: str = Field(default="", description="Secondary insurance member ID. Empty if not found.")
    group_id: str = Field(default="", description="Secondary insurance group ID. Empty if not found.")


class ReferralSource(BaseModel):
    provider_name: str = Field(default="", description="Referring provider or doctor name. Empty if not found.")
    clinic_name: str = Field(default="", description="Referring clinic or hospital name. Empty if not found.")
    title: str = Field(default="", description="Referring provider's title (MD, DO, NP, ...). Empty if not found.")
    phone: str = Field(default="", description="Referring clinic or provider phone number. Empty if not found.")


class ReferralReceivedDate(BaseModel):
    date: str = Field(default="", description="Date the referral was received, created or faxed. Empty if not found.")


class ExtractedReferralData(BaseModel):
    """The structured payload returned by `POST /api/v1/extract`."""

    patient_demographics: PatientDemographics = Field(default_factory=PatientDemographics)
    primary_insurance: PrimaryInsurance = Field(default_factory=PrimaryInsurance)
    secondary_insurance: SecondaryInsurance = Field(default_factory=SecondaryInsurance)
    referral_source: ReferralSource = Field(default_factory=ReferralSource)
    referral_received_date: ReferralReceivedDate = Field(default_factory=ReferralReceivedDate)


class ExtractionMeta(BaseModel):
    """Non-PHI details about how the extraction ran, useful for debugging a request."""

    request_id: str
    filename: str
    content_type: str
    size_bytes: int
    model: str
    duration_ms: int


class ExtractionResponse(BaseModel):
    data: ExtractedReferralData
    meta: ExtractionMeta


class ErrorDetail(BaseModel):
    code: str = Field(description="Stable, machine-readable error code.")
    message: str = Field(description="Human-readable description of what went wrong.")
    request_id: str | None = Field(default=None, description="Correlates with server logs.")


class ErrorResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "error": {
                "code": "file_too_large",
                "message": "File exceeds the 10 MiB limit.",
                "request_id": "0f9a1c2e4b7d4a1e",
            }
        }
    })

    error: ErrorDetail


class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str


class ReadinessResponse(BaseModel):
    status: str
    version: str
    environment: str
    checks: dict[str, str]
