"""
认证相关路由
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import timedelta
import json

from src.backend.db.database import get_db
from src.backend.db.models import User, UserPermissionCache
from src.backend.core.permission_cache import permission_cache
from src.backend.core.config import settings
from src.backend.core.logger import logger

router = APIRouter()

@router.post("/login")
async def login(email: str, db: AsyncSession = Depends(get_db)):
    """
    测试用登录接口
    实际项目中应使用真正的认证（如LDAP/SSO）
    """
    try:
        # 查询用户
        stmt = select(User).where(User.email == email)
        result = await db.execute(stmt)
        user = result.scalars().first()

        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="用户不存在"
            )

        # 获取用户权限缓存
        user_perms = await permission_cache.get_user_permission_set(str(user.id))

        if not user_perms:
            # 从数据库重建权限信息
            stmt = select(UserPermissionCache).where(
                UserPermissionCache.user_id == user.id
            )
            result = await db.execute(stmt)
            cache_record = result.scalars().first()

            if cache_record:
                user_perms = {
                    "user_id": str(user.id),
                    "name": user.name,
                    "email": user.email,
                    "department": user.department,
                    "roles": json.loads(cache_record.roles or "[]"),
                    "projects": json.loads(cache_record.projects or "[]"),
                    "max_security_level": cache_record.max_security_level
                }
                # 写入缓存
                await permission_cache.set_user_permission_set(str(user.id), user_perms)
            else:
                # 构建默认权限信息
                user_perms = {
                    "user_id": str(user.id),
                    "name": user.name,
                    "email": user.email,
                    "department": user.department,
                    "roles": [user.role],
                    "projects": [],
                    "max_security_level": user.max_security_level
                }

        logger.info(f"用户登录成功: {email}")

        return {
            "status": "success",
            "user_id": str(user.id),
            "email": user.email,
            "name": user.name,
            "department": user.department,
            "role": user.role,
            "permissions": user_perms
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"登录失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="登录失败"
        )

@router.get("/user/{user_id}/permissions")
async def get_user_permissions(user_id: str, db: AsyncSession = Depends(get_db)):
    """获取用户权限信息"""
    try:
        # 先查缓存
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
                "departments": json.loads(cache_record.departments or "[]"),
                "roles": json.loads(cache_record.roles or "[]"),
                "projects": json.loads(cache_record.projects or "[]"),
                "max_security_level": cache_record.max_security_level
            }

            # 写入缓存
            await permission_cache.set_user_permission_set(user_id, user_perms)

        logger.info(f"获取用户权限: {user_id}")

        return {
            "status": "success",
            "user_id": user_id,
            "permissions": user_perms
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取用户权限失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取权限失败"
        )
