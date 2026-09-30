#!/usr/bin/env python3
"""
诊断脚本 - 检查知识库是否可用
"""
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.backend.ingestion.rag_service import RAGService
from src.backend.core.logger import logger
import asyncio


async def diagnose():
    try:
        logger.info("=" * 70)
        logger.info("开始诊断知识库")
        logger.info("=" * 70)

        # 步骤1：初始化RAG服务
        logger.info("\n[步骤 1/4] 初始化RAG服务...")
        rag = RAGService()
        logger.info("✅ RAG服务初始化成功")

        # 步骤2：检查向量库统计
        logger.info("\n[步骤 2/4] 检查向量库统计...")
        stats = await rag.get_kb_stats()

        if stats["status"] == "success":
            logger.info(f"✅ 向量库统计成功")
            logger.info(f"  • 总chunks数: {stats.get('total_chunks', 0)}")
            logger.info(f"  • 向量维度: {stats.get('vector_size', 0)}")
        else:
            logger.error(f"❌ 统计失败: {stats.get('message')}")
            return False

        # 步骤3：测试搜索
        logger.info("\n[步骤 3/4] 测试搜索功能...")
        test_queries = [
            "中山三院",
            "出库单",
            "标签打印"
        ]

        for query in test_queries:
            try:
                result = await rag.search(query, top_k=3)
                if result["status"] == "success":
                    count = result.get("count", 0)
                    logger.info(f"  ✅ '{query}' → {count} 条结果")
                else:
                    logger.warning(f"  ⚠️ '{query}' → 搜索失败")
            except Exception as e:
                logger.error(f"  ❌ '{query}' → {str(e)}")
                return False

        # 步骤4：检查embedding维度
        logger.info("\n[步骤 4/4] 检查Embedding模型...")
        test_text = "测试文本"
        try:
            embedding = rag.index._embed_model.get_text_embedding(test_text)
            dim = len(embedding)
            logger.info(f"✅ Embedding模型正常")
            logger.info(f"  • 维度: {dim}")
            logger.info(f"  • 模型: BAAI/bge-small-zh")
        except Exception as e:
            logger.error(f"❌ Embedding模型错误: {e}")
            return False

        logger.info("\n" + "=" * 70)
        logger.info("✅ 诊断完成 - 知识库正常！")
        logger.info("=" * 70)
        return True

    except Exception as e:
        logger.error(f"诊断失败: {e}", exc_info=True)
        return False


if __name__ == "__main__":
    success = asyncio.run(diagnose())
    sys.exit(0 if success else 1)
