"""
意图识别与查询优化 Agent
负责：意图分类、问题重写、上下文补全
"""
import json
from typing import Dict, List, Optional
from openai import AsyncOpenAI

from src.backend.core.config import settings
from src.backend.core.logger import logger
from src.backend.ingestion.hospital_mapping import normalize_hospital_name
from src.backend.agent.prompts import (
    INTENT_CLASSIFICATION_PROMPT,
    QUERY_REWRITE_PROMPT,
    CONTEXT_COMPLETION_PROMPT,
    get_hospital_extraction_prompt
)
from src.backend.agent.prompts.context_prompts import format_conversation_history


class IntentAgent:
    """
    意图识别与查询优化 Agent

    功能：
    1. 意图分类 - 判断用户问题类型
    2. 问题重写 - 优化查询词
    3. 上下文补全 - 多轮对话中补全省略信息
    """

    def __init__(self):
        """初始化 IntentAgent"""
        self.client = AsyncOpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_api_base
        )
        self.model = "deepseek-v4-flash"
        logger.info("IntentAgent initialized")

    async def process(
        self,
        query: str,
        conversation_history: Optional[List[Dict]] = None,
        enable_rewrite: bool = True,
        enable_context: bool = True,
        enable_hospital_extraction: bool = True
    ) -> Dict:
        """
        完整的查询处理流程

        Args:
            query: 用户原始问题
            conversation_history: 对话历史
            enable_rewrite: 是否启用问题重写
            enable_context: 是否启用上下文补全
            enable_hospital_extraction: 是否启用医院识别

        Returns:
            {
                "original_query": "原始问题",
                "processed_query": "处理后的问题",
                "hospital": "肇庆市一" 或 None,
                "intent": {
                    "intent": "product_feature",
                    "doc_type": "手册",
                    "keywords": ["SPD", "功能"],
                    "confidence": 0.9
                },
                "rewrite": {"need_rewrite": True, ...},
                "context": {"need_completion": True, ...}
            }
        """
        result = {
            "original_query": query,
            "processed_query": query,
            "hospital": None,
            "intent": None,
            "rewrite": None,
            "context": None
        }

        current_query = query

        # 0. 医院识别（新增）
        if enable_hospital_extraction:
            try:
                hospital_result = await self.extract_hospital(query)
                result["hospital"] = hospital_result
                logger.info(f"Hospital extracted: {hospital_result}")
            except Exception as e:
                logger.warning(f"Hospital extraction failed: {e}")
                result["hospital"] = None

        # 1. 上下文补全（如果有对话历史）
        if enable_context and conversation_history:
            context_result = await self.complete_context(
                current_query,
                conversation_history
            )
            result["context"] = context_result

            if context_result and context_result.get("need_completion"):
                current_query = context_result["completed_query"]
                logger.info(f"Context completed: '{query}' → '{current_query}'")

        # 2. 问题重写
        if enable_rewrite:
            try:
                rewrite_result = await self.rewrite_query(current_query)
                result["rewrite"] = rewrite_result

                if rewrite_result and rewrite_result.get("need_rewrite"):
                    current_query = rewrite_result["rewritten_query"]
                    logger.info(f"Query rewritten: '{result.get('context', {}).get('completed_query', query)}' → '{current_query}'")
            except Exception as e:
                logger.warning(f"Query rewrite failed: {e}, using original query")
                result["rewrite"] = None

        result["processed_query"] = current_query

        # 3. 意图分类
        try:
            intent_result = await self.classify_intent(current_query)
            result["intent"] = intent_result
        except Exception as e:
            logger.warning(f"Intent classification failed: {e}, using fallback")
            result["intent"] = {
                "intent": "general",
                "doc_type": None,
                "keywords": [],
                "confidence": 0.0,
                "reasoning": "分类失败，使用默认值"
            }

        return result

    async def classify_intent(self, query: str) -> Dict:
        """
        意图分类

        Args:
            query: 查询文本

        Returns:
            {
                "intent": "product_feature",
                "doc_type": "手册",
                "keywords": ["SPD", "功能"],
                "confidence": 0.9,
                "reasoning": "用户询问产品功能"
            }
        """
        prompt = INTENT_CLASSIFICATION_PROMPT.format(query=query)

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3
            )

            response_text = response.choices[0].message.content.strip()

            # 提取 JSON
            response_text = self._extract_json(response_text)
            result = json.loads(response_text)

            logger.info(
                f"Intent classified: {result['intent']} "
                f"(confidence: {result.get('confidence', 0):.2f})"
            )

            return result

        except Exception as e:
            logger.warning(f"Intent classification failed: {e}, using fallback")
            return {
                "intent": "general",
                "doc_type": None,
                "keywords": [],
                "confidence": 0.0,
                "reasoning": "分类失败，使用默认值"
            }

    async def rewrite_query(self, query: str) -> Dict:
        """
        问题重写

        Args:
            query: 原始查询

        Returns:
            {
                "rewritten_query": "重写后的查询",
                "need_rewrite": true,
                "changes": "改动说明"
            }
        """
        # 简单规则：如果查询已经很标准，跳过 LLM 调用
        if len(query) > 10 and not self._needs_rewrite(query):
            return {
                "rewritten_query": query,
                "need_rewrite": False,
                "changes": "查询已足够清晰"
            }

        prompt = QUERY_REWRITE_PROMPT.format(query=query)

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3
            )

            response_text = response.choices[0].message.content.strip()
            response_text = self._extract_json(response_text)
            result = json.loads(response_text)

            if result.get("need_rewrite"):
                logger.info(f"Query rewrite: {result.get('changes', 'N/A')}")

            return result

        except Exception as e:
            logger.warning(f"Query rewrite failed: {e}, using original")
            return {
                "rewritten_query": query,
                "need_rewrite": False,
                "changes": "重写失败，保持原样"
            }

    async def complete_context(
        self,
        query: str,
        conversation_history: List[Dict]
    ) -> Dict:
        """
        上下文补全

        Args:
            query: 当前查询
            conversation_history: 对话历史

        Returns:
            {
                "completed_query": "补全后的问题",
                "need_completion": true,
                "original_topic": "SPD系统",
                "reasoning": "补全说明"
            }
        """
        # 简单规则：如果查询很完整，跳过 LLM 调用
        if not self._needs_context(query):
            return {
                "completed_query": query,
                "need_completion": False,
                "reasoning": "问题已完整"
            }

        # 格式化历史
        history_text = format_conversation_history(conversation_history, max_turns=3)

        prompt = CONTEXT_COMPLETION_PROMPT.format(
            conversation_history=history_text,
            current_query=query
        )

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3
            )

            response_text = response.choices[0].message.content.strip()
            response_text = self._extract_json(response_text)
            result = json.loads(response_text)

            if result.get("need_completion"):
                logger.info(f"Context completion: {result.get('reasoning', 'N/A')}")

            return result

        except Exception as e:
            logger.warning(f"Context completion failed: {e}, using original")
            return {
                "completed_query": query,
                "need_completion": False,
                "reasoning": "补全失败，保持原样"
            }

    def _extract_json(self, text: str) -> str:
        """从响应中提取 JSON"""
        if "```json" in text:
            return text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            return text.split("```")[1].split("```")[0].strip()
        return text

    def _needs_rewrite(self, query: str) -> bool:
        """判断是否需要重写（简单规则）"""
        # 包含口语词汇
        colloquial = ["咋", "啥", "咋整", "整啥", "咋弄"]
        if any(word in query for word in colloquial):
            return True

        # 过短
        if len(query) < 5:
            return True

        return False

    def _needs_context(self, query: str) -> bool:
        """判断是否需要上下文补全（简单规则）"""
        # 包含代词或省略
        pronouns = ["它", "这个", "那个", "呢", "还有呢", "详细", "具体"]
        return any(word in query for word in pronouns)

    async def extract_hospital(self, query: str) -> Optional[str]:
        """
        从查询中识别医院名称

        Args:
            query: 用户查询文本

        Returns:
            识别到的医院名称（标准化），如果没有识别到则返回 None
        """
        prompt = get_hospital_extraction_prompt(query)

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3
            )

            response_text = response.choices[0].message.content.strip()
            response_text = self._extract_json(response_text)
            result = json.loads(response_text)

            hospital = result.get("hospital")
            confidence = result.get("confidence", 0.0)

            if hospital:
                hospital = normalize_hospital_name(hospital)
                logger.info(f"Hospital identified: {hospital} (confidence: {confidence:.2f})")
            else:
                logger.info(f"No hospital identified in query")

            return hospital

        except Exception as e:
            logger.warning(f"Hospital extraction failed: {e}")
            return None
