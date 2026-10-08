"""
飞书模块装配入口

main.py 只需调用 install_lark(app)，开关判断全部收敛在这里：
- LARK_ENABLED=false（默认）：立即返回，原网页版行为完全不变
- LARK_ENABLED=true：注册飞书免登路由，并挂上「登录守卫 + 身份归一」中间件
"""
from urllib.parse import parse_qsl, urlencode

from src.backend.core.logger import logger
from src.backend.lark.config import lark_settings

# 需要登录态才能访问的业务接口
PROTECTED_PREFIXES = (
    "/api/qa",
    "/api/search",
    "/api/ingest",
    "/api/knowledge-base",
    "/api/images",
    "/api/pdf-page",
    "/api/sessions",
)

# 会话接口：身份取自令牌，按用户私有（lark:{open_id}）
SESSION_PREFIXES = ("/api/sessions",)

# 问答/检索接口：统一按默认部门（全员可见）
VISIBILITY_PREFIXES = ("/api/qa", "/api/search")


def _override_user_dept(query_string: bytes, dept: str) -> bytes:
    """把 query string 里的 user_dept 覆盖为服务端推导值（防前端伪造）"""
    pairs = parse_qsl(query_string.decode("utf-8"), keep_blank_values=True)
    filtered = [(k, v) for k, v in pairs if k != "user_dept"]
    filtered.append(("user_dept", dept))
    return urlencode(filtered).encode("utf-8")


def _resolve_dept(path: str, open_id: str) -> str:
    if path.startswith(SESSION_PREFIXES):
        return f"lark:{open_id}"
    if path.startswith(VISIBILITY_PREFIXES):
        return lark_settings.lark_default_dept
    return lark_settings.lark_default_dept


def install_lark(app) -> None:
    """按开关装配飞书模块"""
    if not lark_settings.lark_enabled:
        logger.info("LARK_ENABLED=false，飞书免登未启用（保持原网页版行为）")
        return

    # 延迟导入：未安装 PyJWT 时也不影响原网页版启动
    from starlette.responses import JSONResponse

    from src.backend.lark.routes import router as lark_router
    from src.backend.lark.security import (
        COOKIE_NAME,
        decode_access_token,
        extract_token,
    )

    app.include_router(lark_router, prefix="/api/auth", tags=["飞书免登"])

    @app.middleware("http")
    async def lark_guard(request, call_next):
        path = request.url.path
        if not path.startswith(PROTECTED_PREFIXES):
            return await call_next(request)

        token = extract_token(
            request.cookies.get(COOKIE_NAME),
            request.headers.get("Authorization"),
        )
        payload = decode_access_token(token) if token else None
        if not payload or not payload.get("oid"):
            return JSONResponse({"detail": "未登录或登录已过期"}, status_code=401)

        # 身份以令牌为准：覆盖前端传入的 user_dept，避免越权
        dept = _resolve_dept(path, str(payload["oid"]))
        request.scope["query_string"] = _override_user_dept(
            request.scope.get("query_string", b""), dept
        )
        return await call_next(request)

    logger.info(
        f"飞书免登已启用（默认部门={lark_settings.lark_default_dept}，"
        f"重定向={lark_settings.lark_redirect_uri}）"
    )