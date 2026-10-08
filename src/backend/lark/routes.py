"""
飞书免登路由（前缀 /api/auth/lark）

1. GET  /authorize-url  返回飞书授权链接，并写入一次性 state Cookie
2. POST /exchange       用 code 换登录态，下发 httpOnly Cookie
3. GET  /me             读取当前登录用户
4. POST /logout         清除登录态
"""
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.core.logger import logger
from src.backend.db.database import get_db
from src.backend.db.models import User
from src.backend.lark import client
from src.backend.lark.config import lark_settings
from src.backend.lark.deps import get_current_lark_user, lark_email
from src.backend.lark.security import COOKIE_NAME, create_access_token

router = APIRouter(prefix="/lark", tags=["飞书免登"])

STATE_COOKIE = "lark_oauth_state"
STATE_MAX_AGE = 600


def _profile(user: User) -> dict:
    # email 是映射键（{open_id}@lark.local），不对外暴露
    return {
        "user_id": str(user.id),
        "name": user.name,
        "department": user.department,
        "role": user.role,
    }


@router.get("/authorize-url")
async def get_authorize_url(response: Response):
    """返回飞书授权链接，并写入一次性 state Cookie"""
    try:
        state = secrets.token_urlsafe(16)
        authorize_url = client.build_authorize_url(state)
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"飞书应用未正确配置: {e}",
        )

    response.set_cookie(
        key=STATE_COOKIE,
        value=state,
        max_age=STATE_MAX_AGE,
        httponly=True,
        secure=lark_settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return {"authorize_url": authorize_url}


@router.post("/exchange")
async def exchange(
    payload: dict,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """用授权 code 换取登录态"""
    code = (payload or {}).get("code")
    state = (payload or {}).get("state")
    expected_state = request.cookies.get(STATE_COOKIE)

    if not code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="缺少授权码 code")
    if not expected_state or state != expected_state:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="state 校验失败，请重新登录")

    try:
        token_data = await client.exchange_code(code)
        user_token = token_data.get("access_token")
        info = await client.get_user_info(user_token)
    except Exception as e:
        logger.error(f"飞书免登失败: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"飞书登录失败: {e}")

    open_id = info.get("open_id")
    if not open_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="飞书未返回 open_id")

    # 按映射键查找，没有则创建（复用原 users 表，不改表结构）
    email = lark_email(open_id)
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            name=info.get("name") or "飞书用户",
            email=email,
            department=lark_settings.lark_default_dept,
            role="user",
        )
        db.add(user)
    else:
        user.name = info.get("name") or user.name

    await db.commit()
    await db.refresh(user)

    token = create_access_token(str(user.id), open_id)
    response.delete_cookie(STATE_COOKIE, path="/")
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=lark_settings.lark_jwt_expire_minutes * 60,
        httponly=True,
        secure=lark_settings.cookie_secure,
        samesite="lax",
        path="/",
    )

    logger.info(f"飞书免登成功: {user.name}")
    return {"status": "success", "user": _profile(user)}


@router.get("/me")
async def me(user: User = Depends(get_current_lark_user)):
    """获取当前登录用户"""
    return {"status": "success", "user": _profile(user)}


@router.post("/logout")
async def logout(response: Response):
    """清除登录态"""
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"status": "success"}