#!/usr/bin/env python3
"""
解析图片对照表并重新入库文档
将图片所属章节信息作为描述用于embedding
"""
import asyncio
import sys
from pathlib import Path
import json
import re

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.backend.ingestion.rag_service import RAGService
from src.backend.core.logger import logger


def parse_image_reference_table(table_path: str) -> dict:
    """
    解析图片对照表，返回 {图片路径: 所属章节描述}
    """
    image_descriptions = {}

    try:
        with open(table_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 使用正则表达式提取表格行
        # 格式: | 序号 | 图片文件 | 所属章节 | 原始链接 |
        lines = content.split('\n')

        for line in lines:
            # 跳过标题和分隔符
            if '|' not in line or '序号' in line or '---|' in line:
                continue

            # 分割表格单元格
            parts = [p.strip() for p in line.split('|')]

            # 过滤空的部分
            parts = [p for p in parts if p]

            # 应该有 4 个部分: 序号, 图片文件, 所属章节, 原始链接
            if len(parts) >= 3:
                image_file = parts[1].strip('`')  # 移除反引号
                chapter = parts[2]

                # 标准化图片路径
                if not image_file.startswith('images/'):
                    image_file = f'images/{image_file}'

                image_descriptions[image_file] = chapter
                logger.info(f"Mapped {image_file} -> {chapter[:50]}...")

        logger.info(f"Successfully parsed {len(image_descriptions)} image descriptions")
        return image_descriptions

    except Exception as e:
        logger.error(f"Failed to parse image reference table: {e}", exc_info=True)
        return {}


async def main():
    """主函数"""
    try:
        logger.info("=" * 70)
        logger.info("开始重新入库医院文档流程（使用图片对照表）")
        logger.info("=" * 70)

        # 初始化RAG服务
        rag = RAGService()

        # 步骤1: 解析图片对照表
        logger.info("\n[步骤 1/4] 解析图片对照表...")
        table_path = project_root / "docs" / "图片链接对照表.md"

        if not table_path.exists():
            logger.error(f"对照表不存在: {table_path}")
            return

        image_descriptions = parse_image_reference_table(str(table_path))
        logger.info(f"✓ 成功解析 {len(image_descriptions)} 张图片的描述信息")

        # 步骤2: 清空向量库
        logger.info("\n[步骤 2/4] 清空向量库...")
        clear_result = await rag.clear_vector_store()
        if clear_result["status"] != "success":
            logger.error(f"清空向量库失败: {clear_result['message']}")
            return

        logger.info("✓ 向量库已清空")

        # 步骤3: 入库第一份文档
        logger.info("\n[步骤 3/4] 入库文档 1: 医院随货同行复核资料...")
        doc1_path = project_root / "docs" / "销售_指南_医院送货检查指南.md"

        if not doc1_path.exists():
            logger.error(f"文档不存在: {doc1_path}")
            return

        result1 = await rag.ingest_file(str(doc1_path), use_hospital_parser=True)

        if result1["status"] == "success":
            logger.info(f"✓ 文档 1 入库成功: {result1['chunks']} chunks")
        else:
            logger.error(f"文档 1 入库失败: {result1['message']}")
            return

        # 步骤4: 入库第二份文档（使用图片描述）
        logger.info("\n[步骤 4/4] 入库文档 2: 医院SPD操作指南（含图片描述）...")
        doc2_path = project_root / "docs" / "销售_指南_SPD操作指南.md"

        if not doc2_path.exists():
            logger.error(f"文档不存在: {doc2_path}")
            return

        logger.info(f"使用 {len(image_descriptions)} 个图片描述增强embedding...")

        # 直接调用ingest_file，系统会自动使用医院分割器
        # 但我们需要一个修改版本来传入image_descriptions
        # 让我们读取文件并手动处理

        with open(doc2_path, 'r', encoding='utf-8') as f:
            content = f.read()

        file_hash = __import__('hashlib').sha256(content.encode()).hexdigest()
        file_id = str(__import__('uuid').uuid4())
        ingested_at = __import__('datetime').datetime.now().isoformat()

        from llama_index.core.schema import Document as LlamaIndexDoc
        from src.backend.ingestion.hospital_parser import HospitalDocumentParser

        doc = LlamaIndexDoc(
            text=content,
            metadata={
                "source": doc2_path.name,
                "file_path": str(doc2_path),
                "file_id": file_id,
                "file_hash": file_hash,
                "ingested_at": ingested_at
            }
        )

        # 使用图片描述来增强文档
        nodes = HospitalDocumentParser.parse_documents_by_hospital(
            documents=[doc],
            chunk_size=512,
            chunk_overlap=50,
            image_descriptions=image_descriptions
        )

        logger.info(f"Document split into {len(nodes)} chunks with image descriptions")

        # 增强metadata
        for i, node in enumerate(nodes):
            node.metadata.update({
                "file_id": file_id,
                "chunk_index": i,
                "total_chunks": len(nodes),
                "version": 1,
                "parser_type": "hospital"
            })

        # 计算embeddings并插入向量库
        logger.info("Computing embeddings and inserting into Qdrant...")
        rag.index.insert_nodes(nodes)
        logger.info(f"Successfully inserted {len(nodes)} chunks into vector store")

        result2 = {
            "status": "success",
            "file": doc2_path.name,
            "file_id": file_id,
            "file_hash": file_hash,
            "file_size": len(content),
            "chunks": len(nodes),
            "message": f"Successfully ingested {len(nodes)} chunks with image descriptions"
        }

        if result2["status"] == "success":
            logger.info(f"✓ 文档 2 入库成功: {result2['chunks']} chunks")
        else:
            logger.error(f"文档 2 入库失败: {result2['message']}")
            return

        # 步骤5: 获取统计信息
        logger.info("\n[统计信息]")
        stats = await rag.get_kb_stats()
        if stats["status"] == "success":
            logger.info(f"✓ 知识库总chunks数: {stats['total_chunks']}")
            logger.info(f"  向量维度: {stats.get('vector_size', 'N/A')}")

        logger.info("\n" + "=" * 70)
        logger.info("✓ 重新入库流程完成!")
        logger.info("=" * 70)
        logger.info(f"入库统计:")
        logger.info(f"  - 文档 1（规则库）: {result1['chunks']} chunks")
        logger.info(f"  - 文档 2（SPD指南，含{len(image_descriptions)}张图片描述）: {result2['chunks']} chunks")
        logger.info(f"  - 总计: {result1['chunks'] + result2['chunks']} chunks")
        logger.info(f"\n✓ 所有chunks现在包含了:")
        logger.info(f"  • 医院名称标签")
        logger.info(f"  • 图片路径信息（可用于展示原图）")
        logger.info(f"  • 图片所属章节描述（用于理解图片内容）")

    except Exception as e:
        logger.error(f"流程失败: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
