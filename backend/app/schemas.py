"""Pydantic request/response schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class SearchFilters(BaseModel):
    document_ids: list[str] | None = None
    content_types: list[str] | None = None


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=10, ge=1, le=50)
    search_type: Literal["hybrid", "vector", "keyword"] = "hybrid"
    filters: SearchFilters | None = None
    rerank: bool = True


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=200)


class RegisterRequest(LoginRequest):
    kind: Literal["employer", "member"] = "member"
    workspace_name: str | None = Field(default=None, max_length=80)
    invite_code: str | None = Field(default=None, max_length=200)
    display_name: str | None = Field(default=None, max_length=80)


class CreateUserRequest(LoginRequest):
    role: Literal["viewer", "user", "admin"] = "user"
    display_name: str | None = Field(default=None, max_length=80)


class AdminUserUpdate(BaseModel):
    """Partial update from the admin panel: at least one field is required."""

    role: Literal["viewer", "user", "admin"] | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def _at_least_one(self) -> "AdminUserUpdate":
        if self.role is None and self.is_active is None:
            raise ValueError("Provide role, is_active, or both")
        return self


class PasswordResetRequest(BaseModel):
    """The recovery access token from the email fragment plus the new password."""

    access_token: str = Field(min_length=10, max_length=4000)
    password: str = Field(min_length=1, max_length=200)



class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_history: list[ChatMessage] = Field(default_factory=list)
    stream: bool = True
    language: Literal["en", "ar"] = "en"
    top_k: int = Field(default=10, ge=1, le=20)
    search_type: Literal["hybrid", "vector", "keyword"] = "hybrid"
    document_ids: list[str] | None = None
