"""
医院名称映射表
从 docs/销售_指南_SPD操作指南.md 中提取的所有医院
用于医院级别的搜索识别和过滤
"""

# 医院规范化映射表
# key: 规范化的医院名称（作为标准名）
# value: 该医院的所有别名和变体（用于LLM识别和关键词匹配）
HOSPITAL_MAPPING = {
    # 广东中部医院
    "和祐医院": {
        "aliases": ["和祐", "和祐医院"],
        "region": "广州",
        "type": "综合医院",
        "full_name": "和祐医院"
    },

    "中山三院": {
        "aliases": ["中山三院", "中山三", "中山医院", "中山"],
        "region": "中山",
        "type": "综合医院",
        "full_name": "中山市第三人民医院"
    },

    "和睦家": {
        "aliases": ["和睦家", "和睦家医院", "深圳和睦家"],
        "region": "深圳/广州",
        "type": "私立医院",
        "full_name": "和睦家医疗"
    },

    # 肇庆
    "肇庆市一": {
        "aliases": ["肇庆市一", "肇庆一", "肇庆市第一人民医院"],
        "region": "肇庆",
        "type": "综合医院",
        "full_name": "肇庆市第一人民医院"
    },

    "肇庆市二": {
        "aliases": ["肇庆市二", "肇庆二", "肇庆市第二人民医院", "肇庆市二【新】"],
        "region": "肇庆",
        "type": "综合医院",
        "full_name": "肇庆市第二人民医院"
    },

    "肇庆高要": {
        "aliases": ["肇庆高要", "高要", "肇庆高要人民医院"],
        "region": "肇庆",
        "type": "综合医院",
        "full_name": "肇庆高要人民医院"
    },

    # 梅州
    "梅州人民": {
        "aliases": ["梅州人民", "梅州人民医院"],
        "region": "梅州",
        "type": "综合医院",
        "full_name": "梅州市人民医院"
    },

    "梅州中医院": {
        "aliases": ["梅州中医院", "梅州中医", "梅州市中医院"],
        "region": "梅州",
        "type": "中医医院",
        "full_name": "梅州市中医院"
    },

    # 其他
    "陆总": {
        "aliases": ["陆总", "陆总医院"],
        "region": "广州",
        "type": "综合医院",
        "full_name": "陆总医院"
    },

    "市中医": {
        "aliases": ["市中医", "市中医院"],
        "region": "广州",
        "type": "中医医院",
        "full_name": "广州市中医院"
    },

    "佛山妇幼": {
        "aliases": ["佛山妇幼", "佛山妇幼保健院", "佛山妇幼（线下回款）"],
        "region": "佛山",
        "type": "妇幼医院",
        "full_name": "佛山市妇幼保健院"
    },

    "佛山市三水区乐平镇人民医院": {
        "aliases": ["三水乐平", "乐平镇人民医院", "佛山市三水区乐平镇人民医院"],
        "region": "佛山",
        "type": "综合医院",
        "full_name": "佛山市三水区乐平镇人民医院"
    },

    "佛山市南海区人民医院": {
        "aliases": ["南海人民医院", "南海区人民医院", "佛山市南海区人民医院", "佛山市南海区人民医院+"],
        "region": "佛山",
        "type": "综合医院",
        "full_name": "佛山市南海区人民医院"
    },

    "南方中西医结合医院": {
        "aliases": ["南方中西医", "南方中西医结合医院"],
        "region": "广州",
        "type": "中西医结合医院",
        "full_name": "南方中西医结合医院"
    },

    "省医": {
        "aliases": ["省医", "省医院", "广东省医院"],
        "region": "广州",
        "type": "综合医院",
        "full_name": "广东省人民医院"
    },

    "番禺中心医院": {
        "aliases": ["番禺中心", "番禺中心医院", "番禺中心医院0"],
        "region": "广州",
        "type": "综合医院",
        "full_name": "番禺中心医院"
    },

    "天河人民医院": {
        "aliases": ["天河人民", "天河人民医院"],
        "region": "广州",
        "type": "综合医院",
        "full_name": "天河人民医院"
    },

    "河源人民": {
        "aliases": ["河源人民", "河源人民医院", "河源人民（线下回款）"],
        "region": "河源",
        "type": "综合医院",
        "full_name": "河源市人民医院"
    },

    "河源国控": {
        "aliases": ["河源国控", "源城人民", "河源国控-源城人民"],
        "region": "河源",
        "type": "综合医院",
        "full_name": "河源市源城区人民医院"
    },

    "南五": {
        "aliases": ["南五", "南五医院"],
        "region": "广州",
        "type": "综合医院",
        "full_name": "广州市第五人民医院"
    },

    "东莞台心医院": {
        "aliases": ["台心", "东莞台心", "东莞台心医院"],
        "region": "东莞",
        "type": "私立医院",
        "full_name": "东莞台心医院"
    },

    "南方医": {
        "aliases": ["南方医", "南方医科大学", "南医大"],
        "region": "广州",
        "type": "综合医院",
        "full_name": "南方医科大学附属医院"
    },

    "广医一": {
        "aliases": ["广医一", "广医", "广州医科大学"],
        "region": "广州",
        "type": "综合医院",
        "full_name": "广州医科大学附属第一医院"
    },

    "武警医院": {
        "aliases": ["武警", "武警医院", "武警总医院"],
        "region": "广州",
        "type": "综合医院",
        "full_name": "中国人民武装警察部队医院"
    },

    "汕头沁美": {
        "aliases": ["沁美", "汕头沁美"],
        "region": "汕头",
        "type": "私立医院",
        "full_name": "汕头沁美医院"
    },

    # 系统/平台相关
    "医保平台": {
        "aliases": ["医保平台", "医保系统"],
        "region": "多地",
        "type": "系统",
        "full_name": "医保平台"
    },

    "自由主题": {
        "aliases": ["自由主题"],
        "region": "通用",
        "type": "其他",
        "full_name": "自由主题"
    }
}


def normalize_hospital_name(name: str) -> str:
    """
    规范化医院名称
    将输入的医院名（可能是别名）转换为标准名

    Args:
        name: 医院名称（可能是别名）

    Returns:
        标准化后的医院名称，如果未找到则返回原输入
    """
    if not name:
        return None

    name = name.strip()
    if not name:
        return None

    # 先检查是否是标准名
    if name in HOSPITAL_MAPPING:
        return name

    # 检查别名
    for standard_name, info in HOSPITAL_MAPPING.items():
        if name in info["aliases"] or name == info["full_name"]:
            return standard_name

    # 未找到，返回原值
    return name


def find_hospital_in_text(text: str) -> str:
    """从文本中按最长标准名或别名匹配医院，避免短别名覆盖长名称。"""
    if not text:
        return None

    candidates = []
    for standard_name, info in HOSPITAL_MAPPING.items():
        candidates.append((standard_name, standard_name))
        candidates.append((standard_name, info["full_name"]))
        candidates.extend((standard_name, alias) for alias in info["aliases"])

    for standard_name, candidate in sorted(candidates, key=lambda item: len(item[1]), reverse=True):
        if candidate and candidate in text:
            return standard_name
    return None

def get_hospital_info(hospital_name: str) -> dict:
    """获取医院的详细信息。"""
    standard_name = normalize_hospital_name(hospital_name)
    return HOSPITAL_MAPPING.get(standard_name)


def get_all_hospital_names() -> list:
    """获取所有标准化的医院名称"""
    return list(HOSPITAL_MAPPING.keys())


def get_all_aliases() -> list:
    """获取所有医院别名（用于提示词）"""
    all_aliases = []
    for standard_name, info in HOSPITAL_MAPPING.items():
        all_aliases.extend(info["aliases"])
    return all_aliases
