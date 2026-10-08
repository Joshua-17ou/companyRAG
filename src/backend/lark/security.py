"""
飞书登录态：JWT 签发与校验

JWT 通过 httpOnly Cookie 承载，同源下 SSE fetch 与 <img src> 会自动带上凭据。
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt

from src.backend.lark.config import lark_settings

# 飞书登录态 Cookie 名称
COOKIE_NAME = "lark_token"


def create_access_token(user_id: str, open_id: str) -> str:
    """签发登录态；sub=内部用户ID，oid=飞书 open_id"""
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=lark_settings.lark_jwt_expire_minutes
    )
    payload = {
        "sub": user_id,
        "oid": open_id,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(
        payload,
        lark_settings.lark_jwt_secret,
        algorithm=lark_settings.lark_jwt_algorithm,
    )


def decode_access_token(token: str) -> Optional[dict]:
    """校验登录态；无效或过期返回 None"""
    try:
        return jwt.decode(
            token,
            lark_settings.lark_jwt_secret,
            algorithms=[lark_settings.lark_jwt_algorithm],
        )
    except jwt.PyJWTError:
        return None


def extract_token(cookie_token: Optional[str], authorization: Optional[str]) -> Optional[str]:
    """Cookie 优先，回退 Authorization: Bearer <token>"""
    if cookie_token:
        return cookie_token
    auth = authorization or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None