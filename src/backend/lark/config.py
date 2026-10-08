"""
飞书模块独立配置

刻意不并入 core/config.py：保持解耦，原网页版不感知飞书配置。
"""
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LarkSettings(BaseSettings):
    """飞书免登配置（读取同一份 .env）"""

    # 总开关：false 时飞书模块完全不生效
    lark_enabled: bool = False

    # 飞书开放平台「企业自建应用」凭证
    lark_app_id: Optional[str] = None
    lark_app_secret: Optional[str] = None

    # 必须与飞书后台「安全设置-重定向 URL」完全一致，例如 https://域名/auth/callback
    lark_redirect_uri: Optional[str] = None

    # 飞书暂无部门时的默认部门（配合 rag_service 的「全员」短路实现全员可见）
    lark_default_dept: str = "全员"

    # 登录态 Cookie 是否仅 HTTPS 传输；本地 http 调试需设 false
    cookie_secure: bool = True

    # 登录态 JWT（本模块自签自验，与原网页版无关）
    lark_jwt_secret: str = "dev-secret-key"
    lark_jwt_algorithm: str = "HS256"
    lark_jwt_expire_minutes: int = Field(default=1440, ge=5)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


lark_settings = LarkSettings()