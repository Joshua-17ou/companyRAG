"""
权限缓存引擎
基于Redis的用户权限集合缓存，支持TTL和主动失效
"""
import json
from typing import Optional, Dict, List
from uuid import UUID
import redis.asyncio as redis

from src.backend.core.config import settings
from src.backend.core.logger import logger

class PermissionCacheEngine:
    """权限缓存引擎"""

    def __init__(self):
        self.redis_url = settings.redis_url
        self.cache_ttl = settings.redis_cache_ttl
        self.redis_client = None

    async def connect(self):
        """连接Redis"""
        try:
            self.redis_client = await redis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True
            )
            await self.redis_client.ping()
            logger.info("Redis连接成功")
        except Exception as e:
            logger.error(f"Redis连接失败: {e}")
            raise

    async def disconnect(self):
        """断开Redis连接"""
        if self.redis_client:
            await self.redis_client.close()
            logger.info("Redis连接已关闭")

    async def get_user_permission_set(self, user_id: str) -> Optional[Dict]:
        """
        从缓存获取用户权限集合
        缓存key: user_perms:{user_id}
        """
        if not self.redis_client:
            return None

        try:
            cache_key = f"user_perms:{user_id}"
            cached_data = await self.redis_client.get(cache_key)

            if cached_data:
                logger.debug(f"权限缓存命中: {user_id}")
                return json.loads(cached_data)
            else:
                logger.debug(f"权限缓存未命中: {user_id}")
                return None
        except Exception as e:
            logger.error(f"获取权限缓存失败 ({user_id}): {e}")
            return None

    async def set_user_permission_set(self, user_id: str, permission_data: Dict) -> bool:
        """
        设置用户权限集合到缓存
        """
        if not self.redis_client:
            return False

        try:
            cache_key = f"user_perms:{user_id}"
            await self.redis_client.setex(
                cache_key,
                self.cache_ttl,
                json.dumps(permission_data)
            )
            logger.debug(f"权限缓存已设置: {user_id}")
            return True
        except Exception as e:
            logger.error(f"设置权限缓存失败 ({user_id}): {e}")
            return False

    async def invalidate_user_permission(self, user_id: str) -> bool:
        """
        主动失效用户权限缓存（用户权限变更时调用）
        """
        if not self.redis_client:
            return False

        try:
            cache_key = f"user_perms:{user_id}"
            result = await self.redis_client.delete(cache_key)
            logger.info(f"权限缓存已失效: {user_id}")
            return result > 0
        except Exception as e:
            logger.error(f"权限缓存失效失败 ({user_id}): {e}")
            return False

    async def warm_up_cache(self, user_permissions: List[Dict]) -> int:
        """
        缓存预热：批量导入用户权限
        用于项目启动或定期同步
        """
        if not self.redis_client:
            return 0

        success_count = 0
        try:
            for perm_data in user_permissions:
                user_id = str(perm_data.get("user_id"))
                if await self.set_user_permission_set(user_id, perm_data):
                    success_count += 1
            logger.info(f"权限缓存预热完成: {success_count}/{len(user_permissions)}")
            return success_count
        except Exception as e:
            logger.error(f"权限缓存预热失败: {e}")
            return success_count

    async def get_cache_stats(self) -> Dict:
        """获取缓存统计信息"""
        if not self.redis_client:
            return {}

        try:
            info = await self.redis_client.info()
            keys_count = await self.redis_client.dbsize()
            return {
                "memory_usage": info.get("used_memory_human", "N/A"),
                "total_keys": keys_count,
                "connected_clients": info.get("connected_clients", 0)
            }
        except Exception as e:
            logger.error(f"获取缓存统计失败: {e}")
            return {}

# 全局缓存引擎实例
permission_cache = PermissionCacheEngine()
