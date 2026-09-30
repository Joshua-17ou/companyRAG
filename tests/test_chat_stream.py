import json
import unittest
from unittest.mock import AsyncMock, Mock, patch

from llama_index.core.schema import Document
from src.backend.ingestion.rag_service import RAGService
from src.backend.ingestion.hospital_parser import HospitalDocumentParser
from src.backend.api.routes import ingestion


class AnswerStreamTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.service = object.__new__(RAGService)
        self.service.search = AsyncMock(return_value={"status": "success", "results": []})

    def test_normalize_image_links_consumes_existing_image_marker(self):
        normalized = self.service._normalize_image_links("步骤\n![出库单](images/step.png)")
        self.assertEqual(normalized, "步骤\n![出库单](/api/images/step.png)")
        self.assertNotIn("!![", normalized)

    def test_normalize_plain_image_link_adds_single_marker(self):
        normalized = self.service._normalize_image_links("[出库单](images/step.png)")
        self.assertEqual(normalized, "![出库单](/api/images/step.png)")

    async def test_greetings_skip_search(self):
        for query in ["hello", "你好！"]:
            events = [event async for event in self.service.generate_answer_stream(query)]
            self.assertEqual(events[-1]["type"], "answer_complete")
            self.assertTrue(events[-1]["content"].strip())
            response = await self.service.generate_answer(query)
            self.assertTrue(response["answer"].strip())
        self.service.search.assert_not_awaited()

    async def test_no_results_completes_with_visible_answer(self):
        events = [event async for event in self.service.generate_answer_stream("未知流程")]
        self.assertEqual(events[0], {"type": "search_complete", "found_count": 0})
        self.assertEqual(events[-1]["type"], "answer_complete")
        self.assertIn("未找到", events[-1]["content"])

    async def test_search_error_is_not_no_results(self):
        self.service.search.return_value = {"status": "error", "message": "test failure"}
        events = [event async for event in self.service.generate_answer_stream("SPD")]
        self.assertEqual(events[0]["type"], "error")
        self.assertEqual((await self.service.generate_answer("SPD"))["status"], "error")

    async def test_stream_fallback_keeps_retrieved_source(self):
        self.service.search.return_value = {
            "status": "success",
            "results": [{
                "text": "SPD 原文步骤",
                "score": 0.9,
                "metadata": {"source": "流程.md", "hospital": "肇庆市一"},
                "images": [{"url": "https://example.invalid/step.png"}],
            }],
        }
        diagnostics = Mock()
        diagnostics.succeeded = False
        diagnostics.failure_reason = "length"
        diagnostics.to_dict.return_value = {
            "finish_reason": "length",
            "fallback_reason": "length",
        }

        async def fake_chunks(messages, settings, current, streaming=True):
            current.error_type = "LengthError"
            current.finish_reason = "length"
            if False:
                yield ""

        with patch("src.backend.ingestion.rag_service.settings.llm_provider", "deepseek"), \
             patch("src.backend.ingestion.rag_service.settings.deepseek_api_key", "test-key"), \
             patch("src.backend.ingestion.rag_service.deepseek_answer_chunks", fake_chunks):
            events = [event async for event in self.service.generate_answer_stream("SPD")]

        completed = events[-1]
        self.assertEqual(completed["type"], "answer_complete")
        self.assertTrue(completed["fallback"])
        self.assertIn("原文资料，非生成答案", completed["content"])
        self.assertTrue(completed["images"])

    async def test_non_stream_reuses_provided_search_result(self):
        search_result = {
            "status": "success",
            "results": [{
                "text": "SPD 原文步骤",
                "score": 0.9,
                "metadata": {"source": "流程.md", "hospital": "肇庆市一"},
                "images": [],
            }],
        }
        diagnostics = Mock()
        diagnostics.succeeded = False
        diagnostics.failure_reason = "error"
        diagnostics.to_dict.return_value = {"fallback_reason": "error"}

        async def fake_chunks(messages, settings, current, streaming=False):
            current.error_type = "TimeoutError"
            if False:
                yield ""

        with patch("src.backend.ingestion.rag_service.settings.llm_provider", "deepseek"), \
             patch("src.backend.ingestion.rag_service.settings.deepseek_api_key", "test-key"), \
             patch("src.backend.ingestion.rag_service.deepseek_answer_chunks", fake_chunks):
            result = await self.service.generate_answer("SPD", search_result=search_result)

        self.service.search.assert_not_awaited()
        self.assertTrue(result["fallback"])
        self.assertIn("原文资料，非生成答案", result["answer"])
        self.assertEqual(result["sources"][0]["filename"], "流程.md")

    async def test_hospital_filter_is_applied_inside_retrieval(self):
        self.service.intent_agent = Mock()
        self.service.intent_agent.process = AsyncMock(return_value={
            "processed_query": "SPD流程", "intent": {"intent": "general"}, "hospital": "肇庆市第一人民医院"
        })
        self.service.reranker = None
        self.service.index = Mock()
        self.service.index.as_retriever.return_value.retrieve.return_value = []
        result = await RAGService.search(self.service, "肇庆市一SPD流程")
        self.assertEqual(result["status"], "success")
        filters = self.service.index.as_retriever.call_args.kwargs["filters"]
        self.assertEqual(filters.filters[0].key, "hospital")
        self.assertEqual(filters.filters[0].value, "肇庆市一")

    def test_local_hospital_matching_prefers_longest_name(self):
        from src.backend.ingestion.hospital_mapping import find_hospital_in_text

        self.assertEqual(find_hospital_in_text("番禺中心spd流程"), "番禺中心医院")
        self.assertEqual(find_hospital_in_text("佛山市南海区人民医院流程"), "佛山市南海区人民医院")
        self.assertIsNone(find_hospital_in_text("SPD通用流程"))

    async def route_events(self, chunks, db=None, session_id=None, mode=None, agent_enabled=False):
        async def generate(**kwargs):
            for chunk in chunks:
                yield chunk
        with patch.object(ingestion, "RAGService") as service, \
             patch.object(ingestion.settings, "rag_agent_enabled", agent_enabled):
            service.return_value.generate_answer_stream = generate
            response = await ingestion.stream_qa(
                question="test", session_id=session_id, mode=mode or "simple", db=db
            )
            return [json.loads(frame.removeprefix("data: ").strip()) async for frame in response.body_iterator]

    async def test_agent_route_preserves_existing_sse_contract(self):
        chunks = [
            {"type": "thinking", "content": "正在扩大检索范围..."},
            {"type": "answer_chunk", "content": "答案"},
            {
                "type": "answer_complete",
                "content": "答案",
                "sources": [{"filename": "流程.md"}],
                "images": [],
                "fallback": False,
                "diagnostics": {"agent_mode": "agent", "retrieval_attempts": 2},
            },
        ]

        async def agent_stream(*args, **kwargs):
            for chunk in chunks:
                yield chunk

        with patch.object(ingestion, "RAGService"), \
             patch.object(ingestion, "RAGOrchestrator") as orchestrator, \
             patch.object(ingestion.settings, "rag_agent_enabled", True):
            orchestrator.return_value.stream = agent_stream
            response = await ingestion.stream_qa(question="test", mode="agent", db=None)
            events = [
                json.loads(frame.removeprefix("data: ").strip())
                async for frame in response.body_iterator
            ]

        self.assertTrue(any(event["type"] == "thinking" for event in events))
        self.assertEqual(events[-2]["type"], "answer")
        self.assertEqual(events[-2]["diagnostics"]["agent_mode"], "agent")
        self.assertEqual(events[-1]["type"], "done")

    async def test_agent_mode_requires_feature_flag(self):
        with patch.object(ingestion.settings, "rag_agent_enabled", False):
            with self.assertRaises(Exception) as raised:
                await ingestion.stream_qa(question="test", mode="agent", db=None)
        self.assertEqual(raised.exception.status_code, 400)

    async def test_route_accepts_legacy_and_completed_answers(self):
        for event_type in ["answer", "answer_complete"]:
            events = await self.route_events([{"type": event_type, "content": "未找到相关内容"}])
            self.assertEqual(events[-2]["type"], "answer")
            self.assertEqual(events[-2]["content"], "未找到相关内容")
            self.assertEqual(events[-1]["type"], "done")

    async def test_route_empty_and_error_are_terminal(self):
        for chunks in [[], [{"type": "error", "content": "检索失败"}]]:
            events = await self.route_events(chunks)
            self.assertEqual(events[-2]["type"], "error")
            self.assertEqual(events[-1]["type"], "done")
            self.assertFalse(any(event["type"] == "answer" for event in events))

    async def test_fallback_answer_is_visible_but_not_persisted(self):
        db = Mock()
        db.execute = AsyncMock(return_value=Mock())
        db.execute.return_value.scalars.return_value.all.return_value = []
        db.commit = AsyncMock()
        chunks = [{
            "type": "answer_complete",
            "content": "**原文资料，非生成答案**\n\nSPD 原文步骤",
            "sources": [{"filename": "流程.md"}],
            "images": [{"url": "step.png"}],
            "fallback": True,
            "diagnostics": {"fallback_reason": "length"},
        }]
        events = await self.route_events(
            chunks, db=db, session_id="00000000-0000-0000-0000-000000000001"
        )
        answer = events[-2]
        self.assertEqual(answer["type"], "answer")
        self.assertTrue(answer["fallback"])
        self.assertIn("原文资料", answer["content"])
        db.add.assert_not_called()
        db.commit.assert_not_awaited()

    async def test_blank_answer_is_not_persisted(self):
        db = Mock()
        db.execute = AsyncMock(return_value=Mock())
        db.execute.return_value.scalars.return_value.all.return_value = []
        db.commit = AsyncMock()
        events = await self.route_events([], db=db, session_id="00000000-0000-0000-0000-000000000001")
        self.assertEqual(events[-2]["type"], "error")
        self.assertEqual(events[-2]["content"], "未收到有效答案，请重试。")
        db.add.assert_not_called()
        db.commit.assert_not_awaited()


class HospitalParserTests(unittest.TestCase):
    def test_boundaries_aliases_and_images(self):
        image = "![操作](images/123456789012345678901234.png)"
        text = "## 肇庆市一\n" + "一" * 75 + image + "一" * 50 + "\n## 肇庆市二【新】\n二院步骤"
        nodes = HospitalDocumentParser.parse_documents_by_hospital([Document(text=text, metadata={"owner_dept": "销售"})], chunk_size=90, chunk_overlap=20)
        first = [node for node in nodes if node.metadata["hospital"] == "肇庆市一"]
        second = [node for node in nodes if node.metadata["hospital"] == "肇庆市二"]
        self.assertTrue(first and second)
        self.assertTrue(any(image in node.text for node in first))
        self.assertTrue(all("二院" not in node.text for node in first))
        for node in nodes:
            self.assertEqual(node.metadata["owner_dept"], "销售")
            self.assertIsNotNone(node.ref_doc_id)
            if "images/" in node.text:
                self.assertIn(image, node.text)
                self.assertEqual(len(node.metadata["image_paths"]), 1)

    def test_invalid_overlap(self):
        with self.assertRaises(ValueError):
            HospitalDocumentParser.split_hospital_content("test", chunk_size=10, chunk_overlap=10)


if __name__ == "__main__":
    unittest.main()
