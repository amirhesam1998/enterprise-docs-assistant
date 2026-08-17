"""The extractor interface and the canonical `ExtractedDocument` container.

An extractor turns one source file into a canonical, quality-scored document:
a public `DocumentManifest` plus a list of schema-valid `PageResult`s (each
carrying reading-ordered `BlockResult`s). Extractors never touch Qdrant, the
embedding model, or ACL groups — they produce the intermediate representation
that structure-aware chunking later converts into `Chunk`s.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterator

from eda.ingestion_schema import BlockResult, DocumentManifest, PageResult
from eda.quality import QualityReport, score_document


class ExtractorRoute(str, Enum):
    """Which extractor implementation produced a document."""

    DOCLING = "docling"
    NATIVE_PDF = "native_pdf"
    ADAPTIVE_PDF_OCR = "adaptive_pdf_ocr"
    DOCX = "docx"
    XLSX = "xlsx"
    IMAGE_OCR = "image_ocr"


class ExtractorUnavailable(RuntimeError):
    """The extractor cannot run here (missing engine/dependency). Message is public-safe."""


class ExtractionFailed(RuntimeError):
    """The extractor ran but could not produce usable output. Message is public-safe."""


@dataclass(frozen=True)
class ExtractionOptions:
    """Inputs an extractor needs. ACL groups are carried for the downstream
    chunker only and are deliberately never written into public manifest metadata."""

    tenant_id: str
    logical_document_key: str
    source_name: str
    acl_groups: tuple[str, ...] = ()
    page_start: int = 0
    page_end: int | None = None
    allow_needs_review: bool = False
    ocr_languages: str = "eng+fas"
    adaptive_config: Any = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExtractedDocument:
    """Canonical output of an extraction: manifest + scored pages."""

    manifest: DocumentManifest
    pages: tuple[PageResult, ...]
    extractor_route: ExtractorRoute
    quality: QualityReport
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    @classmethod
    def build(
        cls,
        *,
        manifest: DocumentManifest,
        pages: list[PageResult] | tuple[PageResult, ...],
        extractor_route: ExtractorRoute,
        warnings: tuple[str, ...] = (),
        errors: tuple[str, ...] = (),
    ) -> "ExtractedDocument":
        pages = tuple(pages)
        quality = score_document(str(manifest.document_id), pages)
        return cls(
            manifest=manifest,
            pages=pages,
            extractor_route=extractor_route,
            quality=quality,
            warnings=warnings,
            errors=errors,
        )

    def iter_blocks(self) -> Iterator[tuple[PageResult, BlockResult]]:
        for page in self.pages:
            for block in page.blocks:
                yield page, block

    @property
    def table_count(self) -> int:
        return sum(1 for _, block in self.iter_blocks() if block.table is not None)


def extension_of(path: str | Path) -> str:
    return os.path.splitext(str(path))[1].lower()


class DocumentExtractor(ABC):
    """One extraction engine behind a uniform, testable interface."""

    route: ExtractorRoute
    supported_extensions: frozenset[str] = frozenset()

    @property
    def name(self) -> str:
        return self.route.value

    def supports(self, path: str | Path, mime_type: str | None = None, extension: str | None = None) -> bool:
        ext = (extension or extension_of(path)).lower()
        return ext in self.supported_extensions

    @abstractmethod
    def extract(self, path: str | Path, *, options: ExtractionOptions) -> ExtractedDocument:
        """Produce a canonical, quality-scored document. Must not leak source paths."""
        raise NotImplementedError
