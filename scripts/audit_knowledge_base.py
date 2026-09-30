"""Audit the PostgreSQL document registry and Qdrant index.

Dry-run is the default. Use --apply only after reviewing the generated report.
"""
import argparse
import asyncio
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient, models
from sqlalchemy import select

from src.backend.core.config import settings
from src.backend.db.database import AsyncSessionLocal
from src.backend.db.models import KnowledgeBaseFile


def scroll_all(client: QdrantClient) -> list:
    points = []
    offset = None
    while True:
        batch, offset = client.scroll(
            collection_name=settings.qdrant_collection_name,
            limit=256,
            offset=offset,
            with_payload=True,
            with_vectors=True,
        )
        points.extend(batch)
        if offset is None:
            return points


def point_metadata(point) -> dict:
    payload = point.payload or {}
    metadata = payload.get("metadata")
    return metadata if isinstance(metadata, dict) else payload


def document_hashes() -> dict[str, str]:
    root = Path("docs")
    if not root.exists():
        return {}
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in {".md", ".markdown", ".txt", ".pdf"}
    }


async def registry_rows() -> list[dict[str, Any]]:
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(KnowledgeBaseFile))).scalars().all()
        return [
            {
                "id": str(row.id),
                "filename": row.filename,
                "file_hash": row.file_hash,
                "total_chunks": row.total_chunks,
                "image_count": row.image_count,
                "status": row.status,
                "chunk_strategy": row.chunk_strategy,
                "chunk_strategy_version": row.chunk_strategy_version,
                "chunk_size": row.chunk_size,
                "chunk_overlap": row.chunk_overlap,
            }
            for row in rows
        ]


def classify(points: list, rows: list[dict[str, Any]], hashes: dict[str, str]) -> dict[str, Any]:
    registered_keys = {(row["file_hash"], row["filename"]) for row in rows}
    active_rows = [row for row in rows if row["status"] == "active"]
    points_by_file_id = defaultdict(list)
    points_by_source = defaultdict(list)
    for point in points:
        metadata = point_metadata(point)
        file_id = str(metadata.get("file_id", ""))
        source = str(metadata.get("filename") or metadata.get("source") or "")
        if file_id:
            points_by_file_id[file_id].append(point)
        if source:
            points_by_source[source].append(point)

    registered = []
    for row in active_rows:
        matching = points_by_file_id.get(row["id"], [])
        if not matching:
            matching = [
                point for point in points_by_source.get(row["filename"], [])
                if point_metadata(point).get("file_hash") == row["file_hash"]
            ]
        strategies = Counter(
            point_metadata(point).get("chunk_strategy")
            or point_metadata(point).get("parser_type", "")
            for point in matching
        )
        item = {
            **row,
            "vector_count": len(matching),
            "vector_strategies": dict(strategies),
            "vector_file_ids": sorted({str(point_metadata(point).get("file_id", "")) for point in matching}),
        }
        if len(matching) == row["total_chunks"] and matching:
            registered.append(item)
        else:
            registered.append({**item, "status": "chunk_count_mismatch"})

    orphan_temp = []
    unregistered = []
    for point in points:
        metadata = point_metadata(point)
        file_id = str(metadata.get("file_id", ""))
        source = str(metadata.get("filename") or metadata.get("source") or "")
        item = {
            "id": str(point.id),
            "file_id": file_id,
            "source": source,
            "file_hash": metadata.get("file_hash"),
            "strategy": metadata.get("chunk_strategy") or metadata.get("parser_type"),
            "payload": point.payload,
            "vector": point.vector,
        }
        point_key = (metadata.get("file_hash"), Path(source).name)
        if point_key in registered_keys or file_id in {row["id"] for row in rows}:
            continue
        if Path(source).name.startswith("tmp") and Path(source).suffix == ".md":
            orphan_temp.append(item)
        else:
            unregistered.append(item)

    known_filenames = {row["filename"] for row in rows}
    docs_without_registry = [
        {"filename": filename, "file_hash": file_hash}
        for filename, file_hash in sorted(hashes.items())
        if filename not in known_filenames
    ]
    return {
        "registered": registered,
        "orphan_temp_vectors": orphan_temp,
        "unregistered_vectors": unregistered,
        "docs_without_registry": docs_without_registry,
        "counts": {
            "database_rows": len(rows),
            "active_database_rows": len(active_rows),
            "qdrant_points": len(points),
            "orphan_temp_vectors": len(orphan_temp),
            "unregistered_vectors": len(unregistered),
            "docs_without_registry": len(docs_without_registry),
        },
    }


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def apply_cleanup(client: QdrantClient, report: dict[str, Any], backup_path: Path) -> int:
    orphan = report["orphan_temp_vectors"]
    if not orphan:
        return 0
    save_json(backup_path, {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "collection": settings.qdrant_collection_name,
        "points": orphan,
    })
    client.delete(
        collection_name=settings.qdrant_collection_name,
        points_selector=models.PointIdsList(points=[item["id"] for item in orphan]),
        wait=True,
    )
    return len(orphan)


async def main(args) -> None:
    client = QdrantClient(url=settings.qdrant_url)
    rows = await registry_rows()
    report = classify(scroll_all(client), rows, document_hashes())
    report["mode"] = "apply" if args.apply else "dry-run"
    report["generated_at"] = datetime.now(timezone.utc).isoformat()
    save_json(args.report, report)

    removed = 0
    if args.apply:
        removed = apply_cleanup(client, report, args.backup)
    print(json.dumps({
        "status": "applied" if args.apply else "dry-run",
        "report": str(args.report),
        "backup": str(args.backup) if args.apply and removed else None,
        "removed_orphan_temp_vectors": removed,
        "counts": report["counts"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report", type=Path, default=Path("backups/knowledge_audit.json"))
    parser.add_argument("--backup", type=Path, default=Path("backups/orphan_temp_vectors.json"))
    asyncio.run(main(parser.parse_args()))
