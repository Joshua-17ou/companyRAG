"""
会话管理 API 路由
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, update
from typing import List
from uuid import UUID
import json

from src.backend.db.database import get_db
from src.backend.db.models import ChatSession, ChatMessage
from src.backend.core.logger import logger

router = APIRouter(prefix="/sessions", tags=["会话管理"])


@router.get("")
async def get_sessions(
    user_dept: str,
    limit: int = 50,
    db: AsyncSession = Depends(get_db)
):
    """
    获取用户的会话列表

    Args:
        user_dept: 用户部门
        limit: 返回数量限制
    """
    try:
        result = await db.execute(
            select(ChatSession)
            .where(ChatSession.user_dept == user_dept)
            .order_by(ChatSession.updated_at.desc())
            .limit(limit)
        )
        sessions = result.scalars().all()

        return {
            "status": "success",
            "sessions": [
                {
                    "id": str(session.id),
                    "title": session.title,
                    "created_at": session.created_at.isoformat(),
                    "updated_at": session.updated_at.isoformat(),
                }
                for session in sessions
            ]
        }
    except Exception as e:
        logger.error(f"获取会话列表失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("")
async def create_session(
    user_dept: str,
    title: str = "新对话",
    db: AsyncSession = Depends(get_db)
):
    """
    创建新会话

    Args:
        user_dept: 用户部门
        title: 会话标题
    """
    try:
        session = ChatSession(
            title=title,
            user_dept=user_dept
        )
        db.add(session)
        await db.commit()
        await db.refresh(session)

        return {
            "status": "success",
            "session": {
                "id": str(session.id),
                "title": session.title,
                "created_at": session.created_at.isoformat(),
                "updated_at": session.updated_at.isoformat(),
            }
        }
    except Exception as e:
        await db.rollback()
        logger.error(f"创建会话失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/{session_id}")
async def get_session(
    session_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """
    获取会话详情（包含所有消息）

    Args:
        session_id: 会话ID
    """
    try:
        result = await db.execute(
            select(ChatSession).where(ChatSession.id == session_id)
        )
        session = result.scalar_one_or_none()

        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="会话不存在"
            )

        # 获取消息
        messages_result = await db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at)
        )
        messages = messages_result.scalars().all()

        return {
            "status": "success",
            "session": {
                "id": str(session.id),
                "title": session.title,
                "created_at": session.created_at.isoformat(),
                "updated_at": session.updated_at.isoformat(),
            },
            "messages": [
                {
                    "id": str(msg.id),
                    "role": msg.role,
                    "content": msg.content,
                    "sources": msg.sources,
                    "images": msg.images,
                    "created_at": msg.created_at.isoformat(),
                }
                for msg in messages
            ]
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取会话详情失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.put("/{session_id}")
async def update_session(
    session_id: UUID,
    title: str,
    db: AsyncSession = Depends(get_db)
):
    """
    更新会话标题

    Args:
        session_id: 会话ID
        title: 新标题
    """
    try:
        result = await db.execute(
            update(ChatSession)
            .where(ChatSession.id == session_id)
            .values(title=title)
        )

        if result.rowcount == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="会话不存在"
            )

        await db.commit()

        return {"status": "success", "message": "标题已更新"}
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"更新会话失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.delete("/{session_id}")
async def delete_session(
    session_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """
    删除会话

    Args:
        session_id: 会话ID
    """
    try:
        result = await db.execute(
            delete(ChatSession).where(ChatSession.id == session_id)
        )

        if result.rowcount == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="会话不存在"
            )

        await db.commit()

        return {"status": "success", "message": "会话已删除"}
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"删除会话失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/{session_id}/messages")
async def add_message(
    session_id: UUID,
    role: str,
    content: str,
    sources: dict = None,
    images: dict = None,
    db: AsyncSession = Depends(get_db)
):
    """
    添加消息到会话

    Args:
        session_id: 会话ID
        role: 角色 (user/assistant)
        content: 消息内容
        sources: 来源文档
        images: 图片信息
    """
    try:
        # 检查会话是否存在
        result = await db.execute(
            select(ChatSession).where(ChatSession.id == session_id)
        )
        session = result.scalar_one_or_none()

        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="会话不存在"
            )

        # 添加消息
        message = ChatMessage(
            session_id=session_id,
            role=role,
            content=content,
            sources=sources,
            images=images
        )
        db.add(message)

        # 更新会话的 updated_at
        await db.execute(
            update(ChatSession)
            .where(ChatSession.id == session_id)
            .values(updated_at=message.created_at)
        )

        await db.commit()
        await db.refresh(message)

        return {
            "status": "success",
            "message": {
                "id": str(message.id),
                "role": message.role,
                "content": message.content,
                "created_at": message.created_at.isoformat(),
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"添加消息失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
