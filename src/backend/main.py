"""
FastAPI 应用主入口
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from src.backend.core.config import settings
from src.backend.core.logger import logger
from src.backend.api.routes import health, permission, auth, ingestion, images, sessions
from src.backend.lark.install import install_lark
from src.backend.db.database import init_db, close_db
from src.backend.ingestion.rag_service import RAGService

import asyncio

async def load_docs_in_background():
    """后台加载文档任务"""
    try:
        logger.info("后台任务：开始加载docs目录文档...")
        rag_service = RAGService()

        result = await rag_service.auto_load_docs_directory()
        if result.get("total_chunks", 0) > 0:
            logger.info(f"✓ 成功加载 {result['total_chunks']} 个文档块到向量库")
        else:
            logger.info("docs目录为空或不存在")

        # 迁移现有的chunks到数据库
        logger.info("后台任务：迁移chunks到数据库...")
        db_session = None
        try:
            from src.backend.db.database import AsyncSessionLocal
            db_session = AsyncSessionLocal()
            migration_result = await rag_service.sync_existing_chunks_to_db(db_session)
            if migration_result.get("status") == "success":
                logger.info(
                    f"✓ 已迁移 {migration_result.get('synced_files', 0)} "
                    f"个文件到知识库管理系统"
                )
            else:
                logger.warning(f"迁移失败: {migration_result.get('message')}")
        finally:
            if db_session:
                await db_session.close()

        logger.info("✅ 后台文档加载任务完成")
    except Exception as e:
        logger.error(f"后台加载文档失败: {e}", exc_info=True)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动和关闭事件"""
    logger.info("应用启动中...")
    try:
        await init_db()
        logger.info("数据库已初始化")
    except Exception as e:
        logger.error(f"初始化数据库失败: {e}", exc_info=True)

    # 初始化RAG服务
    try:
        logger.info("初始化RAG服务...")
        rag_service = RAGService()
        logger.info("RAG服务已初始化")

        # 模型预热
        logger.info("开始模型预热...")
        warmup_result = await rag_service.generate_answer(
            query="测试",
            top_k=1,
            user_dept="公共",
            enable_intent=False
        )
        logger.info("✓ 模型预热完成")
    except Exception as e:
        logger.error(f"RAG服务初始化/预热失败: {e}", exc_info=True)

    logger.info("✅ 应用启动完成")

    yield

    logger.info("应用关闭中...")
    try:
        await close_db()
    except Exception as e:
        logger.error(f"关闭数据库失败: {e}", exc_info=True)

# 创建FastAPI应用
app = FastAPI(
    title="RAG 知识库系统",
    description="企业级RAG知识库系统API",
    version="1.0.0",
    lifespan=lifespan
)

# CORS配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 开发环境允许所有源
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 路由
app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(permission.router, prefix="/api/permission", tags=["permission"])
app.include_router(ingestion.router, prefix="/api", tags=["ingestion"])
app.include_router(images.router, prefix="/api", tags=["images"])
app.include_router(sessions.router, prefix="/api", tags=["sessions"])

# 飞书免登（LARK_ENABLED=false 时为空操作，不影响原网页版）
install_lark(app)

@app.get("/")
async def root():
    """根路由"""
    return {
        "message": "RAG 知识库系统 API",
        "version": "1.0.0",
        "docs": "/docs"
    }

@app.get("/health")
async def health():
    """健康检查（存活）"""
    return {"status": "ok"}

@app.get("/ready")
async def ready():
    """就绪检查：数据库可连通才返回 200，供网关与发布钩子判定"""
    from sqlalchemy import text
    from src.backend.db.database import AsyncSessionLocal
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
    except Exception as e:
        logger.error(f"就绪检查失败: {e}")
        raise HTTPException(status_code=503, detail="数据库不可用")
    return {"status": "ready"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.backend.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.api_debug,
        log_level="info"
    )
