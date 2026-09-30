"""
LlamaIndex RAG完整流程测试
"""
import asyncio
from src.backend.ingestion.rag_service import RAGService


async def test_llamaindex_rag():
    """LlamaIndex RAG流程测试"""

    print("="*80)
    print("LLAMAINDEX RAG WORKFLOW TEST")
    print("="*80)

    # 初始化
    print("\n[1] Initializing RAG Service...")
    rag = RAGService()
    print("✓ RAG Service ready")

    # 入库
    print("\n[2] Ingesting Document...")
    doc_path = "docs/销售_指南_医院送货检查指南.md"
    result = await rag.ingest_file(doc_path)
    print(f"✓ {result.get('message')}")

    # 搜索测试
    queries = [
        "医院出库单检验报告要求",
        "产品配送流程",
        "财务审批规则"
    ]

    print("\n[3] Testing Search & QA...")
    for query in queries:
        print(f"\n  Query: '{query}'")
        print("  " + "-"*70)

        # 搜索
        search_result = await rag.search(query, top_k=3)
        if search_result.get("status") == "success":
            results = search_result.get("results", [])
            print(f"  Found {len(results)} chunks:")
            for i, r in enumerate(results[:2], 1):
                print(f"    [{i}] {r['text'][:50]}...")

        # 生成答案
        print(f"\n  Generating answer...")
        qa_result = await rag.generate_answer(query, top_k=3)
        if qa_result.get("status") == "success":
            answer = qa_result.get("answer", "")
            print(f"  ✓ Answer:")
            for line in answer.split("\n")[:3]:
                print(f"    {line}")
            if len(answer.split("\n")) > 3:
                print(f"    ...")

            sources = qa_result.get("sources", [])
            if sources:
                print(f"\n  Sources:")
                for source in sources[:2]:
                    print(f"    - {source['text'][:50]}...")
        else:
            print(f"  ✗ Error: {qa_result.get('message')}")

    print("\n" + "="*80)
    print("TEST COMPLETED")
    print("="*80)


if __name__ == "__main__":
    print("Starting LlamaIndex RAG Test\n")
    asyncio.run(test_llamaindex_rag())
