"""Register verified Qdrant document groups in the PostgreSQL registry.

Only groups whose source file and content hash match exactly are registered.
Existing rows and hash mismatches are skipped.
"""
import argparse
import asyncio
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import uuid

from qdrant_client import QdrantClient
from sqlalchemy import select

from src.backend.core.config import settings
from src.backend.db.database import AsyncSessionLocal
from src.backend.db.models import KnowledgeBaseFile


SUPPORTED_EXTENSIONS = {".md", ".markdown", ".txt", ".pdf"}


def scroll_all(client):
    points = []
    offset = None
    while True:
        batch, offset = client.scroll(
            collection_name=settings.qdrant_collection_name,
            limit=256,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        points.extend(batch)
        if offset is None:
            return points


def metadata(point):
    payload = point.payload or {}
    value = payload.get("metadata")
    return value if isinstance(value, dict) else payload


def current_documents():
    root = Path("docs")
    return {
        path.name: path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    }


def groups(points):
    result = defaultdict(list)
    for point in points:
        item = metadata(point)
        source = str(item.get("filename") or item.get("source") or "")
        file_hash = item.get("file_hash")
        if source and file_hash:
            result[(Path(source).name, file_hash)].append((point, item))
    return result


async def register_verified(apply: bool, selected_filenames: set[str] | None = None):
    client = QdrantClient(url=settings.qdrant_url)
    docs = current_documents()
    grouped = groups(scroll_all(client))
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(KnowledgeBaseFile))).scalars().all()
        existing_hashes = {row.file_hash for row in rows}
        existing_names = {row.filename for row in rows}
        candidates = []
        skipped = []

        for (filename, vector_hash), entries in sorted(grouped.items()):
            if selected_filenames is not None and filename not in selected_filenames:
                continue
            path = docs.get(filename)
            if path is None:
                skipped.append({"filename": filename, "reason": "file_not_found"})
                continue
            actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual_hash != vector_hash:
                skipped.append({"filename": filename, "reason": "hash_mismatch", "vector_hash": vector_hash, "file_hash": actual_hash})
                continue
            if vector_hash in existing_hashes or filename in existing_names:
                skipped.append({"filename": filename, "reason": "already_registered"})
                continue

            first = entries[0][1]
            vector_file_ids = {str(item.get("file_id", "")) for _, item in entries if item.get("file_id")}
            if len(vector_file_ids) != 1:
                skipped.append({"filename": filename, "reason": "multiple_vector_file_ids"})
                continue
            try:
                file_id = uuid.UUID(next(iter(vector_file_ids)))
            except ValueError:
                skipped.append({"filename": filename, "reason": "invalid_vector_file_id"})
                continue

            strategy = first.get("chunk_strategy") or first.get("parser_type") or "character"
            strategy_version = first.get("chunk_strategy_version") or f"{strategy}_v1"
            candidates.append({
                "id": str(file_id),
                "filename": filename,
                "file_hash": vector_hash,
                "file_size": path.stat().st_size,
                "total_chunks": len(entries),
                "image_count": sum(1 for _, item in entries if item.get("image_paths")),
                "source_type": "hospital" if strategy == "hospital_markdown" else "document",
                "chunk_strategy": strategy,
                "chunk_strategy_version": strategy_version,
                "chunk_size": first.get("chunk_size") or 512,
                "chunk_overlap": first.get("chunk_overlap") or 50,
            })

        inserted = []
        if apply:
            for item in candidates:
                db.add(KnowledgeBaseFile(
                    id=uuid.UUID(item["id"]),
                    filename=item["filename"],
                    original_file_path=f"docs/{item['filename']}",
                    file_hash=item["file_hash"],
                    file_size=item["file_size"],
                    total_chunks=item["total_chunks"],
                    image_count=item["image_count"],
                    source_type=item["source_type"],
                    chunk_strategy=item["chunk_strategy"],
                    chunk_strategy_version=item["chunk_strategy_version"],
                    chunk_size=item["chunk_size"],
                    chunk_overlap=item["chunk_overlap"],
                    metadata_json={
                        "parser_type": item["chunk_strategy"],
                        "registered_from": "verified_qdrant_vectors",
                        "vector_file_id": item["id"],
                    },
                    status="active",
                ))
                inserted.append(item)
            await db.commit()

    print(json.dumps({
        "status": "applied" if apply else "dry-run",
        "candidates": candidates,
        "inserted": inserted,
        "skipped": skipped,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--filename", action="append", default=[])
    args = parser.parse_args()
    asyncio.run(register_verified(args.apply, set(args.filename) if args.filename else None))
