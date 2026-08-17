"""Build the `docs` collection in Qdrant from source documents.

Qdrant runs as a server (see QDRANT_URL). Embedded file mode is deliberately not
used: it takes an exclusive lock on the storage directory, which stops this script
from running while the API is up.

All four tenants are declared in TENANTS below and indexed in a single run, so one
invocation rebuilds the whole store. Point IDs are uuid5(NAMESPACE, chunk_id),
derived inside eda.index — re-running this script overwrites the same points
rather than duplicating them, and tenants cannot collide because chunk_id carries
the source name.
"""
import os

from qdrant_client import QdrantClient

from eda.index import ingest_chunks
from eda.parse import parse_pdf, parse_xlsx

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
COLLECTION = os.getenv("QDRANT_COLLECTION", "docs")

POSTGRES_PDF = "data/raw/postgres/postgresql-17-A4.pdf"

# The four tenants, as data rather than blocks to comment in and out by hand.
# The page ranges are load-bearing — they define which points belong to which
# tenant, and together they produce 380 points.
TENANTS = [
    {
        "name": "postgres / engineering",
        "parser": parse_pdf,
        "args": {
            "path": POSTGRES_PDF,
            "tenant_id": "postgres",
            "source": "postgres.pdf",
            "logical_document_key": "postgres-reference-manual",
            "acl_groups": ["engineering"],
            "page_start": 31,
            "page_end": 131,
        },
    },
    {
        "name": "acme-internal / sales",
        "parser": parse_pdf,
        "args": {
            "path": POSTGRES_PDF,
            "tenant_id": "acme-internal",
            "source": "acme-handbook.pdf",
            "logical_document_key": "acme-handbook",
            "acl_groups": ["sales"],
            "page_start": 500,
            "page_end": 600,
        },
    },
    {
        "name": "postgres / hr",
        "parser": parse_pdf,
        "args": {
            "path": POSTGRES_PDF,
            "tenant_id": "postgres",
            "source": "postgres-hr.pdf",
            "logical_document_key": "postgres-hr-handbook",
            "acl_groups": ["hr"],
            "page_start": 700,
            "page_end": 750,
        },
    },
    {
        # No authoritative ACL is encoded in the current parser or workbook
        # contract. Configure acl_groups here before running this batch build.
        "name": "kb",
        "parser": parse_xlsx,
        "args": {
            "path": "data/excel/knowledge_base.xlsx",
            "tenant_id": "kb",
            "source": "knowledge_base.xlsx",
        },
    },
]


def validate_tenant_specs():
    """Fail before connecting/indexing when XLSX access scope is undefined."""
    for tenant in TENANTS:
        if tenant["parser"] is parse_xlsx and not tenant["args"].get("acl_groups"):
            raise ValueError(
                f"{tenant['name']}: configure authoritative acl_groups before "
                "XLSX indexing; missing ACL is not public access."
            )


if __name__ == "__main__":
    validate_tenant_specs()
    print(f"Qdrant: {QDRANT_URL}  collection: {COLLECTION}")
    client = QdrantClient(url=QDRANT_URL)
    try:
        total = 0
        for tenant in TENANTS:
            print(f"--- {tenant['name']} ---")
            chunks = tenant["parser"](**tenant["args"])
            total += ingest_chunks(chunks, client, COLLECTION)

        count = client.count(collection_name=COLLECTION).count
        print(f"مجموع: {total} — {count} point در «{COLLECTION}» ✅")
    finally:
        client.close()
