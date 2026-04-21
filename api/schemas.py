from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr


class ConfirmRequest(BaseModel):
    code: str


class ActivateRequest(BaseModel):
    setup_token: str
    password: str
    name: str = ""


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class UpdateUserRequest(BaseModel):
    name: str | None = None
    email: EmailStr | None = None
    password: str | None = None


class SetupTokenResponse(BaseModel):
    setup_token: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime


class UserResponse(BaseModel):
    id: str
    email: str
    name: str | None
    created_at: datetime


# ── Progress ──────────────────────────────────────────────────────────────────

class UserRefResponse(BaseModel):
    user_id: str
    name: str | None


class CreateProgressRequest(BaseModel):
    badge_slug: str
    level_index: int = Field(..., ge=0)
    step_index: int = Field(..., ge=0)
    notes: str | None = Field(None, max_length=10_000)


class UpdateProgressRequest(BaseModel):
    notes: str | None = Field(None, max_length=10_000)


class RequestSignoffRequest(BaseModel):
    mentor_email: EmailStr


class ProgressEntryResponse(BaseModel):
    id: str
    badge_slug: str
    level_index: int
    step_index: int
    notes: str | None
    status: str
    pending_mentors: list[UserRefResponse]
    signed_off_by: UserRefResponse | None
    signed_off_at: datetime | None
    created_at: datetime


class SignoffRequestResponse(BaseModel):
    id: str
    scout: UserRefResponse
    badge_slug: str
    level_index: int
    step_index: int
    notes: str | None
    status: str
    created_at: datetime


class MentorResponse(BaseModel):
    user_id: str
    name: str | None


# ── Groups ────────────────────────────────────────────────────────────────────

class CreateGroupRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    slug: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")


class UpdateGroupRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    slug: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")


class GroupResponse(BaseModel):
    id: str
    name: str
    slug: str
    created_at: str


class CreateSpeltakRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    slug: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")


class UpdateSpeltakRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    slug: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")


class SpeltakResponse(BaseModel):
    id: str
    group_id: str
    name: str
    slug: str


class SetMemberRoleRequest(BaseModel):
    user_id: str
    role: str = Field(..., pattern=r"^(groepsleider|member)$")


class SetSpeltakRoleRequest(BaseModel):
    user_id: str
    role: str = Field(..., pattern=r"^(speltakleider|scout)$")


class CreateEmaillessScoutRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)


class TransferScoutRequest(BaseModel):
    to_speltak_id: str
