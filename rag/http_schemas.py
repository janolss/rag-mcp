"""Pydantic request/response schemas for /api/v1."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ErrorBody(BaseModel):
    error: str
    code: str = "error"


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    workspace_id: str | None = None
    source_ids: list[str] | None = None
    document_types: list[str] | None = None
    limit: int | None = Field(default=None, ge=1, le=50)
    scope: str = "workspace"
    search_mode: str = "semantic"
    path_prefix: str | None = None


class SearchResponse(BaseModel):
    hits: list[dict[str, Any]]


class DocumentQuery(BaseModel):
    workspace_id: str | None = None
    source_id: str
    document_id: str
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
