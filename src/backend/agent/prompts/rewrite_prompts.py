"""
问题重写提示词
"""

QUERY_REWRITE_PROMPT = """你是一个查询优化专家。将用户的原始问题重写为更适合检索的标准化查询。

原始问题：{query}

重写规则：
1. **口语化转标准化**：将口语、方言转为正式表达
   - "出库咋整" → "出库流程操作步骤"
   - "spd啥功能" → "SPD系统功能介绍"

2. **补全缺失信息**：添加必要的上下文
   - "价格" → "SPD系统价格"
   - "怎么用" → "SPD系统使用方法"

3. **术语标准化**：使用行业标准术语
   - "库存" → "库存管理"
   - "出货" → "出库管理"

4. **明确查询意图**：
   - 如果问"是什么"，保留
   
   - 如果问"怎么做"，转为"流程"或"操作步骤"
   - 如果问"多少钱"，转为"价格"

5. **保持简洁**：不要添加冗余信息

判断是否需要重写：
- 如果原问题已经清晰、标准，直接返回原问题
- 如果有明显的口语化、缺失信息或歧义，进行重写

返回 JSON 格式：
{{
    "rewritten_query": "重写后的查询",
    "need_rewrite": true,
    "changes": "简要说明做了什么改动"
}}

如果不需要重写：
{{
    "rewritten_query": "原始问题",
    "need_rewrite": false,
    "changes": "问题已经足够清晰"
}}
"""

# 示例
REWRITE_EXAMPLES = [
    {
        "original": "出库咋整",
        "rewritten": "出库流程操作步骤",
        "need_rewrite": True,
        "changes": "口语化转标准化，补全'流程操作步骤'"
    },
    {
        "original": "SPD系统的功能介绍",
        "rewritten": "SPD系统的功能介绍",
        "need_rewrite": False,
        "changes": "问题已经足够清晰"
    },
    {
        "original": "价格",
        "rewritten": "SPD系统价格",
        "need_rewrite": True,
        "changes": "补全主语'SPD系统'"
    }
]
