import unittest
from unittest.mock import AsyncMock, Mock, patch

from src.backend.agent.rag_orchestrator import RAGOrchestrator


class RAGOrchestratorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.service = Mock()
        self.service.search = AsyncMock()
        self.service._normalize_image_links.side_effect = lambda text: text
        self.orchestrator = RAGOrchestrator(self.service)

    async def collect(self, query="SPD流程", **kwargs):
        return [
            event
            async for event in self.orchestrator.stream(
                query,
                user_dept="销售",
                history_context=[],
                **kwargs,
            )
        ]

    async def test_greeting_skips_search_and_generation(self):
        events = await self.collect("你好")

        self.assertEqual(events[-1]["type"], "answer_complete")
        self.assertEqual(events[-1]["diagnostics"]["retrieval_attempts"], 0)
        self.service.search.assert_not_awaited()
        self.service.generate_answer_stream.assert_not_called()

    async def test_high_evidence_generates_once(self):
        result = {
            "status": "success",
            "results": [
                {"text": "步骤一", "score": 0.9, "metadata": {}, "images": []},
                {"text": "步骤二", "score": 0.8, "metadata": {}, "images": []},
            ],
        }
        self.service.search.return_value = result

        async def answer_stream(**kwargs):
            yield {"type": "answer_chunk", "content": "答案"}
            yield {
                "type": "answer_complete",
                "content": "答案",
                "sources": [],
                "images": [],
                "fallback": False,
                "diagnostics": {"request_id": "test"},
            }

        self.service.generate_answer_stream = answer_stream
        events = await self.collect()

        self.assertEqual(self.service.search.await_count, 1)
        completed = events[-1]
        self.assertEqual(completed["content"], "答案")
        self.assertEqual(completed["diagnostics"]["retrieval_attempts"], 1)
        self.assertIn("answer", completed["diagnostics"]["transitions"])

    async def test_single_valid_result_generates_answer(self):
        self.service.search.return_value = {
            "status": "success",
            "results": [{"text": "完整医院流程", "score": 0.9, "metadata": {}, "images": []}],
        }

        async def answer_stream(**kwargs):
            yield {
                "type": "answer_complete",
                "content": "整理后的答案",
                "sources": [],
                "images": [],
                "fallback": False,
                "diagnostics": None,
            }

        self.service.generate_answer_stream = answer_stream
        events = await self.collect("番禺中心医院出库流程")

        self.assertEqual(self.service.search.await_count, 1)
        self.assertEqual(events[-1]["content"], "整理后的答案")
        self.assertFalse(events[-1]["fallback"])

    async def test_low_evidence_recovers_once_without_repeating_intent(self):
        weak = {
            "status": "success",
            "results": [{"text": "片段", "score": 0.1, "metadata": {}, "images": []}],
        }
        strong = {
            "status": "success",
            "results": [
                {"text": "步骤一", "score": 0.9, "metadata": {}, "images": []},
                {"text": "步骤二", "score": 0.8, "metadata": {}, "images": []},
            ],
        }
        self.service.search.side_effect = [weak, strong]

        async def answer_stream(**kwargs):
            yield {
                "type": "answer_complete",
                "content": "恢复后的答案",
                "sources": [],
                "images": [],
                "fallback": False,
                "diagnostics": None,
            }

        self.service.generate_answer_stream = answer_stream
        with patch("src.backend.agent.rag_orchestrator.settings.rag_agent_min_results", 2):
            events = await self.collect()

        self.assertEqual(self.service.search.await_count, 2)
        first, second = self.service.search.await_args_list
        self.assertTrue(first.kwargs["enable_intent"])
        self.assertFalse(second.kwargs["enable_intent"])
        self.assertEqual(first.kwargs["user_dept"], second.kwargs["user_dept"])
        self.assertEqual(events[-1]["diagnostics"]["retrieval_attempts"], 2)
        self.assertEqual(events[-1]["diagnostics"]["recovery_reason"], "insufficient_results")

    async def test_persistently_weak_evidence_uses_source_fallback(self):
        weak = {
            "status": "success",
            "results": [{
                "text": "仅有一个片段",
                "score": 0.1,
                "metadata": {"source": "流程.md"},
                "images": [],
            }],
        }
        self.service.search.side_effect = [weak, weak]

        with patch("src.backend.agent.rag_orchestrator.settings.rag_agent_min_results", 2):
            events = await self.collect()
        completed = events[-1]

        self.assertEqual(self.service.search.await_count, 2)
        self.assertTrue(completed["fallback"])
        self.assertIn("原文资料", completed["content"])
        self.assertEqual(completed["sources"][0]["filename"], "流程.md")
        self.service.generate_answer_stream.assert_not_called()

    async def test_source_fallback_normalizes_image_urls(self):
        weak = {
            "status": "success",
            "results": [{
                "text": "步骤\n![图片](images/step.png)",
                "score": 0.1,
                "metadata": {"source": "流程.md"},
                "images": [{"url": "/api/images/step.png"}],
            }],
        }
        self.service.search.side_effect = [weak, weak]
        self.service._normalize_image_links.side_effect = (
            lambda text: text.replace("(images/", "(/api/images/")
        )

        with patch("src.backend.agent.rag_orchestrator.settings.rag_agent_min_results", 2):
            events = await self.collect()

        self.assertIn("![图片](/api/images/step.png)", events[-1]["content"])

    async def test_missing_hospital_clarifies_after_bounded_search(self):
        empty = {"status": "success", "results": []}
        self.service.search.side_effect = [empty, empty]

        with patch("src.backend.agent.rag_orchestrator.settings.rag_agent_clarify_on_missing_hospital", True):
            events = await self.collect("医院SPD入库怎么做")

        completed = events[-1]
        self.assertTrue(completed["fallback"])
        self.assertTrue(completed["diagnostics"]["clarified"])
        self.assertIn("医院名称", completed["content"])
        self.assertEqual(self.service.search.await_count, 2)
        self.service.generate_answer_stream.assert_not_called()


if __name__ == "__main__":
    unittest.main()
