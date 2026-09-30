"""
RAG问答Agent - 使用Claude进行多轮对话
基于Anthropic的Tool Use功能
"""
import json
import httpx
from typing import Optional
from anthropic import Anthropic

from src.backend.core.config import settings
from src.backend.core.logger import logger


class RAGQAAgent:
    """RAG问答Agent - 集成Claude和RAG服务"""

    def __init__(self, api_base: str = "http://127.0.0.1:8000", user_dept: str = None):
        """
        初始化Agent

        Args:
            api_base: RAG后端API地址
            user_dept: 用户所属部门（用于权限过滤）
        """
        self.api_base = api_base
        self.user_dept = user_dept  # 存储用户部门

        # 使用自定义API base如果配置了
        client_kwargs = {"api_key": settings.claude_api_key}
        if settings.claude_api_base:
            client_kwargs["base_url"] = settings.claude_api_base

        self.client = Anthropic(**client_kwargs)
        self.model = settings.claude_model_sonnet
        self.conversation_history = []

        # 会话记忆管理配置
        self.max_recent_turns = 3  # 保留最近3轮对话（6条消息：3个user + 3个assistant）
        self.conversation_summary = ""  # 历史对话摘要

        # 定义可用工具
        self.tools = [
            {
                "name": "search_documents",
                "description": "在RAG知识库中搜索相关文档",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "搜索查询文本"
                        },
                        "top_k": {
                            "type": "integer",
                            "description": "返回结果数量，默认为5",
                            "default": 5
                        }
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "generate_answer",
                "description": "根据问题从RAG系统生成答案（包括文档检索和LLM生成）",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "用户问题"
                        },
                        "top_k": {
                            "type": "integer",
                            "description": "检索文档数量，默认为3",
                            "default": 3
                        }
                    },
                    "required": ["query"]
                }
            }
        ]

    def search_documents(self, query: str, top_k: int = 5) -> dict:
        """调用后端搜索API"""
        try:
            with httpx.Client() as client:
                params = {"query": query, "top_k": top_k}
                if self.user_dept:
                    params["user_dept"] = self.user_dept  # 传递部门信息

                response = client.post(
                    f"{self.api_base}/api/search",
                    params=params,
                    timeout=30.0
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Search API call failed: {e}")
            return {"status": "error", "message": str(e)}

    def generate_answer(self, query: str, top_k: int = 3) -> dict:
        """调用后端QA API"""
        try:
            with httpx.Client() as client:
                params = {"query": query, "top_k": top_k}
                if self.user_dept:
                    params["user_dept"] = self.user_dept  # 传递部门信息

                response = client.post(
                    f"{self.api_base}/api/qa",
                    params=params,
                    timeout=30.0
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"QA API call failed: {e}")
            return {"status": "error", "message": str(e)}

    def process_tool_call(self, tool_name: str, tool_input: dict) -> str:
        """处理工具调用"""
        logger.info(f"Calling tool: {tool_name} with input: {tool_input}")

        if tool_name == "search_documents":
            result = self.search_documents(
                query=tool_input.get("query"),
                top_k=tool_input.get("top_k", 5)
            )
        elif tool_name == "generate_answer":
            result = self.generate_answer(
                query=tool_input.get("query"),
                top_k=tool_input.get("top_k", 3)
            )
        else:
            result = {"error": f"Unknown tool: {tool_name}"}

        return json.dumps(result, ensure_ascii=False, indent=2)

    def _compress_conversation_history(self):
        """
        压缩对话历史，保留最近N轮对话 + 更早对话的摘要

        策略：
        1. 如果对话历史超过max_recent_turns轮（user+assistant为1轮）
        2. 将更早的对话压缩为摘要
        3. 保留最近的对话完整内容
        """
        # 计算轮次（每轮 = 1个user消息 + 1个assistant响应）
        # 注意：工具调用也算在assistant响应中
        user_messages = [msg for msg in self.conversation_history if msg["role"] == "user"]

        # 需要保留的最近消息数（max_recent_turns轮 = max_recent_turns * 2条消息）
        messages_to_keep = self.max_recent_turns * 2

        # 如果历史消息不超过阈值，不需要压缩
        if len(self.conversation_history) <= messages_to_keep:
            return

        logger.info(f"会话历史达到 {len(self.conversation_history)} 条消息，开始压缩...")

        # 提取需要压缩的消息
        messages_to_summarize = self.conversation_history[:-messages_to_keep]
        recent_messages = self.conversation_history[-messages_to_keep:]

        # 构建摘要prompt
        summary_text = self._build_summary_text(messages_to_summarize)

        try:
            # 调用Claude生成摘要
            summary_response = self.client.messages.create(
                model=self.model,
                max_tokens=500,
                messages=[{
                    "role": "user",
                    "content": f"""请简洁地总结以下对话的关键信息，包括：
1. 用户主要询问了什么问题
2. 已经获得了哪些关键答案和结论
3. 任何重要的上下文信息

对话内容：
{summary_text}

请用3-5句话总结，重点关注对后续对话有用的信息。"""
                }]
            )

            # 提取摘要文本
            new_summary = ""
            for block in summary_response.content:
                if hasattr(block, "text"):
                    new_summary = block.text
                    break

            # 合并新旧摘要
            if self.conversation_summary:
                self.conversation_summary = f"{self.conversation_summary}\n\n{new_summary}"
            else:
                self.conversation_summary = new_summary

            # 重构对话历史：摘要 + 最近消息
            self.conversation_history = recent_messages

            logger.info(f"✅ 会话压缩完成，保留最近 {messages_to_keep} 条消息")
            logger.info(f"📝 当前摘要长度: {len(self.conversation_summary)} 字符")

        except Exception as e:
            logger.error(f"会话压缩失败: {e}")
            # 压缩失败时保持原样

    def _build_summary_text(self, messages: list) -> str:
        """构建用于摘要的文本"""
        lines = []
        for msg in messages:
            role = msg["role"]
            content = msg["content"]

            # 处理文本内容
            if isinstance(content, str):
                lines.append(f"{role}: {content[:300]}")  # 限制每条消息长度
            # 处理工具调用内容（简化）
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "tool_result":
                        continue  # 跳过工具结果细节
                    elif hasattr(item, "text"):
                        lines.append(f"{role}: {item.text[:300]}")

        return "\n".join(lines)

    def _get_messages_with_summary(self) -> list:
        """
        获取包含摘要的完整消息列表

        Returns:
            如果有摘要，在对话历史前添加系统消息；否则返回原始历史
        """
        if self.conversation_summary:
            summary_message = {
                "role": "user",
                "content": f"""[历史对话摘要]
{self.conversation_summary}

以上是之前对话的摘要。现在继续当前对话。"""
            }
            return [summary_message] + self.conversation_history
        else:
            return self.conversation_history

    def chat(self, user_message: str) -> dict:
        """
        多轮对话 - 返回思考过程和最终答案

        Args:
            user_message: 用户消息

        Returns:
            {
                "status": "success",
                "thoughts": [...],  # 完整的思考过程列表
                "answer": "最终答案",
                "is_final": True     # 标记是否是最终答案
            }
        """
        # 添加用户消息到历史
        self.conversation_history.append({
            "role": "user",
            "content": user_message
        })

        logger.info(f"User: {user_message}")

        # 在处理新消息前，检查是否需要压缩历史
        self._compress_conversation_history()

        thoughts = []
        max_iterations = 10
        iteration = 0

        # 保存来自generate_answer工具的sources和images
        tool_sources = []
        tool_images = []

        while iteration < max_iterations:
            iteration += 1

            # 获取包含摘要的完整消息列表
            messages_to_send = self._get_messages_with_summary()

            # 调用Claude
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2048,
                tools=self.tools,
                messages=messages_to_send
            )

            logger.info(f"Claude response (iteration {iteration}): stop_reason={response.stop_reason}")

            # 提取当前思考内容
            for block in response.content:
                if hasattr(block, "text") and block.text:
                    thoughts.append({
                        "step": iteration,
                        "type": "thinking",
                        "content": block.text,
                        "timestamp": iteration
                    })
                    logger.info(f"Thought: {block.text[:100]}...")

            # 如果Claude已做出决定（不再调用工具）
            if response.stop_reason == "end_turn":
                # 提取最终响应文本
                final_response = ""
                for block in response.content:
                    if hasattr(block, "text"):
                        final_response = block.text
                        break

                # 添加Assistant响应到历史
                self.conversation_history.append({
                    "role": "assistant",
                    "content": final_response
                })

                logger.info(f"Assistant: {final_response}")
                return {
                    "status": "success",
                    "thoughts": thoughts,
                    "answer": final_response,
                    "sources": tool_sources,
                    "images": tool_images,
                    "is_final": True
                }

            # 处理工具调用
            if response.stop_reason == "tool_use":
                # 添加Assistant响应（包含工具调用）到历史
                self.conversation_history.append({
                    "role": "assistant",
                    "content": response.content
                })

                # 处理所有工具调用
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        tool_name = block.name
                        tool_input = block.input

                        # 记录工具调用
                        thoughts.append({
                            "step": iteration,
                            "type": "tool_call",
                            "tool": tool_name,
                            "input": tool_input,
                            "timestamp": iteration
                        })
                        logger.info(f"Calling tool: {tool_name}")

                        tool_result = self.process_tool_call(tool_name, tool_input)

                        # 从工具结果中提取sources和images
                        if tool_name in ["generate_answer", "search_documents"]:
                            try:
                                result_data = json.loads(tool_result)

                                if tool_name == "search_documents":
                                    # 从搜索结果提取sources
                                    tool_sources = result_data.get("results", [])
                                    # 收集所有搜索结果中的图片
                                    all_images = []
                                    seen_images = set()
                                    for result in tool_sources:
                                        for img in result.get("images", []):
                                            img_path = img.get("path", "")
                                            if img_path and img_path not in seen_images:
                                                seen_images.add(img_path)
                                                all_images.append(img)
                                    tool_images = all_images

                                elif tool_name == "generate_answer":
                                    tool_sources = result_data.get("sources", [])
                                    tool_images = result_data.get("images", [])

                                logger.info(f"Extracted {len(tool_sources)} sources and {len(tool_images)} images from {tool_name}")
                            except Exception as e:
                                logger.error(f"Failed to extract sources/images: {e}")

                        # 记录工具结果摘要
                        result_preview = str(tool_result)[:500]
                        thoughts.append({
                            "step": iteration,
                            "type": "tool_result",
                            "tool": tool_name,
                            "content": result_preview,
                            "timestamp": iteration
                        })

                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": tool_result
                        })

                # 添加工具结果到历史
                self.conversation_history.append({
                    "role": "user",
                    "content": tool_results
                })
            else:
                # 未预期的stop_reason
                logger.warning(f"Unexpected stop_reason: {response.stop_reason}")
                break

        return {
            "status": "error",
            "thoughts": thoughts,
            "answer": "Agent达到最大迭代次数，无法生成完整响应",
            "is_final": False
        }

    def reset_conversation(self):
        """重置对话历史"""
        self.conversation_history = []
        self.conversation_summary = ""
        logger.info("Conversation history and summary reset")

    def get_conversation_stats(self) -> dict:
        """
        获取会话统计信息

        Returns:
            {
                "total_messages": 消息总数,
                "user_messages": 用户消息数,
                "assistant_messages": 助手消息数,
                "has_summary": 是否有历史摘要,
                "summary_length": 摘要长度
            }
        """
        user_count = sum(1 for msg in self.conversation_history if msg["role"] == "user")
        assistant_count = sum(1 for msg in self.conversation_history if msg["role"] == "assistant")

        return {
            "total_messages": len(self.conversation_history),
            "user_messages": user_count,
            "assistant_messages": assistant_count,
            "turns": user_count,  # 对话轮次
            "has_summary": bool(self.conversation_summary),
            "summary_length": len(self.conversation_summary) if self.conversation_summary else 0
        }
