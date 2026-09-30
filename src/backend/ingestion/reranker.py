"""
本地 Rerank 模型封装
使用 BAAI/bge-reranker-base 进行精排
"""
import os
from typing import List, Tuple
from sentence_transformers import CrossEncoder
from src.backend.core.logger import logger
from src.backend.core.config import settings


class LocalReranker:
    """本地 BGE Reranker 模型"""

    def __init__(self, model_path: str = None):
        """
        初始化 Reranker

        Args:
            model_path: 模型路径，默认从配置读取
        """
        self.model_path = model_path or settings.rerank_model_path

        if not os.path.exists(self.model_path):
            logger.warning(f"Rerank model not found at {self.model_path}, rerank disabled")
            self.model = None
            return

        try:
            logger.info(f"Loading rerank model from {self.model_path}")
            self.model = CrossEncoder(self.model_path, max_length=512)
            logger.info("Rerank model loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load rerank model: {e}")
            self.model = None

    def rerank(self, query: str, documents: List[str], top_k: int = 5) -> List[Tuple[int, float]]:
        """
        对检索结果重新排序

        Args:
            query: 查询文本
            documents: 文档列表
            top_k: 返回前 k 个结果

        Returns:
            [(doc_index, score), ...] 按分数降序排列
        """
        if not self.model or not documents:
            # 如果模型未加载或无文档，返回原始顺序
            return [(i, 1.0) for i in range(min(top_k, len(documents)))]

        try:
            # 构建查询-文档对
            pairs = [[query, doc] for doc in documents]

            # 计算相关性分数
            scores = self.model.predict(pairs)

            # 排序并返回 top_k
            ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
            return ranked[:top_k]

        except Exception as e:
            logger.error(f"Rerank failed: {e}")
            # 降级：返回原始顺序
            return [(i, 1.0) for i in range(min(top_k, len(documents)))]
