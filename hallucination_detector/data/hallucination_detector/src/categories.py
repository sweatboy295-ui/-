"""
自建"客服回复幻觉"分类体系。

严重度数值越大越严重：critical=4 / high=3 / medium=2 / low=1。
7 类幻觉及其与人工标注（ground_truth 的 8 类）的对应关系：
  SAFETY_MISINFO      安全误导    (critical)  <- 安全误导
  PARAMS_FABRICATED   参数/规格编造 (high)     <- 参数编造
  POLICY_FABRICATED   政策编造/偏差 (high)     <- 政策编造、政策偏差
  PROMO_FABRICATED    优惠编造     (high)     <- 优惠编造
  INFO_FABRICATED     事实信息编造  (high)     <- 信息编造
  CAPABILITY_OVERREACH 能力越界    (high)     <- 能力越界
  INFO_OMISSION       关键信息遗漏  (medium)   <- 信息遗漏
"""

SEVERITY_LEVELS = {
    "critical": 4,
    "high": 3,
    "medium": 2,
    "low": 1,
}

# 类型元数据：code / 中英文名 / 严重度 / 判定依据(basis) / 对应人工标注类型(gt_types)
CATEGORIES = [
    {
        "code": "SAFETY_MISINFO",
        "zh": "安全误导",
        "en": "Safety Misinformation",
        "severity": "critical",
        "severity_score": 4,
        "basis": "回复与产品安全提示（孕妇/医嘱/成分禁忌等）直接冲突，可能危害用户健康。",
        "gt_types": ["安全误导"],
    },
    {
        "code": "PARAMS_FABRICATED",
        "zh": "参数/规格编造",
        "en": "Product-spec Fabrication",
        "severity": "high",
        "severity_score": 3,
        "basis": "回复中的产品参数（版本/接口/材质/保修/NFC等）与知识库明确记载冲突，或知识库未标注却断然宣称。",
        "gt_types": ["参数编造"],
    },
    {
        "code": "POLICY_FABRICATED",
        "zh": "政策编造/偏差",
        "en": "Policy Fabrication / Deviation",
        "severity": "high",
        "severity_score": 3,
        "basis": "回复中的售后/交易政策（退货天数、运费、发票、发货时效、快递等）与知识库政策矛盾，或部分正确部分错误。",
        "gt_types": ["政策编造", "政策偏差"],
    },
    {
        "code": "PROMO_FABRICATED",
        "zh": "优惠编造",
        "en": "Promotion Fabrication",
        "severity": "high",
        "severity_score": 3,
        "basis": "杜撰不存在的优惠券/满减/折扣/学生优惠等，常伴随承诺发送到账户等越界动作。",
        "gt_types": ["优惠编造"],
    },
    {
        "code": "INFO_FABRICATED",
        "zh": "事实信息编造",
        "en": "Factual Info Fabrication",
        "severity": "high",
        "severity_score": 3,
        "basis": "杜撰地址、门店、品牌关联、物流位置等知识库无任何记载的事实信息。",
        "gt_types": ["信息编造"],
    },
    {
        "code": "CAPABILITY_OVERREACH",
        "zh": "能力越界",
        "en": "Capability Overreach",
        "severity": "high",
        "severity_score": 3,
        "basis": "系统明确未接入某接口/不具备某操作能力（物流、退款、改地址、工单、发券等），却假装已查询或已执行。",
        "gt_types": ["能力越界"],
    },
    {
        "code": "INFO_OMISSION",
        "zh": "关键信息遗漏",
        "en": "Key Info Omission",
        "severity": "medium",
        "severity_score": 2,
        "basis": "知识库中存在影响结论的关键数据（如用户反馈偏大半码），回复却给出相反或过于简化的结论，省略该信息。",
        "gt_types": ["信息遗漏"],
    },
]

# code -> 类型元数据 的索引，便于查严重度/中文名
CODE_TO_META = {c["code"]: c for c in CATEGORIES}
# 人工标注类型 -> 本项目 code 的映射（用于评估时的类型级对齐）
GT_TO_CODE = {}
for c in CATEGORIES:
    for gt in c["gt_types"]:
        GT_TO_CODE[gt] = c["code"]


def severity_of(code):
    """返回某类型的严重度数值（越大越严重）。"""
    return CODE_TO_META[code]["severity_score"]


def zh_of(code):
    """返回某类型的中文名。"""
    return CODE_TO_META[code]["zh"]


def severity_label(score):
    """严重度数值 -> 严重度标签（critical/high/...），未知值归为 low。"""
    rev = {v: k for k, v in SEVERITY_LEVELS.items()}
    return rev.get(score, "low")


def gt_bucket_to_code(gt_type):
    """人工标注类型 -> 本项目分类 code；无法对应时返回 None。"""
    return GT_TO_CODE.get(gt_type, None)


def top_category():
    """按严重度从高到低返回全部分类（用于展示）。"""
    return sorted(CATEGORIES, key=lambda c: -c["severity_score"])