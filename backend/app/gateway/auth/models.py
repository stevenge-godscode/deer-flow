"""User Pydantic models for authentication."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator


def _utc_now() -> datetime:
    """Return current UTC time (timezone-aware)."""
    return datetime.now(UTC)


class User(BaseModel):
    """Internal user representation."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(default_factory=uuid4, description="Primary key")
    email: EmailStr | None = Field(
        ...,
        description="Genuine email, optional for a verified OAuth-only ordinary account",
    )
    password_hash: str | None = Field(None, description="bcrypt hash, nullable for OAuth users")
    system_role: Literal["admin", "user"] = Field(default="user")
    created_at: datetime = Field(default_factory=_utc_now)

    # OAuth linkage (optional)
    oauth_provider: str | None = Field(None, description="e.g. 'github', 'google'")
    oauth_id: str | None = Field(None, description="User ID from OAuth provider")

    # Auth lifecycle
    needs_setup: bool = Field(default=False, description="True when a reset account must complete setup")
    token_version: int = Field(default=0, description="Incremented on password change to invalidate old JWTs")

    @model_validator(mode="after")
    def require_contact_or_oauth(self):
        if self.email is None and (not self.oauth_provider or not self.oauth_id or self.password_hash is not None or self.system_role != "user"):
            raise ValueError("Email-less accounts require an ordinary OAuth-only identity")
        return self


class UserResponse(BaseModel):
    """Response model for user info endpoint."""

    id: str
    email: str | None
    system_role: Literal["admin", "user"]
    needs_setup: bool = False
    oauth_provider: str | None = Field(
        None,
        description="OAuth/SSO provider ID if the user logged in via SSO (e.g. 'keycloak')",
    )
    permissions: list[str] | None = Field(
        None,
        description=("Effective route permissions granted to this credential (RFC #4063 Phase 4). Only GET /api/v1/auth/me resolves them; credential-creation responses leave it None."),
    )
