"""Thin diagnostic CLI for the typed adaptive PDF extractor."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from eda.adaptive_ocr import AdaptiveOCRConfig, AdaptivePDFExtractor


def _one_based_pages(value: str) -> tuple[int, ...]:
    try:
        pages = tuple(sorted({int(item.strip()) for item in value.split(",") if item.strip()}))
    except ValueError as error:
        raise argparse.ArgumentTypeError("Pages must be comma-separated integers.") from error
    if not pages or pages[0] < 1:
        raise argparse.ArgumentTypeError("Page numbers must be one-based positive integers.")
    return pages


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Emit typed adaptive PDF page contracts.")
    parser.add_argument("pdf_path", type=Path)
    parser.add_argument("--pages", required=True, type=_one_based_pages)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--logical-document-key", required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("data/debug/adaptive-pdf"))
    parser.add_argument("--dpi", type=int, default=220)
    parser.add_argument("--languages", default="fas+eng,fas,eng")
    parser.add_argument("--psm", default="3,6,11")
    parser.add_argument("--preprocessing", default="original,enhanced")
    parser.add_argument("--max-candidates", type=int, default=8)
    parser.add_argument("--region-min-advantage", type=float, default=5.0)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    config = AdaptiveOCRConfig(
        render_dpi=args.dpi,
        language_profiles=tuple(item.strip() for item in args.languages.split(",") if item.strip()),
        psm_candidates=tuple(int(item.strip()) for item in args.psm.split(",") if item.strip()),
        preprocessing_candidates=tuple(
            item.strip() for item in args.preprocessing.split(",") if item.strip()
        ),
        max_candidate_count=args.max_candidates,
        region_min_advantage=args.region_min_advantage,
    )
    extraction = AdaptivePDFExtractor(config).extract(
        args.pdf_path,
        tenant_id=args.tenant_id,
        logical_document_key=args.logical_document_key,
        source_name=args.pdf_path.name,
        page_indexes=(page - 1 for page in args.pages),
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "manifest.json").write_text(
        extraction.manifest.model_dump_json(indent=2),
        encoding="utf-8",
    )
    for page in extraction.pages:
        output = args.output_dir / f"page-{page.page_number}.json"
        output.write_text(page.model_dump_json(indent=2), encoding="utf-8")
        print(
            json.dumps(
                {
                    "page_number": page.page_number,
                    "page_type": page.page_type.value,
                    "status": page.processing_status.value,
                    "route": page.ocr_decision.selected_route.value,
                    "quality_gate_passed": page.ocr_decision.quality_gate_passed,
                    "confidence": page.ocr_decision.mean_confidence,
                    "quality_score": page.ocr_decision.quality_score,
                    "agreement_score": page.ocr_decision.agreement_score,
                    "selection_score": page.ocr_decision.selection_score,
                    "candidate_count": page.ocr_decision.candidate_count,
                    "duration_ms": page.ocr_decision.processing_time_ms,
                    "warnings": page.warnings,
                    "output": output.as_posix(),
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
