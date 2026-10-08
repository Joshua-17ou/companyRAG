"""
飞书开放平台客户端

最小闭环：生成授权链接 → code 换 user_access_token → 拉取用户信息。
另附 tenant_access_token（预留给后续部门/通讯录调用）。
"""
import time
from typing import Dict
from urllib.parse import quote, urlencode

import httpx

from src.backend.core.logger import logger
from src.backend.lark.config import lark_settings

LARK_BASE = "https://open.feishu.cn"
LARK_ACCOUNTS = "https://accounts.feishu.cn"

_app_token_cache: Dict[str, object] = {"token": None, "expire_at": 0.0}


def build_authorize_url(state: str) -> str:
    """构造飞书 OAuth v2 授权链接，前端整页跳转"""
    if not lark_settings.lark_app_id or not lark_settings.lark_redirect_uri:
        raise RuntimeError("未配置 LARK_APP_ID / LARK_REDIRECT_URI")
    params = {
        "client_id": lark_settings.lark_app_id,
        "redirect_uri": lark_settings.lark_redirect_uri,
        "state": state,
    }
    return (
        f"{LARK_ACCOUNTS}/open-apis/authen/v1/authorize"
        f"?{urlencode(params, quote_via=quote)}"
    )


async def exchange_code(code: str) -> Dict:
    """用授权 code 换 user_access_token"""
    payload = {
        "grant_type": "authorization_code",
        "client_id": lark_settings.lark_app_id,
        "client_secret": lark_settings.lark_app_secret,
        "code": code,
        "redirect_uri": lark_settings.lark_redirect_uri,
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{LARK_BASE}/open-apis/authen/v2/oauth/token", json=payload
        )
        resp.raise_for_status()
        data = resp.json()

    if not data.get("access_token"):
        logger.error(f"飞书换取 token 失败: {data}")
        raise RuntimeError(
            data.get("error_description") or data.get("msg") or "换取 token 失败"
        )
    return data


async def get_user_info(user_access_token: str) -> Dict:
    """拉取用户信息（name/avatar_url/open_id/union_id/email?）"""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{LARK_BASE}/open-apis/authen/v1/user_info",
            headers={"Authorization": f"Bearer {user_access_token}"},
        )
        resp.raise_for_status()
        data = resp.json()

    if data.get("code") != 0:
        logger.error(f"获取飞书用户信息失败: {data}")
        raise RuntimeError(data.get("msg") or "获取用户信息失败")
    return data.get("data") or {}


async def get_app_access_token() -> str:
    """tenant_access_token（进程内缓存），预留给部门/通讯录调用"""
    now = time.time()
    if _app_token_cache["token"] and float(_app_token_cache["expire_at"]) > now:
        return str(_app_token_cache["token"])

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{LARK_BASE}/open-apis/auth/v3/app_access_token/internal",
            json={
                "app_id": lark_settings.lark_app_id,
                "app_secret": lark_settings.lark_app_secret,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    if data.get("code") != 0:
        logger.error(f"获取 tenant_access_token 失败: {data}")
        raise RuntimeError(data.get("msg") or "获取 tenant_access_token 失败")

    token = data.get("tenant_access_token")
    _app_token_cache["token"] = token
    _app_token_cache["expire_at"] = now + int(data.get("expire", 7200)) - 300
    return str(token)