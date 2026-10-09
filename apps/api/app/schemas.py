from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    filename: str = Field(min_length=1, max_length=300)
    content_type: str
    size_bytes: int = Field(gt=0)


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: str
    status: str
    stage: str
    progress: float
    error: str | None
    cost_usd: float


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    filename: str
    status: str
    duration_ms: int | None
    fps: str | None
    has_audio: bool | None
    error: str | None
    created_at: datetime
    job: JobOut | None = None
    """가장 최근 job (진행률 폴링용)."""
    proxy_url: str | None = None
    peaks_url: str | None = None


class ProjectCreated(BaseModel):
    project: ProjectOut
    upload_url: str
    upload_headers: dict[str, str]


class WordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    idx: int
    start_ms: int
    end_ms: int
    text: str


class DecisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    start_ms: int
    end_ms: int
    kind: str
    reason: str
    confidence: float
    status: str
    source: str


class DecisionPatch(BaseModel):
    status: Literal["suggested", "accepted", "rejected"] | None = None
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, ge=0)


class DecisionCreate(BaseModel):
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    reason: str = ""


class ExportOut(BaseModel):
    format: str
    url: str
    created_at: datetime
