"""
意图分类提示词
"""

from typing import Dict


def _build_hospital_list_text() -> str:
    """
    从hospital_mapping动态生成医院列表文本，避免硬编码重复

    Returns:
        格式化的医院列表文本
    """
    from src.backend.ingestion.hospital_mapping import HOSPITAL_MAPPING

    # 按region分组医院，并同时提供标准名、全名和别名
    hospitals_by_region: Dict[str, list] = {}
    for standard_name, info in HOSPITAL_MAPPING.items():
        region = info.get("region", "其他")
        names = [standard_name, info.get("full_name", standard_name)]
        names.extend(info.get("aliases", []))
        unique_names = list(dict.fromkeys(name for name in names if name))
        hospitals_by_region.setdefault(region, []).append(
            f"{standard_name}（{'、'.join(unique_names)}）"
        )

    # 生成格式化文本
    lines = ["已知医院列表（标准名：别名/全名）："]
    for region in sorted(hospitals_by_region):
        lines.append(f"- {'；'.join(hospitals_by_region[region])}（{region}）")

    return "\n".join(lines)


def get_hospital_extraction_prompt(query: str) -> str:
    """
    生成医院提取提示词（动态包含最新的医院列表）

    Args:
        query: 用户问题

    Returns:
        完整的提示词
    """
    hospital_list = _build_hospital_list_text()

    return f"""从用户问题中识别所涉及的医院名称。

{hospital_list}

用户问题：{query}

请识别问题中提到的医院名称。如果问题提到了某家医院，返回该医院的标准名称。
如果提到了多个医院，返回最主要的（或第一个提到的）。
如果问题没有提到任何具体医院（如"出库流程"、"功能介绍"等通用问题），返回 null。

返回格式：JSON（只返回JSON，不要其他内容）
{{
    "hospital": "肇庆市一" 或 null,
    "confidence": 0.95,
    "reasoning": "用户明确提到了'肇庆市一'"
}}
"""


# 保留向后兼容的常量（已弃用，使用get_hospital_extraction_prompt()替代）
HOSPITAL_EXTRACTION_PROMPT = None

INTENT_CLASSIFICATION_PROMPT = """分析用户问题的意图，判断应该查询哪种类型的文档。

用户问题：{query}

请从以下意图类型中选择最匹配的：

1. **product_feature**（产品功能介绍）
   - 用户问"是什么"、"有什么功能"、"产品介绍"、"特点"、"优势"
   - 应查"手册"类文档
   - 示例："SPD系统有什么功能？"、"产品特点是什么？"

2. **operation_process**（操作流程步骤）
   - 用户问"怎么操作"、"流程是什么"、"如何使用"、"步骤"
   - 应查"指南"类文档
   - 示例："出库流程怎么操作？"、"如何录入数据？"

3. **case_study**（客户案例、项目经验）
   - 用户问"案例"、"成功案例"、"实际效果"、"客户"、"实施经验"
   - 应查"案例"类文档
   - 示例："有哪些客户案例？"、"实施效果如何？"

4. **pricing_info**（价格、报价信息）
   - 用户问"价格"、"多少钱"、"报价"、"成本"、"费用"
   - 应查"报价"或"清单"类文档
   - 示例："SPD系统多少钱？"、"价格是多少？"

5. **policy_rule**（政策、规则、制度）
   - 用户问"政策"、"规定"、"制度"、"要求"、"标准"、"规范"
   - **注意**：关于"福利"、"假期"等员工相关问题属于此类
   - 应查"政策"类文档
   - 示例："报销政策是什么？"、"请假制度"、"员工福利有哪些？"

6. **general**（通用查询，无明确类型）
   - 无法明确分类，或查询范围广泛
   - 包括：公司介绍、企业文化、联系方式等
   - 应查所有类型文档
   - 示例："企业文化是什么？"、"公司简介"、"联系方式"

**分类要点**：
- 如果问题同时涉及多个类型，选择最主要的意图
- 如果无法确定或问题模糊，选择 general
- 置信度范围：0.0-1.0，越确定分数越高

请以 JSON 格式返回（只返回 JSON，不要其他内容）：
{{
    "intent": "product_feature",
    "doc_type": "手册",
    "keywords": ["SPD", "功能"],
    "confidence": 0.9,
    "reasoning": "用户询问产品功能特点"
}}
"""

# Few-shot 示例（可选，用于提升准确率）
INTENT_EXAMPLES = [
    {
        "query": "SPD系统有什么功能？",
        "result": {
            "intent": "product_feature",
            "doc_type": "手册",
            "keywords": ["SPD", "功能"],
            "confidence": 0.95
        }
    },
    {
        "query": "出库流程怎么操作？",
        "result": {
            "intent": "operation_process",
            "doc_type": "指南",
            "keywords": ["出库", "流程", "操作"],
            "confidence": 0.9
        }
    },
    {
        "query": "企业文化是什么？",
        "result": {
            "intent": "general",
            "doc_type": None,
            "keywords": ["企业文化"],
            "confidence": 0.85
        }
    },
    {
        "query": "员工福利有哪些？",
        "result": {
            "intent": "general",
            "doc_type": None,
            "keywords": ["员工福利"],
            "confidence": 0.8
        }
    }
]
