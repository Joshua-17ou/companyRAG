"""
向量化模块
集成OpenAI Embedding API（使用同步客户端）
"""
from typing import List, Dict, Optional
import asyncio
import time

from openai import OpenAI

from src.backend.core.config import settings
from src.backend.core.logger import logger


class EmbeddingService:
    """向量化服务"""

    # 从配置读取模型名称，默认使用text-embedding-3-small
    # 支持中转站可能提供的其他embedding模型

    BATCH_SIZE = 25
    MAX_TOKENS_PER_REQUEST = 8000

    def __init__(self, model: str = None):
        """初始化OpenAI客户端"""
        # 支持传入自定义模型，或从配置读取
        self.model = model or settings.embedding_model or "text-embedding-3-small"

        if not settings.gpt4_api_key:
            logger.warning("GPT4_API_KEY not configured, embedding will fail")
            self.client = None
        else:
            # 配置中转站API
            self.client = OpenAI(
                api_key=settings.gpt4_api_key,
                base_url="https://api.sandboxai.top/v1"  # 中转站URL
            )

        logger.info(f"EmbeddingService initialized with model: {self.model} (relay: api.sandboxai.top)")

    async def embed_text(self, text: str) -> Optional[List[float]]:
        """为单个文本生成向量"""
        if not self.client:
            logger.error("OpenAI client not initialized")
            return None

        try:
            if not text or len(text.strip()) == 0:
                logger.warning("Empty text provided to embedding")
                return None

            text = text[:2000]

            response = self.client.embeddings.create(
                input=text,
                model=self.model
            )

            if response and response.data:
                embedding = response.data[0].embedding
                logger.debug(f"Embedded text ({len(text)} chars) -> {len(embedding)} dimensions")
                return embedding
            else:
                logger.error("Empty response from embedding API")
                return None

        except Exception as e:
            logger.error(f"Embedding failed: {e}")
            return None

    async def embed_texts_batch(self, texts: List[str]) -> List[Optional[List[float]]]:
        """批量向量化文本"""
        if not self.client:
            logger.error("OpenAI client not initialized")
            return [None] * len(texts)

        if not texts:
            return []

        embeddings = [None] * len(texts)

        try:
            for i in range(0, len(texts), self.BATCH_SIZE):
                batch = texts[i : i + self.BATCH_SIZE]
                batch = [t[:2000] if t else "" for t in batch]

                try:
                    response = self.client.embeddings.create(
                        input=batch,
                        model=self.model
                    )

                    if response and response.data:
                        for j, data in enumerate(response.data):
                            batch_idx = i + data.index
                            embeddings[batch_idx] = data.embedding

                        logger.info(f"Embedded batch {i // self.BATCH_SIZE + 1}: {len(batch)} texts")
                    else:
                        logger.error(f"Empty response for batch starting at {i}")

                except Exception as e:
                    logger.error(f"Batch embedding failed at {i}: {e}")
                    continue

                # 避免API速率限制
                await asyncio.sleep(0.1)

        except Exception as e:
            logger.error(f"Batch embedding failed: {e}")

        return embeddings

    @staticmethod
    def estimate_embedding_cost(num_texts: int, avg_chars_per_text: int = 500) -> Dict:
        """估算向量化成本"""
        tokens_per_text = int(avg_chars_per_text * 1.2)
        total_tokens = num_texts * tokens_per_text
        cost_usd = (total_tokens / 1_000_000) * 0.02

        return {
            "num_texts": num_texts,
            "total_tokens": total_tokens,
            "cost_usd": cost_usd,
            "cost_cents": int(cost_usd * 100)
        }


