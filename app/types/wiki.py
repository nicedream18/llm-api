"""Wiki contracts; paths are logical identifiers, never filesystem paths."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def normalized_path(value: str) -> str:
    if len(value) > 384 or not value or value.startswith("/") or "\\" in value:
        raise ValueError("Invalid Wiki path")
    if any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError("Invalid Wiki path")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("Invalid Wiki path")
    return value


class WikiProjectInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=4096)


class WikiPageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    title: str = Field(min_length=1, max_length=256)
    content: str = Field(default="", max_length=1_000_000)
    tags: list[str] = Field(default_factory=list, max_length=100)

    _path = field_validator("path")(normalized_path)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, tags: list[str]) -> list[str]:
        if any(not tag.strip() or len(tag) > 64 for tag in tags):
            raise ValueError("Tags must contain between 1 and 64 characters")
        return sorted({tag.strip() for tag in tags})


class WikiPageUpdate(WikiPageInput):
    revision: int = Field(ge=1)


class WikiSourceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: str = Field(min_length=1, max_length=256)
    content: str = Field(min_length=1, max_length=1_000_000)


class WikiAskInput(BaseModel):
    question: str = Field(min_length=1, max_length=32768)
    model: str = Field(min_length=1, max_length=128)
    top_k: int = Field(default=5, ge=1, le=20)


class WikiBackupPage(WikiPageInput):
    pass


class WikiBackupAsset(BaseModel):
    page_path: str
    filename: str = Field(min_length=1, max_length=256)
    media_type: Literal[
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
        "application/pdf",
        "text/plain",
    ]
    content_base64: str = Field(max_length=14_000_000)


class WikiBackupSource(WikiSourceInput):
    status: Literal["pending", "ingested", "failed"] = "pending"
    page_path: str | None = None


class WikiBackup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: Literal["waliapi-wiki-v1"]
    project: WikiProjectInput
    pages: list[WikiBackupPage] = Field(default_factory=list, max_length=2000)
    attachments: list[WikiBackupAsset] = Field(default_factory=list, max_length=2000)
    sources: list[WikiBackupSource] = Field(default_factory=list, max_length=2000)
