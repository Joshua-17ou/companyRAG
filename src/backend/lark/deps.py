"""
飞书模块公共依赖与身份映射约定
"""
from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.core.logger import logger
from src.backend.db.database import get_db
from src.backend.db.models import User
from src.backend.lark.security import COOKIE_NAME, decode_access_token, extract_token


def lark_email(open_id: str) -> str:
    """
    飞书身份 → users.email 的映射键。

    复用原有 users 表而不新增字段：飞书用户不保证有邮箱，
    因此用 `{open_id}@lark.local` 作为唯一、可反查的邮箱。
    """
    return f"{open_id}@lark.local"


def lark_session_dept(open_id: str) -> str:
    """
    飞书会话归属命名空间。

    复用 chat_sessions.user_dept 实现「按用户私有」：
    每个飞书用户一个独立命名空间，与原网页版的部门值（销售/财务/行政）天然隔离。
    """
    return f"lark:{open_id}"


async def get_current_lark_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """从 Cookie/Bearer 解析登录态并返回用户；失败一律 401"""
    token = extract_token(
        request.cookies.get(COOKIE_NAME),
        request.headers.get("Authorization"),
    )
    payload = decode_access_token(token) if token else None
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未登录或登录已过期",
        )

    try:
        user_id = UUID(payload["sub"])
    except (KeyError, ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的登录凭证",
        )

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        logger.warning(f"飞书登录态对应的用户不存在: {user_id}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在",
        )
    return user


def current_open_id(request: Request) -> Optional[str]:
    """从 Cookie/Bearer 取出 open_id（守卫中间件已校验签名）"""
    token = extract_token(
        request.cookies.get(COOKIE_NAME),
        request.headers.get("Authorization"),
    )
    payload = decode_access_token(token) if token else None
    return (payload or {}).get("oid")