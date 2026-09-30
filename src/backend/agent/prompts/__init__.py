"""
提示词管理模块
集中管理所有 Agent 使用的提示词
"""

from .intent_prompts import INTENT_CLASSIFICATION_PROMPT, get_hospital_extraction_prompt
from .rewrite_prompts import QUERY_REWRITE_PROMPT
from .context_prompts import CONTEXT_COMPLETION_PROMPT
from .answer_prompts import ANSWER_GENERATION_PROMPT

__all__ = [
    'INTENT_CLASSIFICATION_PROMPT',
    'get_hospital_extraction_prompt',
    'QUERY_REWRITE_PROMPT',
    'CONTEXT_COMPLETION_PROMPT',
    'ANSWER_GENERATION_PROMPT',
]
