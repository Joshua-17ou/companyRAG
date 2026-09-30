"""
健康检查和系统状态路由
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from src.backend.db.database import get_db
from src.backend.core.permission_cache import permission_cache
from src.backend.core.logger import logger

router = APIRouter()

@router.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    """健康检查"""
    return {
        "status": "ok",
        "service": "RAG Knowledge Base System"
    }

@router.get("/health/detailed")
async def detailed_health_check(db: AsyncSession = Depends(get_db)):
    """详细的健康检查"""
    health_status = {}

    # 检查数据库
    try:
        result = await db.execute(text("SELECT 1"))
        health_status["database"] = "healthy"
    except Exception as e:
        logger.error(f"数据库检查失败: {e}")
        health_status["database"] = "unhealthy"

    # 检查Redis缓存
    try:
        if permission_cache.redis_client:
            await permission_cache.redis_client.ping()
            health_status["redis"] = "healthy"
        else:
            health_status["redis"] = "not_connected"
    except Exception as e:
        logger.error(f"Redis检查失败: {e}")
        health_status["redis"] = "unhealthy"

    # 获取缓存统计
    try:
        cache_stats = await permission_cache.get_cache_stats()
        health_status["cache_stats"] = cache_stats
    except Exception:
        health_status["cache_stats"] = {}

    overall_status = "healthy" if all(
        v == "healthy" for k, v in health_status.items() if k != "cache_stats"
    ) else "degraded"

    return {
        "overall_status": overall_status,
        "components": health_status
    }
