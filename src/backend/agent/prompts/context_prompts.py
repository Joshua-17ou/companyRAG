"""
上下文补全提示词
用于多轮对话中的问题补全
"""

CONTEXT_COMPLETION_PROMPT = """你是一个对话理解专家。根据对话历史，补全用户当前问题中省略的信息。

对话历史：
{conversation_history}

当前问题：{current_query}

任务：
1. 判断当前问题是否省略了主语或上下文
2. 如果省略了，根据对话历史补全
3. 如果没有省略，返回原始问题

补全规则：
- 如果问题是代词（它、这个、那个），替换为具体实体
- 如果问题缺少主语，从历史中找到最近的主题
- 如果问题是追问（呢、还有呢），补全完整问题
- 保持用户的原始意图，不要过度扩展

示例：
历史：用户："SPD系统有什么功能？"
     助手："SPD系统有入库、出库、库存管理等功能"
当前："价格呢？"
补全："SPD系统的价格是多少？"

历史：用户："出库流程是什么？"
     助手："出库流程包括..."
当前："详细步骤"
补全："出库流程的详细操作步骤是什么？"

返回 JSON 格式：
{{
    "completed_query": "补全后的问题",
    "need_completion": true,
    "original_topic": "SPD系统",
    "reasoning": "补全了省略的主语"
}}

如果不需要补全：
{{
    "completed_query": "原始问题",
    "need_completion": false,
    "reasoning": "问题已完整，无需补全"
}}
"""

def format_conversation_history(history: list, max_turns: int = 3) -> str:
    """
    格式化对话历史为字符串

    Args:
        history: 对话历史 [{"role": "user", "content": "..."}, ...]
        max_turns: 最多保留多少轮对话

    Returns:
        格式化的历史字符串
    """
    if not history:
        return "（无对话历史）"

    # 只取最近的 max_turns 轮
    recent_history = history[-(max_turns * 2):]

    formatted = []
    for msg in recent_history:
        role = "用户" if msg["role"] == "user" else "助手"
        content = msg["content"]

        # 简化内容，只保留前100字
        if isinstance(content, str) and len(content) > 100:
            content = content[:100] + "..."

        formatted.append(f"{role}：{content}")

    return "\n".join(formatted)
