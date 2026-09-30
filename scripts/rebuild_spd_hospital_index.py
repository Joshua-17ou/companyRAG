"""Dry-run by default; --apply replaces only the verified SPD document's points."""
import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path.cwd()))

from llama_index.core.schema import Document, MetadataMode
from llama_index.core.vector_stores.utils import node_to_metadata_dict
from qdrant_client import QdrantClient, models
from sqlalchemy import select, text

from src.backend.core.config import settings
from src.backend.db.database import AsyncSessionLocal
from src.backend.db.models import ImageMapping, KnowledgeBaseFile
from src.backend.ingestion.hospital_parser import HospitalDocumentParser
from src.backend.ingestion.image_mapper import ImageMapper


SOURCE = "销售_指南_SPD操作指南.md"


def scroll_all(client):
    points = []
    offset = None
    while True:
        batch, offset = client.scroll(settings.qdrant_collection_name, limit=100, offset=offset, with_vectors=True)
        points.extend(batch)
        if offset is None:
            return points


def fingerprint(points):
    return {str(point.id): json.dumps(point.model_dump(mode="json"), sort_keys=True, ensure_ascii=False) for point in points}


def restore_points(client, backup):
    client.upsert(settings.qdrant_collection_name, points=[models.PointStruct(
        id=point["id"], vector=point["vector"], payload=point["payload"]
    ) for point in backup["points"] if str(point["id"]) in backup["old_ids"]], wait=True)
    client.delete(settings.qdrant_collection_name, models.PointIdsList(points=backup["new_ids"]), wait=True)


async def restore_backup(client, path):
    backup = json.loads(path.read_text(encoding="utf-8"))
    if backup["collection"] != settings.qdrant_collection_name:
        raise RuntimeError("Backup collection does not match configured collection")
    current = scroll_all(client)
    target_ids = {str(point.id) for point in current if point.payload.get("source") == SOURCE}
    if not target_ids <= set(backup["old_ids"] + backup["new_ids"]):
        raise RuntimeError("SPD index changed after migration; refusing to overwrite newer data")
    async with AsyncSessionLocal() as db:
        registry = await db.get(KnowledgeBaseFile, uuid.UUID(backup["registry_id"]), with_for_update=True)
        original = next(row for row in backup["registry"] if row["id"] == backup["registry_id"])
        migration_id = (registry.metadata_json or {}).get("index_migration_id")
        if migration_id not in {None, backup["migration_id"]}:
            raise RuntimeError("Registry changed after migration")
        restore_points(client, backup)
        registry.total_chunks = original["total_chunks"]
        registry.image_count = original["image_count"]
        registry.metadata_json = original["metadata_json"]
        registry.updated_at = datetime.fromisoformat(original["updated_at"])
        for old_mapping in backup["image_mappings"]:
            mapping = await db.get(ImageMapping, uuid.UUID(old_mapping["id"]))
            if mapping:
                mapping.chunk_index = old_mapping["chunk_index"]
        await db.commit()
    print(json.dumps({"status": "restored", "backup": str(path)}, ensure_ascii=False))


async def main(args):
    client = QdrantClient(url=settings.qdrant_url)
    if args.restore:
        if not args.apply:
            raise RuntimeError("Restore requires --apply")
        await restore_backup(client, args.restore)
        return
    document_path = Path("docs") / SOURCE
    content = document_path.read_text(encoding="utf-8")
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    all_points = scroll_all(client)
    old_points = [point for point in all_points if point.payload.get("source") == SOURCE]
    if not old_points:
        raise RuntimeError("No existing SPD points found; refusing unscoped migration")
    file_ids = {point.payload.get("file_id") for point in old_points}
    hashes = {point.payload.get("file_hash") for point in old_points}
    permissions = {(point.payload.get("owner_dept"), point.payload.get("doc_type")) for point in old_points}
    if len(file_ids) != 1 or None in file_ids or hashes != {content_hash} or len(permissions) != 1:
        raise RuntimeError("Source hash, file identity or permissions do not match the existing index")
    if all(point.payload.get("parser_type") == "hospital" for point in old_points):
        print(json.dumps({"status": "already_migrated", "points": len(old_points)}))
        return
    if not all(isinstance(point.vector, list) and len(point.vector) == 512 for point in old_points):
        raise RuntimeError("Unexpected vector configuration")
    metadata = {key: value for key, value in old_points[0].payload.items()
                if not key.startswith("_") and key not in {"document_id", "doc_id", "ref_doc_id", "chunk_index", "total_chunks"}}
    metadata["filename"] = SOURCE
    metadata["file_path"] = str(document_path)
    metadata["parser_type"] = "hospital"
    metadata["version"] = max(point.payload.get("version", 1) for point in old_points) + 1
    mapper = ImageMapper()
    images = HospitalDocumentParser.extract_images(content)[1]
    descriptions = {}
    for image in images:
        info = mapper.get_image_info(Path(image["path"]).stem)
        if info:
            descriptions[image["path"]] = info["description"]
    document = Document(text=content, metadata=metadata, id_=old_points[0].payload["ref_doc_id"])
    nodes = HospitalDocumentParser.parse_documents_by_hospital([document], image_descriptions=descriptions)
    image_chunks = {}
    for chunk_index, node in enumerate(nodes):
        node.metadata.update({"chunk_index": chunk_index, "total_chunks": len(nodes)})
        for image_path in node.metadata["image_paths"]:
            image_chunks.setdefault(Path(image_path).name, chunk_index)
    expected_images = {Path(image["path"]).name for image in images}
    if not nodes or set(image_chunks) != expected_images:
        raise RuntimeError("Rebuilt chunks do not preserve all document image references")
    hospitals = Counter(node.metadata["hospital"] for node in nodes)
    if not hospitals.get("肇庆市一") or not hospitals.get("肇庆市二"):
        raise RuntimeError("Required hospital sections missing")
    async with AsyncSessionLocal() as db:
        registry = (await db.execute(select(KnowledgeBaseFile).where(
            KnowledgeBaseFile.file_hash == content_hash
        ).with_for_update())).scalar_one()
        mappings = list((await db.execute(select(ImageMapping).where(ImageMapping.source_file_id == registry.id))).scalars())
        summary = {"mode": "apply" if args.apply else "dry-run", "old_points": len(old_points), "new_points": len(nodes),
                   "other_points": len(all_points) - len(old_points), "hospitals": dict(hospitals),
                   "images": len(expected_images), "registry_id": str(registry.id), "vector_file_id": next(iter(file_ids))}
        print(json.dumps(summary, ensure_ascii=False), flush=True)
        if not args.apply:
            return
        migration_id = str(uuid.uuid4())
        backup_dir = args.backup_dir / datetime.now(timezone.utc).strftime("spd-%Y%m%dT%H%M%SZ")
        backup_dir.mkdir(parents=True, exist_ok=False)
        backup_path = backup_dir / "backup.json"
        registry_rows = (await db.execute(text("SELECT row_to_json(record) FROM knowledge_base_files AS record"))).scalars().all()
        mapping_rows = (await db.execute(text("SELECT row_to_json(record) FROM image_mappings AS record WHERE source_file_id = :file_id"), {"file_id": registry.id})).scalars().all()
        backup = {"collection": settings.qdrant_collection_name, "migration_id": migration_id,
                  "source_hash": content_hash, "registry_id": str(registry.id), "registry": list(registry_rows),
                  "image_mappings": list(mapping_rows), "points": [point.model_dump(mode="json") for point in all_points],
                  "old_ids": [str(point.id) for point in old_points], "new_ids": [node.node_id for node in nodes]}
        backup_path.write_text(json.dumps(backup, ensure_ascii=False, indent=2), encoding="utf-8")
        (backup_dir / SOURCE).write_bytes(document_path.read_bytes())
        print(f"Backup saved: {backup_path}", flush=True)
        from src.backend.ingestion.rag_service import LocalEmbeddingModel
        embedder = LocalEmbeddingModel()
        embeddings = embedder.get_text_embedding_batch([node.get_content(metadata_mode=MetadataMode.EMBED) for node in nodes])
        new_points = [models.PointStruct(id=node.node_id, vector=embedding,
                      payload=node_to_metadata_dict(node, remove_text=False, flat_metadata=False))
                      for node, embedding in zip(nodes, embeddings)]
        if fingerprint(scroll_all(client)) != fingerprint(all_points):
            raise RuntimeError("Index changed while preparing migration; retry during a quiet period")
        others_before = fingerprint([point for point in all_points if point.payload.get("source") != SOURCE])
        try:
            for start in range(0, len(new_points), 32):
                client.upsert(settings.qdrant_collection_name, points=new_points[start:start + 32], wait=True)
            inserted = client.retrieve(settings.qdrant_collection_name, ids=backup["new_ids"], with_payload=True)
            if len(inserted) != len(nodes) or Counter(point.payload.get("hospital") for point in inserted) != hospitals:
                raise RuntimeError("Inserted point count or hospital metadata validation failed")
            expected_text = {node.node_id: node.text for node in nodes}
            for point in inserted:
                if json.loads(point.payload["_node_content"])["text"] != expected_text[str(point.id)]:
                    raise RuntimeError("Stored node text does not match parsed document")
            client.delete(settings.qdrant_collection_name, models.PointIdsList(points=backup["old_ids"]), wait=True)
            after = scroll_all(client)
            if fingerprint([point for point in after if point.payload.get("source") != SOURCE]) != others_before:
                raise RuntimeError("Non-SPD points changed during migration")
            if {str(point.id) for point in after if point.payload.get("source") == SOURCE} != set(backup["new_ids"]):
                raise RuntimeError("Final SPD point IDs do not match the migration")
            registry.total_chunks = len(nodes)
            registry.image_count = len(expected_images)
            registry.metadata_json = {**(registry.metadata_json or {}), "parser_type": "hospital",
                                      "images_count": len(expected_images), "vector_file_id": next(iter(file_ids)),
                                      "index_migration_id": migration_id}
            for mapping in mappings:
                filename = Path(mapping.image_path).name
                if filename in image_chunks:
                    mapping.chunk_index = image_chunks[filename]
            await db.commit()
        except Exception:
            await db.rollback()
            restore_points(client, backup)
            raise
        (backup_dir / "result.json").write_text(json.dumps({**summary, "status": "completed", "migration_id": migration_id}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"status": "completed", "backup": str(backup_path), "other_points_unchanged": True}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup-dir", type=Path, default=Path("backups"))
    parser.add_argument("--restore", type=Path)
    asyncio.run(main(parser.parse_args()))
