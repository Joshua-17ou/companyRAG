"""
数据库连接管理
"""
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import text

from src.backend.core.config import settings
from src.backend.core.logger import logger

# 创建base类
Base = declarative_base()

# 使用asyncpg驱动（支持异步）
# 将 postgresql:// 改为 postgresql+asyncpg://
database_url = settings.database_url.replace("postgresql://", "postgresql+asyncpg://")

# 创建异步引擎
engine = create_async_engine(
    database_url,
    echo=settings.api_debug,
    future=True,
    pool_size=20,
    max_overflow=0
)

# 创建session工厂
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)

async def get_db():
    """获取数据库session"""
    async with AsyncSessionLocal() as session:
        yield session

async def init_db():
    """初始化数据库连接"""
    try:
        # 测试连接
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("数据库连接成功")
    except Exception as e:
        logger.error(f"数据库连接失败: {e}")
        raise

async def close_db():
    """关闭数据库连接"""
    await engine.dispose()
    logger.info("数据库连接已关闭")
