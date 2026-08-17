"""Route-based, canonical document extraction.

Public surface: the extractor interface (`DocumentExtractor`), the canonical
`ExtractedDocument` container, the concrete extractors, and the `ExtractionRouter`
with its `default_router()` / `docling_first_router()` factories.
"""

from eda.extractors.adaptive_pdf import AdaptivePdfExtractor
from eda.extractors.base import (
    DocumentExtractor,
    ExtractedDocument,
    ExtractionFailed,
    ExtractionOptions,
    ExtractorRoute,
    ExtractorUnavailable,
    extension_of,
)
from eda.extractors.docx import DocxExtractor
from eda.extractors.image import ImageOcrExtractor
from eda.extractors.native_pdf import NativePdfExtractor
from eda.extractors.router import (
    ExtractionRouter,
    default_router,
    docling_first_router,
)
from eda.extractors.xlsx import XlsxExtractor

__all__ = [
    "AdaptivePdfExtractor",
    "DocumentExtractor",
    "DocxExtractor",
    "ExtractedDocument",
    "ExtractionFailed",
    "ExtractionOptions",
    "ExtractionRouter",
    "ExtractorRoute",
    "ExtractorUnavailable",
    "ImageOcrExtractor",
    "NativePdfExtractor",
    "XlsxExtractor",
    "default_router",
    "docling_first_router",
    "extension_of",
]
