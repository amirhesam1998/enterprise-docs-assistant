"""Extraction quality report harness.

Runs the extraction router over files and produces a factual per-file report:
chosen route, page counts by verdict, average quality score, table count, OCR
usage, warnings, and errors. It reports only measured values and never fabricates
confidence. With no real Persian/English benchmark corpus committed to the repo,
this harness is the instrument to run once such documents are available locally.
"""

from __future__ import annotations

from pathlib import Path

from eda.extractors.base import (
    ExtractedDocument,
    ExtractionFailed,
    ExtractionOptions,
    ExtractorRoute,
)
from eda.extractors.router import ExtractionRouter, default_router
from eda.ingestion_schema import ExtractionRoute as PageRoute

_OCR_ROUTES = {PageRoute.FULL_PAGE_OCR, PageRoute.REGION_OCR, PageRoute.COMBINED}
SUPPORTED_EXTENSIONS = frozenset({".pdf", ".docx", ".xlsx", ".png", ".jpg", ".jpeg"})


def build_report(document: ExtractedDocument) -> dict:
    """Summarize one extracted document into a JSON-serializable report row."""
    quality = document.quality
    ocr_pages = sum(
        1 for page in document.pages if page.ocr_decision.selected_route in _OCR_ROUTES
    )
    return {
        "file": document.manifest.source_name,
        "extractor_route": document.extractor_route.value,
        "page_count": len(document.pages),
        "accepted_pages": quality.accepted_pages,
        "needs_review_pages": quality.needs_review_pages,
        "failed_pages": quality.failed_pages,
        "empty_pages": quality.empty_pages,
        "average_quality_score": quality.score,
        "quality_level": quality.level.value,
        "table_count": document.table_count,
        "ocr_route_pages": ocr_pages,
        "warnings": list(dict.fromkeys(list(document.warnings) + list(quality.warnings))),
        "errors": list(document.errors),
    }


def _options_for(path: Path, tenant_id: str, acl_groups: tuple[str, ...]) -> ExtractionOptions:
    return ExtractionOptions(
        tenant_id=tenant_id,
        logical_document_key=path.name,
        source_name=path.name,
        acl_groups=acl_groups,
    )


def report_file(
    path: str | Path,
    *,
    router: ExtractionRouter | None = None,
    tenant_id: str = "evaluation",
    acl_groups: tuple[str, ...] = ("evaluation",),
) -> dict:
    """Extract and summarize a single file, returning an error row on failure."""
    path = Path(path)
    router = router or default_router()
    try:
        document = router.extract(path, options=_options_for(path, tenant_id, acl_groups))
    except ExtractionFailed as error:
        return {"file": path.name, "extractor_route": None, "error": str(error)}
    return build_report(document)


def run_folder(
    folder: str | Path,
    *,
    router: ExtractionRouter | None = None,
    tenant_id: str = "evaluation",
    acl_groups: tuple[str, ...] = ("evaluation",),
) -> list[dict]:
    """Report on every supported file directly inside ``folder`` (sorted by name)."""
    folder = Path(folder)
    if not folder.is_dir():
        raise NotADirectoryError(f"Not a directory: {folder.name}")
    router = router or default_router()
    reports: list[dict] = []
    for path in sorted(folder.iterdir()):
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
            reports.append(
                report_file(path, router=router, tenant_id=tenant_id, acl_groups=acl_groups)
            )
    return reports


def aggregate(reports: list[dict]) -> dict:
    """Aggregate a run into corpus-level totals — measured values only."""
    scored = [r for r in reports if "error" not in r]
    total_pages = sum(r["page_count"] for r in scored)
    accepted = sum(r["accepted_pages"] for r in scored)
    return {
        "files": len(reports),
        "files_extracted": len(scored),
        "files_failed": len(reports) - len(scored),
        "total_pages": total_pages,
        "accepted_pages": accepted,
        "needs_review_pages": sum(r["needs_review_pages"] for r in scored),
        "failed_pages": sum(r["failed_pages"] for r in scored),
        "tables": sum(r["table_count"] for r in scored),
        "mean_quality_score": (
            round(sum(r["average_quality_score"] for r in scored) / len(scored), 2)
            if scored else None
        ),
        "page_acceptance_rate": round(accepted / total_pages, 4) if total_pages else None,
    }
