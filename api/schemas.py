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
    peer_signoff: bool = False


class UpdateSpeltakRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    slug: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")
    peer_signoff: bool = False


class SpeltakResponse(BaseModel):
    id: str
    group_id: str
    name: str
    slug: str
    peer_signoff: bool


class GroupMembershipResponse(BaseModel):
    user_id: str
    role: str
    approved: bool
    withdrawn: bool
    invited_by_id: str | None


class SpeltakMembershipResponse(BaseModel):
    user_id: str
    role: str
    approved: bool
    withdrawn: bool
    invited_by_id: str | None


class GroupInvitationResponse(BaseModel):
    group_id: str
    group_name: str
    role: str
    withdrawn: bool
    invited_by_id: str | None


class SpeltakInvitationResponse(BaseModel):
    speltak_id: str
    speltak_name: str
    group_id: str
    group_name: str
    role: str
    withdrawn: bool
    invited_by_id: str | None
    source_scout_id: str | None = None
    scout_has_progress: bool = False


class InvitationListResponse(BaseModel):
    group_invites: list[GroupInvitationResponse]
    speltak_invites: list[SpeltakInvitationResponse]


class AttachEmailRequest(BaseModel):
    email: EmailStr


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


class CreateMembershipRequestRequest(BaseModel):
    speltak_id: str | None = None


class MembershipRequestResponse(BaseModel):
    id: str
    user_id: str
    group_id: str
    speltak_id: str | None
    status: str
    reviewed_by_id: str | None
    created_at: datetime


class UserGroupMembershipResponse(BaseModel):
    group_id: str
    role: str
    approved: bool
    withdrawn: bool


class UserSpeltakMembershipResponse(BaseModel):
    speltak_id: str
    group_id: str
    role: str
    approved: bool
    withdrawn: bool


class ActiveMembershipsResponse(BaseModel):
    group_memberships: list[UserGroupMembershipResponse]
    speltak_memberships: list[UserSpeltakMembershipResponse]


# ── Leider progress management ────────────────────────────────────────────────

class SetScoutProgressRequest(BaseModel):
    badge_slug: str
    level_index: int = Field(..., ge=0)
    step_index: int = Field(..., ge=0)
    status: str = Field(..., pattern=r"^(none|in_progress|work_done|signed_off)$")
    message: str = ""


class ToggleFavoriteBadgeRequest(BaseModel):
    badge_slug: str


class ToggleFavoriteBadgeResponse(BaseModel):
    badge_slug: str
    is_favorite: bool


class RequestSignoffSpeltakRequest(BaseModel):
    speltak_id: str


class RequestSignoffMembersRequest(BaseModel):
    mentor_ids: list[str]


class EmailChangeTokenRequest(BaseModel):
    token: str


class PendingEmailChangeResponse(BaseModel):
    new_email: str
    expires_at: datetime


class ContactCaptchaResponse(BaseModel):
    token: str
    a: int
    b: int


class ContactRequest(BaseModel):
    subject: str = Field(..., min_length=1, max_length=200)
    body: str = Field(..., min_length=1)
    sender_email: EmailStr | None = None
    captcha_token: str | None = None
    captcha_answer: int | None = None


class AdminUserResponse(BaseModel):
    id: str
    email: str | None
    name: str | None
    status: str


class AdminDashboardStats(BaseModel):
    total_users: int
    users_by_group: list[dict]
    users_by_status: list[dict]
    users_over_time: list[dict]
    signoff_over_time: list[dict]
    badges_over_time: list[dict]
