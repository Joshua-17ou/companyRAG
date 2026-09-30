import re


NO_RESULTS = "未找到与你的问题相关且有权限访问的知识库内容，请补充医院名称或具体业务步骤。"


def source_excerpt_answer(context_chunks, reason="empty"):
    descriptions = {
        "length": "模型输出达到长度限制，未获得完整答案。",
        "content_filter": "模型未能完成本次生成（内容过滤）。",
        "incomplete": "模型响应中断，未获得完整答案。",
        "error": "模型服务暂时不可用，未能生成答案。",
        "empty": "模型未返回有效的答案正文。",
    }
    heading = descriptions.get(reason, descriptions["empty"])
    excerpts = [text for text in context_chunks if text.strip()]
    if not excerpts:
        return f"{heading}\n\n{NO_RESULTS}"
    return (
        f"{heading}\n\n**原文资料，非生成答案**\n\n"
        "以下是本次检索到且你有权限查看的相关片段，可能只包含流程的一部分；图片保留在对应位置。\n\n"
        + "\n\n---\n\n".join(excerpts)
    )


def greeting_answer(query: str):
    normalized = re.sub(r"[\s，。！？,.!?]+", "", query).casefold()
    if normalized in {"hello", "hi", "hey", "你好", "您好", "你好呀", "在吗"}:
        return "你好！我可以帮你查询医院 SPD 操作流程和知识库资料，请告诉我医院名称及具体问题。"
    return None
