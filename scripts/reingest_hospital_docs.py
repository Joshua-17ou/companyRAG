#!/usr/bin/env python3
"""
重新入库医院相关文档脚本
1. 清空向量库
2. 按医院级别规则重新入库两份文档
"""
import asyncio
import sys
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.backend.ingestion.rag_service import RAGService
from src.backend.core.logger import logger


async def main():
    """主函数"""
    try:
        # 初始化RAG服务
        logger.info("=" * 60)
        logger.info("开始重新入库医院文档流程")
        logger.info("=" * 60)

        rag = RAGService()

        # 步骤1: 清空向量库
        logger.info("\n[步骤 1/3] 清空向量库...")
        clear_result = await rag.clear_vector_store()
        if clear_result["status"] != "success":
            logger.error(f"清空向量库失败: {clear_result['message']}")
            return

        logger.info("✓ 向量库已清空")

        # 步骤2: 入库第一份文档
        logger.info("\n[步骤 2/3] 入库文档 1: 医院随货同行复核资料...")
        doc1_path = project_root / "docs" / "销售_指南_医院送货检查指南.md"

        if not doc1_path.exists():
            logger.error(f"文档不存在: {doc1_path}")
            return

        result1 = await rag.ingest_file(str(doc1_path), use_hospital_parser=True)

        if result1["status"] == "success":
            logger.info(f"✓ 文档 1 入库成功: {result1['chunks']} chunks")
            logger.info(f"  文件哈希: {result1['file_hash'][:16]}...")
        else:
            logger.error(f"文档 1 入库失败: {result1['message']}")
            return

        # 步骤3: 入库第二份文档
        logger.info("\n[步骤 3/3] 入库文档 2: 医院SPD操作指南...")
        doc2_path = project_root / "docs" / "销售_指南_SPD操作指南.md"

        if not doc2_path.exists():
            logger.error(f"文档不存在: {doc2_path}")
            return

        result2 = await rag.ingest_file(str(doc2_path), use_hospital_parser=True)

        if result2["status"] == "success":
            logger.info(f"✓ 文档 2 入库成功: {result2['chunks']} chunks")
            logger.info(f"  文件哈希: {result2['file_hash'][:16]}...")
        else:
            logger.error(f"文档 2 入库失败: {result2['message']}")
            return

        # 步骤4: 获取统计信息
        logger.info("\n[统计信息]")
        stats = await rag.get_kb_stats()
        if stats["status"] == "success":
            logger.info(f"✓ 知识库总chunks数: {stats['total_chunks']}")
            logger.info(f"  向量维度: {stats.get('vector_size', 'N/A')}")

        logger.info("\n" + "=" * 60)
        logger.info("✓ 重新入库流程完成!")
        logger.info("=" * 60)
        logger.info(f"入库统计:")
        logger.info(f"  - 文档 1: {result1['chunks']} chunks")
        logger.info(f"  - 文档 2: {result2['chunks']} chunks")
        logger.info(f"  - 总计: {result1['chunks'] + result2['chunks']} chunks")

    except Exception as e:
        logger.error(f"流程失败: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
