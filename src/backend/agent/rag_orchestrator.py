"""受控的有限状态 RAG 编排器。"""
from dataclasses import dataclass, field
from enum import Enum
from typing import AsyncGenerator, Dict, List, Optional

from src.backend.core.config import settings
from src.backend.core.logger import logger
from src.backend.ingestion.chat_fallback import NO_RESULTS, greeting_answer, source_excerpt_answer
from src.backend.ingestion.hospital_mapping import find_hospital_in_text


class RAGAgentState(str, Enum):
    START = "start"
    RULE_CHECK = "rule_check"
    RETRIEVE_PRIMARY = "retrieve_primary"
    EVIDENCE_GATE = "evidence_gate"
    RECOVER_SEARCH = "recover_search"
    ANSWER = "answer"
    CLARIFY = "clarify"
    DONE = "done"


@dataclass
class RAGAgentContext:
    query: str
    history: List[Dict]
    user_dept: Optional[str]
    transitions: List[str] = field(default_factory=list)
    retrieval_attempts: int = 0
    recovery_reason: Optional[str] = None
    search_result: Optional[Dict] = None
    detected_hospital: Optional[str] = None
    clarified: bool = False


class RAGOrchestrator:
    """用确定性状态机控制检索次数和答案生成次数。"""

    def __init__(self, rag_service):
        self.rag_service = rag_service

    async def stream(
        self,
        query: str,
        user_dept: str = None,
        history_context: list = None,
        top_k: int = 3,
        enable_intent: bool = True,
    ) -> AsyncGenerator[Dict, None]:
        context = RAGAgentContext(
            query=query.strip(),
            history=history_context or [],
            user_dept=user_dept,
        )

        self._transition(context, RAGAgentState.START)
        self._transition(context, RAGAgentState.RULE_CHECK)

        if not context.query:
            yield self._complete(
                context,
                "请补充你想查询的问题。",
                fallback=True,
                reason="empty_query",
            )
            return

        greeting = greeting_answer(context.query)
        if greeting:
            yield self._complete(context, greeting, sources=[], images=[])
            return

        context.detected_hospital = find_hospital_in_text(context.query)
        yield {"type": "thinking", "content": "正在判断问题范围..."}

        self._transition(context, RAGAgentState.RETRIEVE_PRIMARY)
        context.retrieval_attempts += 1
        yield {"type": "thinking", "content": "正在执行第 1 次知识检索..."}
        context.search_result = await self.rag_service.search(
            context.query,
            top_k=top_k,
            user_dept=user_dept,
            enable_intent=enable_intent,
            conversation_history=context.history,
        )

        if context.search_result.get("status") == "error":
            yield {"type": "error", "content": "知识库检索失败，请稍后重试。"}
            return

        self._transition(context, RAGAgentState.EVIDENCE_GATE)
        if not self._has_sufficient_evidence(context.search_result):
            if context.retrieval_attempts < settings.rag_agent_max_retrieval_attempts:
                self._transition(context, RAGAgentState.RECOVER_SEARCH)
                context.recovery_reason = self._evidence_failure_reason(context.search_result)
                context.retrieval_attempts += 1
                yield {
                    "type": "thinking",
                    "content": "当前证据不足，正在扩大检索范围...",
                }
                context.search_result = await self.rag_service.search(
                    context.query,
                    top_k=max(top_k, settings.rag_agent_recovery_top_k),
                    user_dept=user_dept,
                    enable_intent=False,
                    conversation_history=context.history,
                )
                if context.search_result.get("status") == "error":
                    yield {"type": "error", "content": "知识库恢复检索失败，请稍后重试。"}
                    return
                self._transition(context, RAGAgentState.EVIDENCE_GATE)

        if not context.search_result.get("results"):
            if self._should_clarify(context):
                self._transition(context, RAGAgentState.CLARIFY)
                context.clarified = True
                yield self._complete(
                    context,
                    "请补充具体医院名称或业务步骤，我会据此重新检索相关操作资料。",
                    fallback=True,
                    reason="clarification_required",
                )
            else:
                yield self._complete(
                    context,
                    NO_RESULTS,
                    fallback=True,
                    reason="no_results",
                )
            return

        if not self._has_sufficient_evidence(context.search_result):
            chunks = [
                self.rag_service._normalize_image_links(item.get("text", ""))
                for item in context.search_result.get("results", [])
                if (item.get("text") or "").strip()
            ]
            yield self._complete(
                context,
                source_excerpt_answer(chunks, "insufficient_evidence"),
                sources=self._build_sources(context.search_result),
                images=self._collect_images(context.search_result),
                fallback=True,
                reason="insufficient_evidence",
            )
            return

        self._transition(context, RAGAgentState.ANSWER)
        yield {
            "type": "search_complete",
            "found_count": len(context.search_result.get("results", [])),
        }
        yield {"type": "thinking", "content": "证据已准备，正在生成答案..."}

        async for event in self.rag_service.generate_answer_stream(
            query=context.query,
            top_k=top_k,
            user_dept=user_dept,
            enable_intent=False,
            history_context=context.history,
            search_result=context.search_result,
        ):
            if event["type"] == "search_complete":
                continue
            if event["type"] in {"answer", "answer_complete"}:
                self._transition(context, RAGAgentState.DONE)
                event["diagnostics"] = self._diagnostics(
                    context,
                    event.get("diagnostics"),
                )
            yield event

    def _has_sufficient_evidence(self, search_result: Dict) -> bool:
        results = search_result.get("results") or []
        if len(results) < settings.rag_agent_min_results:
            return False
        if not any((item.get("text") or "").strip() for item in results):
            return False
        threshold = settings.rag_agent_min_score
        if threshold is None:
            return True
        scores = [item.get("score") for item in results]
        numeric_scores = [score for score in scores if isinstance(score, (int, float))]
        return bool(numeric_scores) and max(numeric_scores) >= threshold

    def _evidence_failure_reason(self, search_result: Dict) -> str:
        results = search_result.get("results") or []
        if not results:
            return "no_results"
        if len(results) < settings.rag_agent_min_results:
            return "insufficient_results"
        if not any((item.get("text") or "").strip() for item in results):
            return "empty_evidence"
        return "low_score"

    def _should_clarify(self, context: RAGAgentContext) -> bool:
        if not settings.rag_agent_clarify_on_missing_hospital:
            return False
        if context.detected_hospital:
            return False
        hospital_terms = ("医院", "院内", "该院", "本院")
        return any(term in context.query for term in hospital_terms)

    def _build_sources(self, search_result: Dict) -> List[Dict]:
        sources = []
        for index, result in enumerate(search_result.get("results", [])[:3], 1):
            metadata = result.get("metadata", {})
            sources.append({
                "rank": index,
                "text": result.get("text", "")[:200],
                "score": result.get("score", 0.0),
                "filename": metadata.get("source", "未知"),
                "hospital": metadata.get("hospital", "未知医院"),
                "metadata": metadata,
                "images": result.get("images", []),
            })
        return sources

    def _collect_images(self, search_result: Dict) -> List[Dict]:
        images = []
        seen = set()
        for result in search_result.get("results", []):
            for image in result.get("images", []):
                key = image.get("url") or image.get("path")
                if key and key not in seen:
                    seen.add(key)
                    images.append(image)
        return images

    def _transition(self, context: RAGAgentContext, state: RAGAgentState) -> None:
        context.transitions.append(state.value)
        logger.info(
            "RAG agent transition: state=%s attempts=%s",
            state.value,
            context.retrieval_attempts,
        )

    def _diagnostics(self, context: RAGAgentContext, model_diagnostics=None) -> Dict:
        diagnostics = dict(model_diagnostics or {})
        diagnostics.update({
            "agent_mode": "agent",
            "state": context.transitions[-1] if context.transitions else RAGAgentState.DONE.value,
            "transitions": list(context.transitions),
            "retrieval_attempts": context.retrieval_attempts,
            "recovery_reason": context.recovery_reason,
            "clarified": context.clarified,
        })
        return diagnostics

    def _complete(
        self,
        context: RAGAgentContext,
        content: str,
        sources=None,
        images=None,
        fallback: bool = False,
        reason: Optional[str] = None,
    ) -> Dict:
        if reason and not context.recovery_reason:
            context.recovery_reason = reason
        self._transition(context, RAGAgentState.DONE)
        return {
            "type": "answer_complete",
            "content": content,
            "sources": sources or [],
            "images": images or [],
            "fallback": fallback,
            "diagnostics": self._diagnostics(context),
        }
