"""
知识库管理服务 - 独立的业务逻辑层
负责文件元数据管理、统计、删除等操作
"""
from typing import List, Dict, Optional
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, and_
from sqlalchemy.orm import selectinload

from src.backend.db.models import KnowledgeBaseFile, SearchLog, ImageMapping
from src.backend.core.logger import logger


class KnowledgeBaseService:
    """知识库管理服务"""

    def __init__(self, db_session: AsyncSession):
        """初始化服务"""
        self.db = db_session
        self.logger = logger

    async def save_file_record(
        self,
        filename: str,
        file_path: str,
        file_hash: str,
        file_size: int,
        total_chunks: int,
        image_count: int = 0,
        source_type: str = "document",
        hospital_name: Optional[str] = None,
        chunk_strategy: str = "character",
        chunk_strategy_version: Optional[str] = None,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
        metadata: Optional[Dict] = None,
        file_id: Optional[str] = None
    ) -> Dict:
        """保存文件记录到数据库

        Args:
            file_id: 可选的文件UUID。如果不提供，自动生成。用于与向量库保持一致。
        """
        try:
            self.logger.info(f"Saving file record: {filename} ({total_chunks} chunks, {image_count} images)")

            stmt = select(KnowledgeBaseFile).where(
                KnowledgeBaseFile.file_hash == file_hash
            )
            existing = await self.db.execute(stmt)
            existing_record = existing.scalars().first()
            if existing_record:
                if existing_record.status == "active":
                    self.logger.warning(f"File with hash {file_hash[:8]}... already exists")
                    return {
                        "status": "warning",
                        "message": "This file has already been ingested"
                    }
                existing_record.filename = filename
                existing_record.original_file_path = file_path
                existing_record.file_size = file_size
                existing_record.file_hash = file_hash
                existing_record.total_chunks = total_chunks
                existing_record.image_count = image_count
                existing_record.source_type = source_type
                existing_record.hospital_name = hospital_name
                existing_record.chunk_strategy = chunk_strategy
                existing_record.chunk_strategy_version = chunk_strategy_version
                existing_record.chunk_size = chunk_size
                existing_record.chunk_overlap = chunk_overlap
                existing_record.metadata_json = metadata
                existing_record.status = "active"
                existing_record.deleted_at = None
                await self.db.commit()
                return {"status": "success", "file_id": str(existing_record.id), "message": "File record restored"}

            # 如果提供了file_id，使用它；否则生成新的
            record_id = UUID(file_id) if file_id else uuid4()

            file_record = KnowledgeBaseFile(
                id=record_id,
                filename=filename,
                original_file_path=file_path,
                file_hash=file_hash,
                file_size=file_size,
                total_chunks=total_chunks,
                image_count=image_count,
                source_type=source_type,
                hospital_name=hospital_name,
                chunk_strategy=chunk_strategy,
                chunk_strategy_version=chunk_strategy_version,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                metadata_json=metadata,
                status='active'
            )

            self.db.add(file_record)
            await self.db.commit()
            await self.db.refresh(file_record)

            self.logger.info(f"File record saved: {file_record.id}")
            return {
                "status": "success",
                "file_id": str(file_record.id),
                "message": "File record saved"
            }

        except Exception as e:
            await self.db.rollback()
            self.logger.error(f"Failed to save file record: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    async def get_files_list(self, status: str = "active") -> Dict:
        """获取文件列表"""
        try:
            self.logger.info(f"Getting files list with status: {status}")

            stmt = select(KnowledgeBaseFile).where(
                KnowledgeBaseFile.status == status
            ).order_by(KnowledgeBaseFile.created_at.desc())

            result = await self.db.execute(stmt)
            files = result.scalars().all()

            file_list = [
                {
                    "id": str(f.id),
                    "filename": f.filename,
                    "file_size": f.file_size,
                    "chunks": f.total_chunks,
                    "created_at": f.created_at.isoformat() if f.created_at else None,
                    "status": f.status
                }
                for f in files
            ]

            return {
                "status": "success",
                "total_files": len(file_list),
                "files": file_list
            }

        except Exception as e:
            self.logger.error(f"Failed to get files list: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    async def delete_file(self, file_id: str) -> Dict:
        """删除文件记录（软删除）"""
        try:
            self.logger.info(f"Deleting file: {file_id}")

            file_uuid = UUID(file_id)
            stmt = select(KnowledgeBaseFile).where(
                KnowledgeBaseFile.id == file_uuid
            )
            result = await self.db.execute(stmt)
            file_record = result.scalars().first()

            if not file_record:
                return {
                    "status": "error",
                    "message": f"File not found: {file_id}"
                }

            if file_record.status == "deleted":
                return {
                    "status": "warning",
                    "message": "File is already deleted"
                }

            # 软删除：标记为deleted并记录删除时间
            update_stmt = (
                update(KnowledgeBaseFile)
                .where(KnowledgeBaseFile.id == file_uuid)
                .values(status="deleted", deleted_at=datetime.now())
            )
            await self.db.execute(update_stmt)
            await self.db.commit()

            self.logger.info(f"File deleted: {file_id}")
            return {
                "status": "success",
                "file_id": file_id,
                "message": "File deleted successfully"
            }

        except ValueError:
            return {"status": "error", "message": f"Invalid file ID format: {file_id}"}
        except Exception as e:
            await self.db.rollback()
            self.logger.error(f"Failed to delete file: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    async def get_stats(self) -> Dict:
        """获取知识库统计信息"""
        try:
            self.logger.info("Getting knowledge base statistics")

            # 统计活跃文件
            stmt_active = select(KnowledgeBaseFile).where(
                KnowledgeBaseFile.status == "active"
            )
            result = await self.db.execute(stmt_active)
            active_files = result.scalars().all()

            total_files = len(active_files)
            total_chunks = sum(f.total_chunks for f in active_files)
            total_size = sum(f.file_size for f in active_files)

            avg_chunks = total_chunks / total_files if total_files > 0 else 0

            stats = {
                "status": "success",
                "total_files": total_files,
                "total_chunks": total_chunks,
                "total_size_bytes": total_size,
                "total_size_mb": round(total_size / (1024 * 1024), 2),
                "avg_chunks_per_file": round(avg_chunks, 1),
                "avg_file_size_kb": round(total_size / (1024 * total_files), 1) if total_files > 0 else 0
            }

            self.logger.info(f"KB Stats: {total_files} files, {total_chunks} chunks")
            return stats

        except Exception as e:
            self.logger.error(f"Failed to get KB stats: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    async def get_file_by_id(self, file_id: str) -> Dict:
        """获取单个文件详情"""
        try:
            file_uuid = UUID(file_id)
            stmt = select(KnowledgeBaseFile).where(
                KnowledgeBaseFile.id == file_uuid
            )
            result = await self.db.execute(stmt)
            file_record = result.scalars().first()

            if not file_record:
                return {
                    "status": "error",
                    "message": f"File not found: {file_id}"
                }

            return {
                "status": "success",
                "file": {
                    "id": str(file_record.id),
                    "filename": file_record.filename,
                    "file_size": file_record.file_size,
                    "file_hash": file_record.file_hash,
                    "chunks": file_record.total_chunks,
                    "status": file_record.status,
                    "chunk_strategy": file_record.chunk_strategy,
                    "chunk_strategy_version": file_record.chunk_strategy_version,
                    "chunk_size": file_record.chunk_size,
                    "chunk_overlap": file_record.chunk_overlap,
                    "created_at": file_record.created_at.isoformat() if file_record.created_at else None,
                    "deleted_at": file_record.deleted_at.isoformat() if file_record.deleted_at else None
                }
            }

        except ValueError:
            return {"status": "error", "message": f"Invalid file ID format: {file_id}"}
        except Exception as e:
            self.logger.error(f"Failed to get file: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    async def save_image_mapping(
        self,
        file_id: str,
        image_path: str,
        chunk_index: Optional[int] = None,
        image_description: Optional[str] = None,
        image_url: Optional[str] = None
    ) -> Dict:
        """保存图片映射"""
        try:
            file_uuid = UUID(file_id)
            image_record = ImageMapping(
                source_file_id=file_uuid,
                image_path=image_path,
                chunk_index=chunk_index,
                image_description=image_description,
                image_url=image_url
            )
            self.db.add(image_record)
            await self.db.commit()
            return {"status": "success", "image_id": str(image_record.id)}
        except Exception as e:
            await self.db.rollback()
            self.logger.error(f"Failed to save image mapping: {e}")
            return {"status": "error", "message": str(e)}

    async def get_images_by_file(self, file_id: str) -> Dict:
        """根据文件ID获取所有关联的图片"""
        try:
            file_uuid = UUID(file_id)
            stmt = select(ImageMapping).where(
                ImageMapping.source_file_id == file_uuid
            ).order_by(ImageMapping.chunk_index)
            result = await self.db.execute(stmt)
            images = result.scalars().all()

            image_list = [
                {
                    "image_path": img.image_path,
                    "image_url": img.image_url,
                    "description": img.image_description,
                    "chunk_index": img.chunk_index
                }
                for img in images
            ]

            return {
                "status": "success",
                "total_images": len(image_list),
                "images": image_list
            }
        except Exception as e:
            self.logger.error(f"Failed to get images by file: {e}")
            return {"status": "error", "message": str(e)}

    async def log_search(
        self,
        query: str,
        result_count: int,
        image_count: int,
        response_time_ms: int,
        source_file_id: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> Dict:
        """记录搜索日志"""
        try:
            file_uuid = UUID(source_file_id) if source_file_id else None
            user_uuid = UUID(user_id) if user_id else None

            log_record = SearchLog(
                query=query,
                source_file_id=file_uuid,
                user_id=user_uuid,
                result_count=result_count,
                image_count=image_count,
                response_time_ms=response_time_ms
            )
            self.db.add(log_record)
            await self.db.commit()
            return {"status": "success"}
        except Exception as e:
            await self.db.rollback()
            self.logger.error(f"Failed to log search: {e}")
            return {"status": "error", "message": str(e)}

    async def get_file_stats_with_images(self) -> Dict:
        """获取知识库统计信息（包括图片统计）"""
        try:
            stmt_active = select(KnowledgeBaseFile).where(
                KnowledgeBaseFile.status == "active"
            )
            result = await self.db.execute(stmt_active)
            active_files = result.scalars().all()

            total_files = len(active_files)
            total_chunks = sum(f.total_chunks for f in active_files)
            total_images = sum(f.image_count for f in active_files)
            total_size = sum(f.file_size for f in active_files)

            avg_chunks = total_chunks / total_files if total_files > 0 else 0
            avg_images = total_images / total_files if total_files > 0 else 0

            stats = {
                "status": "success",
                "total_files": total_files,
                "total_chunks": total_chunks,
                "total_images": total_images,
                "total_size_bytes": total_size,
                "total_size_mb": round(total_size / (1024 * 1024), 2),
                "avg_chunks_per_file": round(avg_chunks, 1),
                "avg_images_per_file": round(avg_images, 1),
                "avg_file_size_kb": round(total_size / (1024 * total_files), 1) if total_files > 0 else 0,
                "files": [
                    {
                        "id": str(f.id),
                        "filename": f.filename,
                        "chunks": f.total_chunks,
                        "images": f.image_count,
                        "hospital": f.hospital_name,
                        "source_type": f.source_type,
                        "chunk_strategy": f.chunk_strategy,
                        "chunk_strategy_version": f.chunk_strategy_version,
                        "chunk_size": f.chunk_size,
                        "chunk_overlap": f.chunk_overlap,
                    }
                    for f in active_files
                ]
            }
            return stats
        except Exception as e:
            self.logger.error(f"Failed to get KB stats with images: {e}")
            return {"status": "error", "message": str(e)}
