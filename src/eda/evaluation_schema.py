"""Typed manifest for sanitized CI fixtures and ignored private OCR fixtures."""

from __future__ import annotations

from enum import Enum
from pathlib import PurePosixPath, PureWindowsPath

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from eda.ingestion_schema import ExtractionRoute, PageType


class EvaluationTier(str, Enum):
    COMMITTED_SANITIZED = "committed_sanitized"
    LOCAL_PRIVATE = "local_private"


class PrivacyClassification(str, Enum):
    PUBLIC = "public"
    SANITIZED = "sanitized"
    PRIVATE = "private"
    RESTRICTED = "restricted"


class EvaluationTag(str, Enum):
    NATIVE = "native"
    SCANNED = "scanned"
    MIXED = "mixed"
    PERSIAN = "Persian"
    ENGLISH = "English"
    MULTI_COLUMN = "multi-column"
    LOW_QUALITY = "low-quality"
    TABLE_LIKE = "table-like"
    EMPTY = "empty"


class EvaluationFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fixture_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    tier: EvaluationTier
    source_file: str = Field(min_length=1)
    source_page_number: int | None = Field(default=None, gt=0)
    expected_page_type: PageType
    expected_route: ExtractionRoute | None = None
    ground_truth_text: str | None = None
    expected_language_profiles: list[str] = Field(default_factory=list)
    tags: list[EvaluationTag] = Field(default_factory=list)
    privacy_classification: PrivacyClassification
    notes: str = ""

    @field_validator("source_file")
    @classmethod
    def require_relative_source(cls, value: str) -> str:
        windows = PureWindowsPath(value)
        posix = PurePosixPath(value)
        if windows.is_absolute() or posix.is_absolute() or ".." in windows.parts or ".." in posix.parts:
            raise ValueError("source_file must be a repository-relative fixture path.")
        return value.replace("\\", "/")

    @model_validator(mode="after")
    def validate_privacy_tier(self) -> "EvaluationFixture":
        if self.tier == EvaluationTier.COMMITTED_SANITIZED and self.privacy_classification not in {
            PrivacyClassification.PUBLIC,
            PrivacyClassification.SANITIZED,
        }:
            raise ValueError("Committed fixtures must be public or sanitized.")
        if self.tier == EvaluationTier.LOCAL_PRIVATE and self.privacy_classification not in {
            PrivacyClassification.PRIVATE,
            PrivacyClassification.RESTRICTED,
        }:
            raise ValueError("Local-private fixtures must be private or restricted.")
        return self


class EvaluationManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="1.0", pattern=r"^\d+\.\d+$")
    fixtures: list[EvaluationFixture]
