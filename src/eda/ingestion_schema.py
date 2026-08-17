"""Versioned ingestion contracts for the upcoming OCR integration milestone."""

from __future__ import annotations

import re
import subprocess
import unicodedata
from datetime import datetime
from enum import Enum
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from eda.identifiers import page_id as build_page_id
from eda.identifiers import revision_id as build_revision_id
from eda.identifiers import validate_sha256


INGESTION_SCHEMA_VERSION = "1.0"
SCHEMA_VERSION_PATTERN = r"^\d+\.\d+$"
_CODE_REVISION_PATTERN = re.compile(r"^[0-9a-fA-F]{7,64}$")
_PRIVATE_PATH_PATTERN = re.compile(
    r"(?:[A-Za-z]:[\\/]|(?<![\w:])/(?:Users|home|var|tmp|app|data)/)",
    re.IGNORECASE,
)
_SECRET_VALUE_PATTERN = re.compile(
    r"(?:password|secret|access[_-]?token|api[_-]?key)\s*[:=]",
    re.IGNORECASE,
)
_SENSITIVE_KEYS = {
    "api_key",
    "authorization",
    "connection_string",
    "password",
    "secret",
    "secret_key",
    "token",
    "access_token",
}
_TEXT_METADATA_KEYS = {
    "candidate_text",
    "content",
    "document_text",
    "native_text",
    "ocr_text",
    "text",
    "text_preview",
}


class PageType(str, Enum):
    DIGITAL = "digital"
    SCANNED = "scanned"
    MIXED = "mixed"
    EMPTY = "empty"
    UNKNOWN = "unknown"


class ExtractionRoute(str, Enum):
    NATIVE = "native"
    FULL_PAGE_OCR = "full_page_ocr"
    REGION_OCR = "region_ocr"
    COMBINED = "combined"
    REJECTED = "rejected"


class ProcessingStatus(str, Enum):
    ACCEPTED = "accepted"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"


class TextLayer(str, Enum):
    NATIVE = "native"
    OCR = "ocr"
    COMBINED = "combined"


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


def _is_absolute_path(value: str) -> bool:
    return PureWindowsPath(value).is_absolute() or PurePosixPath(value).is_absolute()


def _validate_public_metadata(value: Any, location: str = "metadata") -> Any:
    if isinstance(value, dict):
        for raw_key, item in value.items():
            key = str(raw_key).strip().casefold().replace("-", "_")
            if key in _SENSITIVE_KEYS:
                raise ValueError(f"{location} must not contain secret field {raw_key!r}.")
            if key in _TEXT_METADATA_KEYS:
                raise ValueError(f"{location} must not duplicate document/OCR text.")
            _validate_public_metadata(item, f"{location}.{raw_key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _validate_public_metadata(item, f"{location}[{index}]")
    elif isinstance(value, str) and _is_absolute_path(value):
        raise ValueError(f"{location} must not contain an absolute private path.")
    return value


def _require_timezone(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timestamp must include a timezone.")
    return value


def _validate_public_messages(values: list[str]) -> list[str]:
    for value in values:
        if _PRIVATE_PATH_PATTERN.search(value):
            raise ValueError("Public messages must not contain absolute private paths.")
        if _SECRET_VALUE_PATTERN.search(value):
            raise ValueError("Public messages must not contain secret values.")
    return values


class DocumentManifest(ContractModel):
    """Public document metadata only; no source path or document text."""

    schema_version: str = Field(
        default=INGESTION_SCHEMA_VERSION,
        pattern=SCHEMA_VERSION_PATTERN,
    )
    document_id: UUID
    revision_id: UUID
    tenant_id: str = Field(min_length=1)
    source_name: str = Field(min_length=1)
    source_type: str = Field(min_length=1)
    source_sha256: str
    file_size_bytes: int = Field(ge=0)
    mime_type: str = Field(min_length=1)
    total_pages: int | None = Field(default=None, gt=0)
    parser_name: str = Field(min_length=1)
    parser_version: str = Field(min_length=1)
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("source_sha256")
    @classmethod
    def validate_digest(cls, value: str) -> str:
        return validate_sha256(value)

    @field_validator("source_name")
    @classmethod
    def require_public_source_name(cls, value: str) -> str:
        value = value.strip()
        if (
            not value
            or PureWindowsPath(value).name != value
            or PurePosixPath(value).name != value
        ):
            raise ValueError("source_name must be a filename, not a local path.")
        return value

    @field_validator("created_at")
    @classmethod
    def require_created_timezone(cls, value: datetime) -> datetime:
        return _require_timezone(value)

    @field_validator("metadata")
    @classmethod
    def require_safe_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _validate_public_metadata(value)

    @model_validator(mode="after")
    def validate_revision_identifier(self) -> "DocumentManifest":
        expected = build_revision_id(str(self.document_id), self.source_sha256)
        if str(self.revision_id) != expected:
            raise ValueError("revision_id does not match document_id and source_sha256.")
        return self


class TextRegion(ContractModel):
    """Text in a top-left-origin pixel box: ``(left, top, right, bottom)``."""

    region_id: UUID
    source_layer: TextLayer
    text: str = Field(min_length=1)
    bbox: tuple[float, float, float, float]
    reading_order: int = Field(ge=0)
    confidence: float | None = Field(default=None, ge=0, le=100)
    language_profile: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("bbox")
    @classmethod
    def validate_bbox(
        cls,
        value: tuple[float, float, float, float],
    ) -> tuple[float, float, float, float]:
        left, top, right, bottom = value
        if left < 0 or top < 0 or right <= left or bottom <= top:
            raise ValueError(
                "bbox must use non-negative (left, top, right, bottom) pixels "
                "with right > left and bottom > top."
            )
        return value

    @field_validator("metadata")
    @classmethod
    def require_safe_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _validate_public_metadata(value)


class OCRMetrics(ContractModel):
    mean_confidence: float | None = Field(default=None, ge=0, le=100)
    quality_score: float | None = Field(default=None, ge=0, le=100)
    agreement_score: float | None = Field(default=None, ge=0, le=100)
    selection_score: float | None = Field(default=None, ge=0, le=100)


class OCRCandidateMetrics(OCRMetrics):
    """Compact public candidate evidence; candidate text is deliberately absent."""

    route: ExtractionRoute
    psm: int | Literal["mixed"] | None = None
    language_profile: str | None = None
    preprocessing: str | None = None
    text_length: int = Field(ge=0)
    word_count: int = Field(ge=0)
    meaningful_character_ratio: float = Field(ge=0, le=1)
    garbage_ratio: float = Field(ge=0, le=1)
    repetition_ratio: float = Field(ge=0, le=1)
    coverage: float = Field(ge=0, le=1)
    structurally_valid: bool
    reading_order_valid: bool = True
    quality_gate_passed: bool
    rejection_reasons: list[str] = Field(default_factory=list)

    @field_validator("rejection_reasons")
    @classmethod
    def require_public_rejection_reasons(cls, value: list[str]) -> list[str]:
        return _validate_public_messages(value)


class OCRDecision(OCRMetrics):
    selected_route: ExtractionRoute
    selected_psm: int | Literal["mixed"] | None = None
    selected_language_profile: str | None = None
    selected_preprocessing: str | None = None
    quality_gate_passed: bool
    fallback_reasons: list[str] = Field(default_factory=list)
    candidate_count: int = Field(ge=0)
    processing_time_ms: float | None = Field(default=None, ge=0)
    candidate_metrics: list[OCRCandidateMetrics] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @field_validator("fallback_reasons", "errors", "warnings")
    @classmethod
    def require_public_messages(cls, value: list[str]) -> list[str]:
        return _validate_public_messages(value)

    @model_validator(mode="after")
    def validate_evidence(self) -> "OCRDecision":
        if self.candidate_metrics and len(self.candidate_metrics) != self.candidate_count:
            raise ValueError("candidate_count must match serialized candidate_metrics.")
        if self.candidate_count < 2 and self.agreement_score is not None:
            raise ValueError(
                "agreement_score requires at least two candidates; use null "
                "when independent evidence is insufficient."
            )
        if self.selected_route == ExtractionRoute.REJECTED and self.quality_gate_passed:
            raise ValueError("A rejected route cannot pass the quality gate.")
        if (
            self.selected_route
            in {
                ExtractionRoute.FULL_PAGE_OCR,
                ExtractionRoute.REGION_OCR,
                ExtractionRoute.COMBINED,
            }
            and self.candidate_count == 0
        ):
            raise ValueError("An OCR route requires at least one OCR candidate.")
        return self


class ProcessingProvenance(ContractModel):
    pipeline_name: str = Field(min_length=1)
    pipeline_version: str = Field(min_length=1)
    schema_version: str = Field(
        default=INGESTION_SCHEMA_VERSION,
        pattern=SCHEMA_VERSION_PATTERN,
    )
    input_sha256: str
    dpi: int | None = Field(default=None, gt=0)
    requested_language_profiles: list[str] = Field(default_factory=list)
    resolved_language_profiles: list[str] = Field(default_factory=list)
    python_version: str = Field(min_length=1)
    tesseract_version: str | None = None
    pymupdf_version: str | None = None
    opencv_version: str | None = None
    platform: str = Field(min_length=1)
    code_revision: str | None = None
    processing_timestamp: datetime

    @field_validator("input_sha256")
    @classmethod
    def validate_digest(cls, value: str) -> str:
        return validate_sha256(value)

    @field_validator("code_revision")
    @classmethod
    def validate_code_revision(cls, value: str | None) -> str | None:
        if value is not None and not _CODE_REVISION_PATTERN.fullmatch(value):
            raise ValueError("code_revision must be a Git hexadecimal revision.")
        return value

    @field_validator("processing_timestamp")
    @classmethod
    def require_processing_timezone(cls, value: datetime) -> datetime:
        return _require_timezone(value)


def safe_git_revision(repo_root: str | None = None) -> str | None:
    """Return HEAD when available, otherwise ``None`` without exposing paths."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            check=False,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    revision = result.stdout.strip()
    return revision if result.returncode == 0 and _CODE_REVISION_PATTERN.fullmatch(revision) else None


def derive_index_text(native_text: str, ocr_text: str) -> str:
    """Preserve both layers, dropping only an obviously identical OCR copy."""
    native = native_text.strip()
    ocr = ocr_text.strip()
    if not native:
        return ocr
    if not ocr:
        return native
    def normalize(text: str) -> str:
        text = unicodedata.normalize("NFKC", text).casefold()
        text = text.translate(str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "ـ": ""}))
        return " ".join(text.replace("\u200c", " ").split())
    return native if normalize(native) == normalize(ocr) else f"{native}\n\n{ocr}"


class BlockType(str, Enum):
    """Semantic role of a canonical block, one level above raw text regions."""

    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST_ITEM = "list_item"
    TABLE = "table"
    KEY_VALUE = "key_value"
    IMAGE_TEXT = "image_text"
    HEADER = "header"
    FOOTER = "footer"
    CAPTION = "caption"
    UNKNOWN = "unknown"


class TableCell(ContractModel):
    """One logical cell in a canonical table, addressed by zero-based indices."""

    row_index: int = Field(ge=0)
    col_index: int = Field(ge=0)
    row_span: int = Field(default=1, ge=1)
    col_span: int = Field(default=1, ge=1)
    text: str = ""
    is_header: bool = False

    @field_validator("text")
    @classmethod
    def strip_cell_text(cls, value: str) -> str:
        return value.strip()


class TableResult(ContractModel):
    """A structure-preserving table; ``markdown`` is a lossy reading aid only."""

    num_rows: int = Field(gt=0)
    num_cols: int = Field(gt=0)
    cells: list[TableCell] = Field(default_factory=list)
    caption: str | None = None
    markdown: str = ""

    @model_validator(mode="after")
    def validate_cell_bounds(self) -> "TableResult":
        for cell in self.cells:
            if cell.row_index + cell.row_span > self.num_rows:
                raise ValueError("Table cell exceeds the declared row count.")
            if cell.col_index + cell.col_span > self.num_cols:
                raise ValueError("Table cell exceeds the declared column count.")
        return self


class BlockResult(ContractModel):
    """A semantic, reading-ordered unit produced by any extraction route.

    Blocks are the canonical input to structure-aware chunking. A block carries a
    stable ID, its reading order on the page, its extraction provenance (route and
    source layer), and — for tables — a structure-preserving ``table`` payload in
    addition to a flattened ``text`` rendering used for retrieval.
    """

    block_id: UUID
    block_type: BlockType
    text: str = Field(min_length=1)
    page_number: int = Field(gt=0)
    reading_order: int = Field(ge=0)
    source_layer: TextLayer
    extraction_route: ExtractionRoute
    bbox: tuple[float, float, float, float] | None = None
    language_profile: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=100)
    quality_score: float | None = Field(default=None, ge=0, le=100)
    table: TableResult | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("bbox")
    @classmethod
    def validate_bbox(
        cls,
        value: tuple[float, float, float, float] | None,
    ) -> tuple[float, float, float, float] | None:
        if value is None:
            return None
        left, top, right, bottom = value
        if left < 0 or top < 0 or right <= left or bottom <= top:
            raise ValueError(
                "bbox must use non-negative (left, top, right, bottom) pixels "
                "with right > left and bottom > top."
            )
        return value

    @field_validator("metadata")
    @classmethod
    def require_safe_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _validate_public_metadata(value)

    @model_validator(mode="after")
    def validate_table_linkage(self) -> "BlockResult":
        if self.block_type == BlockType.TABLE and self.table is None:
            raise ValueError("A table block must carry a structured table payload.")
        if self.table is not None and self.block_type != BlockType.TABLE:
            raise ValueError("Only table blocks may carry a structured table payload.")
        return self


class PageResult(ContractModel):
    schema_version: str = Field(
        default=INGESTION_SCHEMA_VERSION,
        pattern=SCHEMA_VERSION_PATTERN,
    )
    document_id: UUID
    revision_id: UUID
    page_id: UUID
    page_index: int = Field(ge=0)
    page_number: int = Field(gt=0)
    page_type: PageType
    processing_status: ProcessingStatus
    native_text: str = ""
    ocr_text: str = ""
    index_text: str = ""
    regions: list[TextRegion] = Field(default_factory=list)
    blocks: list[BlockResult] = Field(default_factory=list)
    ocr_decision: OCRDecision
    provenance: ProcessingProvenance
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @field_validator("errors", "warnings")
    @classmethod
    def require_public_messages(cls, value: list[str]) -> list[str]:
        return _validate_public_messages(value)

    @model_validator(mode="after")
    def validate_page_policy(self) -> "PageResult":
        if self.page_number != self.page_index + 1:
            raise ValueError("page_number must equal zero-based page_index + 1.")
        if str(self.page_id) != build_page_id(str(self.revision_id), self.page_index):
            raise ValueError("page_id does not match revision_id and page_index.")

        object.__setattr__(
            self,
            "index_text",
            derive_index_text(self.native_text, self.ocr_text),
        )
        route = self.ocr_decision.selected_route

        if route == ExtractionRoute.NATIVE and not self.native_text.strip():
            raise ValueError("The native route requires native_text.")
        if route in {ExtractionRoute.FULL_PAGE_OCR, ExtractionRoute.REGION_OCR} \
                and not self.ocr_text.strip():
            raise ValueError("An OCR route requires ocr_text.")
        if route == ExtractionRoute.COMBINED and not (
            self.native_text.strip() and self.ocr_text.strip()
        ):
            raise ValueError("The combined route requires native_text and ocr_text.")

        if self.processing_status == ProcessingStatus.ACCEPTED:
            if route == ExtractionRoute.REJECTED:
                raise ValueError("Rejected extraction cannot be accepted.")
            if not self.ocr_decision.quality_gate_passed:
                raise ValueError("A failed quality gate cannot produce accepted output.")
            if not self.index_text:
                raise ValueError("Accepted pages require non-empty index_text.")
            if self.page_type == PageType.UNKNOWN:
                raise ValueError("Unknown pages must be reviewed before acceptance.")
            if self.page_type == PageType.MIXED and route != ExtractionRoute.COMBINED:
                raise ValueError("Accepted mixed pages must use the combined route.")
            if self.page_type == PageType.SCANNED and route not in {
                ExtractionRoute.FULL_PAGE_OCR,
                ExtractionRoute.REGION_OCR,
            }:
                raise ValueError("Accepted scanned pages require an OCR route.")

        for block in self.blocks:
            if block.page_number != self.page_number:
                raise ValueError("Every block must belong to its page_number.")
        return self

    def deterministic_payload(self) -> dict[str, Any]:
        """Return content fields excluding runtime duration and timestamp."""
        payload = self.model_dump(mode="json")
        payload["ocr_decision"].pop("processing_time_ms", None)
        payload["provenance"].pop("processing_timestamp", None)
        return payload
