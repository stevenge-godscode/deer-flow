"""Published Agent directory and operator-approved identity access profiles."""

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator


class DirectoryProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=100)
    role: str = Field(pattern=r"^agent-directory-[a-z0-9-]+$")
    permission_ids: list[str] = Field(min_length=1, max_length=100)


class DirectoryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    root: str = ""
    origin: str = ""
    realm: str = ""
    provider: str = ""
    credential_file: str = ""
    manager_role: str = Field(default="agent-directory-manager", pattern=r"^agent-directory-[a-z0-9-]+$")
    profiles: dict[str, DirectoryProfile] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_scope(self):
        if self.enabled:
            url = httpx.URL(self.origin)
            if url.scheme != "https" or not url.host or url.path not in ("", "/") or url.query or url.username or url.password:
                raise ValueError("Directory identity origin must be an HTTPS origin")
            if not self.realm or "/" in self.realm or not self.provider or not self.credential_file or not self.profiles:
                raise ValueError("Directory requires an explicit realm, provider, credential and approved profiles")
            if self.manager_role in {p.role for p in self.profiles.values()}:
                raise ValueError("Manager role must be separate from assignable access profiles")
            if len({p.role for p in self.profiles.values()}) != len(self.profiles):
                raise ValueError("Directory profiles require distinct managed roles")
        return self
