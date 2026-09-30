"""
权限检查和测试路由
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Dict
import json
import time

from src.backend.db.database import get_db
from src.backend.db.models import User, UserPermissionCache
from src.backend.core.permission_cache import permission_cache
from src.backend.core.permission_filter import PermissionFilterEngine
from src.backend.core.logger import logger

router = APIRouter()

@router.post("/check")
async def check_permission(
    user_id: str,
    chunk_payload: Dict,
    db: AsyncSession = Depends(get_db)
):
    """
    检查用户是否有权访问某个chunk
    """
    try:
        # 获取用户权限
        user_perms = await permission_cache.get_user_permission_set(user_id)

        if not user_perms:
            # 从数据库查询
            stmt = select(UserPermissionCache).where(
                UserPermissionCache.user_id == user_id
            )
            result = await db.execute(stmt)
            cache_record = result.scalars().first()

            if not cache_record:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="用户权限信息不存在"
                )

            user_perms = {
                "user_id": user_id,
                "department": None,  # 需要从用户表查询
                "roles": json.loads(cache_record.roles or "[]"),
                "projects": json.loads(cache_record.projects or "[]"),
                "max_security_level": cache_record.max_security_level
            }

            # 补充部门信息
            stmt = select(User).where(User.id == user_id)
            result = await db.execute(stmt)
            user = result.scalars().first()
            if user:
                user_perms["department"] = user.department

        # 验证权限上下文
        if not PermissionFilterEngine.validate_permission_context(user_perms):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="权限上下文不完整"
            )

        # 检查权限
        has_permission, rule_name = PermissionFilterEngine.check_permission_rules(
            user_perms,
            chunk_payload
        )

        logger.info(f"权限检查: {user_id} -> {chunk_payload.get('doc_id', 'N/A')} = {has_permission}")

        return {
            "status": "success",
            "user_id": user_id,
            "has_permission": has_permission,
            "matched_rule": rule_name,
            "chunk_id": chunk_payload.get("chunk_id")
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"权限检查失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="权限检查失败"
        )

@router.post("/filter-chunks")
async def filter_chunks(
    user_id: str,
    chunks: List[Dict],
    top_k: int = 5,
    db: AsyncSession = Depends(get_db)
):
    """
    对chunks列表进行权限过滤
    """
    try:
        start_time = time.time()

        # 获取用户权限
        user_perms = await permission_cache.get_user_permission_set(user_id)

        if not user_perms:
            stmt = select(UserPermissionCache).where(
                UserPermissionCache.user_id == user_id
            )
            result = await db.execute(stmt)
            cache_record = result.scalars().first()

            if not cache_record:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="用户权限信息不存在"
                )

            user_perms = {
                "user_id": user_id,
                "department": None,
                "roles": json.loads(cache_record.roles or "[]"),
                "projects": json.loads(cache_record.projects or "[]"),
                "max_security_level": cache_record.max_security_level
            }

            # 补充部门信息
            stmt = select(User).where(User.id == user_id)
            result = await db.execute(stmt)
            user = result.scalars().first()
            if user:
                user_perms["department"] = user.department

        # 验证权限上下文
        if not PermissionFilterEngine.validate_permission_context(user_perms):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="权限上下文不完整"
            )

        # 过滤chunks
        filtered_chunks, stats = PermissionFilterEngine.filter_chunks_by_permission(
            user_perms,
            chunks,
            top_k
        )

        elapsed_ms = (time.time() - start_time) * 1000

        logger.info(
            f"Chunks过滤: {user_id} | "
            f"输入:{stats['total_input']} 输出:{stats['total_output']} | "
            f"耗时:{elapsed_ms:.2f}ms"
        )

        return {
            "status": "success",
            "user_id": user_id,
            "filtered_chunks": filtered_chunks,
            "stats": stats,
            "response_time_ms": elapsed_ms
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Chunks过滤失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="过滤失败"
        )

@router.post("/test/permission-performance")
async def test_permission_performance(
    user_id: str,
    mock_chunk_count: int = 1000,
    db: AsyncSession = Depends(get_db)
):
    """
    权限过滤性能测试
    生成Mock chunks，测试过滤性能和缓存命中率
    """
    try:
        # 生成Mock chunks
        mock_chunks = []
        for i in range(mock_chunk_count):
            chunk = {
                "chunk_id": f"chunk_{i:06d}",
                "doc_id": f"DOC-{i % 10:03d}",
                "payload": {
                    "security_level": (i % 4) + 1,
                    "owner_dept": ["销售部", "财务部", "行政部"][i % 3],
                    "visible_to_depts": ["销售部", "财务部"] if i % 2 == 0 else [],
                    "visible_to_roles": ["CEO", "总监"] if i % 3 == 0 else [],
                    "project_ids": [f"P{j}" for j in range(i % 3)],
                    "visible_to_users": []
                }
            }
            mock_chunks.append(chunk)

        # 第一次查询（缓存miss）
        start_time1 = time.time()
        user_perms1 = await permission_cache.get_user_permission_set(user_id)
        cache_miss_time1 = (time.time() - start_time1) * 1000

        if not user_perms1:
            stmt = select(UserPermissionCache).where(
                UserPermissionCache.user_id == user_id
            )
            result = await db.execute(stmt)
            cache_record = result.scalars().first()

            if not cache_record:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="用户权限信息不存在"
                )

            user_perms1 = {
                "user_id": user_id,
                "department": None,
                "roles": json.loads(cache_record.roles or "[]"),
                "projects": json.loads(cache_record.projects or "[]"),
                "max_security_level": cache_record.max_security_level
            }

            stmt = select(User).where(User.id == user_id)
            result = await db.execute(stmt)
            user = result.scalars().first()
            if user:
                user_perms1["department"] = user.department

            # 写入缓存
            await permission_cache.set_user_permission_set(user_id, user_perms1)

        # 性能测试
        start_time = time.time()
        filtered_chunks, stats = PermissionFilterEngine.filter_chunks_by_permission(
            user_perms1,
            mock_chunks,
            top_k=5
        )
        filter_time = (time.time() - start_time) * 1000

        # 第二次查询（缓存hit）
        start_time2 = time.time()
        user_perms2 = await permission_cache.get_user_permission_set(user_id)
        cache_hit_time2 = (time.time() - start_time2) * 1000

        logger.info(f"性能测试结果: {user_id} | 过滤耗时:{filter_time:.2f}ms | 缓存:{cache_hit_time2:.2f}ms")

        return {
            "status": "success",
            "user_id": user_id,
            "test_config": {
                "mock_chunk_count": mock_chunk_count
            },
            "performance": {
                "filter_time_ms": filter_time,
                "cache_miss_time_ms": cache_miss_time1,
                "cache_hit_time_ms": cache_hit_time2
            },
            "stats": stats
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"性能测试失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="性能测试失败"
        )
