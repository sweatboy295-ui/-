"""
客服回复幻觉检测器
- 默认 mock 模式：不依赖外部 API，可直接复现结果
- 可选 api 模式：通过 OpenAI-compatible /v1/chat/completions 调用真实 LLM，输出结构化 JSON
"""

from __future__ import annotations
import json
import os
import re
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional


@dataclass
class JudgeResult:
    is_hallucination: bool
    hallucination_type: Optional[str]
    severity: str
    evidence: List[str]
    reason: str


class MockLLMJudge:
    """用可解释的规则模拟 LLM-as-a-Judge 的结构化输出。

    注意：mock 规则不读取 ground_truth，只读取 user_question / system_reply / knowledge_base。
    """

    ACTION_CUES = [
        "我帮您查", "帮您查了", "已经在处理中", "已帮您修改",
        "我已经将", "我直接发到您账户", "已经将您的投诉升级",
        "已升级为高级工单", "我已经查询", "已经为您"
    ]

    def judge(self, user_question: str, system_reply: str, knowledge_base: str) -> JudgeResult:
        q, r, kb = user_question, system_reply, knowledge_base

        # 1) 安全误导：高风险人群/健康建议与知识库的限制条件冲突
        if ("孕妇" in q or "孕妇" in kb) and any(x in r for x in ["放心使用", "可以放心", "可以的"]):
            if any(x in kb for x in ["建议咨询医生", "谨慎", "注意事项"]):
                return JudgeResult(
                    True, "安全误导", "Critical",
                    ["回复给出肯定使用建议", "知识库要求孕妇咨询医生"],
                    "回复把知识库中的风险提示弱化为可放心使用，可能影响用户健康决策。"
                )

        # 2) 能力越界：知识库明确说明系统没有接口/操作能力，但回复宣称已经完成操作
        capability_negative = any(x in kb for x in [
            "无（客服系统未接入", "系统不具备", "需人工后台操作",
            "不具备工单升级功能"
        ])
        if capability_negative and any(x in r for x in self.ACTION_CUES):
            return JudgeResult(
                True, "能力越界", "High",
                ["知识库明确没有对应系统能力", "回复使用已执行/已查询/已修改等完成时态"],
                "系统能力边界与回复中的执行承诺冲突，属于假装调用不存在的系统能力。"
            )

        # 3) 政策/优惠类硬冲突
        policy_rules = [
            ("30天无理由", "7天无理由", "无理由退货周期与知识库冲突"),
            ("运费也由我们承担", "买家承担", "退货运费承担方与知识库冲突"),
            ("纸质发票", "暂不支持纸质发票", "发票类型与知识库冲突"),
            ("备注里写上", "订单详情页申请", "发票申请路径与知识库冲突"),
            ("满300减50", "无满300减50", "优惠活动不存在"),
            ("学生优惠", "当前无学生优惠", "学生优惠政策不存在"),
            ("学生认证", "当前无学生优惠", "学生认证入口属于额外编造"),
            ("48小时", "24小时内发货", "发货时限与知识库冲突"),
            ("顺丰", "中通/韵达/圆通", "合作快递与知识库冲突"),
        ]
        for left, right, reason in policy_rules:
            if left in r and right in kb:
                typ = "优惠编造" if ("优惠" in left or "学生" in left or "满" in left) else ("政策偏差" if left in ["48小时", "纸质发票", "备注里写上", "顺丰"] else "政策编造")
                return JudgeResult(True, typ, "High", [left, right], reason)

        # 4) 商品参数硬冲突
        parameter_rules = [
            ("蓝牙5.3", "蓝牙5.0", "蓝牙版本错误"),
            ("多设备同时连接", "单设备连接", "连接能力错误"),
            ("40ms", "80ms", "延迟参数错误"),
            ("头层牛皮", "PU合成革", "材质参数错误"),
            ("两年", "6个月", "保修期参数错误"),
            ("支持NFC", "未标注NFC", "知识库未提供却肯定支持该功能"),
            ("Type-C接口", "USB-A输出", "接口类型错误"),
        ]
        for left, right, reason in parameter_rules:
            if left in r and right in kb:
                return JudgeResult(True, "参数编造", "High", [left, right], reason)

        # 5) 信息编造 / 不存在关系
        info_rules = [
            ("浙江省杭州市西湖区文三路478号", "人工客服不可口头告知退货地址", "杜撰具体退货地址"),
            ("北京、上海、广州、深圳", "纯线上电商品牌", "杜撰线下门店"),
            ("XX品牌旗下的子品牌", "未提及其他品牌关联关系", "杜撰品牌关联关系"),
        ]
        for left, right, reason in info_rules:
            if left in r and right in kb:
                return JudgeResult(True, "信息编造", "High", [left, right], reason)

        # 6) 特征型“未提供能力/事实”编造
        if "NFC" in r and "未标注NFC" in kb:
            return JudgeResult(True, "参数编造", "High", ["NFC", "知识库未标注NFC"], "回复肯定陈述知识库未提供的产品功能。")

        # 7) 正常回复：只在证据没有形成明确冲突时判为正常。
        #    Mock 模式故意不把“用户评价汇总”类软性遗漏直接判为幻觉，
        #    用于展示真实检测中较难发现的边界 case（h20）。
        return JudgeResult(False, None, "None", [], "回复与知识库没有被检测规则识别出的硬冲突或能力越界。")


class APIJudge:
    """可选：调用 OpenAI-compatible API。

    环境变量：
      LLM_BASE_URL，例如 http://localhost:11434/v1
      LLM_API_KEY
      LLM_MODEL
    """

    SYSTEM_PROMPT = """你是客服回复幻觉检测器。只根据输入的用户问题、系统回复、知识库证据进行判断。
幻觉包括：政策编造/偏差、参数编造、能力越界、信息编造、优惠编造、安全误导、信息遗漏。
输出必须是 JSON：
{
  "is_hallucination": true/false,
  "hallucination_type": "... or null",
  "severity": "Critical/High/Medium/None",
  "evidence": ["...", "..."],
  "reason": "..."
}
注意：
1. 知识库明确不存在/不支持/未提供的信息，被回复肯定陈述时，可判幻觉。
2. 系统明确没有接口或能力，但回复宣称已经查询/修改/升级时，判能力越界。
3. 部分正确、部分错误仍判幻觉。
4. 对“信息遗漏”保持谨慎，只在遗漏直接改变用户决策、且知识库提供了明确限制条件时判定。
"""

    def __init__(self):
        try:
            import requests
        except ImportError:
            raise RuntimeError("api 模式需要 requests，请安装 requirements.txt")
        self.requests = requests
        self.base_url = os.getenv("LLM_BASE_URL", "").rstrip("/")
        self.api_key = os.getenv("LLM_API_KEY", "")
        self.model = os.getenv("LLM_MODEL", "gpt-4o-mini")

    def judge(self, user_question: str, system_reply: str, knowledge_base: str) -> JudgeResult:
        if not self.base_url:
            raise RuntimeError("未设置 LLM_BASE_URL")
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps({
                    "user_question": user_question,
                    "system_reply": system_reply,
                    "knowledge_base": knowledge_base
                }, ensure_ascii=False)}
            ],
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        resp = self.requests.post(f"{self.base_url}/chat/completions",
                                  headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        # 兼容 ```json ... ```
        content = re.sub(r"^```json\s*|\s*```$", "", content.strip(), flags=re.I|re.S)
        data = json.loads(content)
        return JudgeResult(
            bool(data.get("is_hallucination")),
            data.get("hallucination_type"),
            data.get("severity") or ("High" if data.get("is_hallucination") else "None"),
            data.get("evidence") or [],
            data.get("reason", "")
        )


def build_judge(mode: str):
    if mode == "api":
        return APIJudge()
    return MockLLMJudge()


def evaluate(dataset: List[Dict[str, Any]], ground_truth: List[Dict[str, Any]], mode: str = "mock"):
    judge = build_judge(mode)
    gt_map = {x["id"]: x for x in ground_truth}
    results = []
    tp = fp = fn = tn = 0
    for item in dataset:
        pred = judge.judge(item["user_question"], item["system_reply"], item["knowledge_base"])
        truth = gt_map[item["id"]]["is_hallucination"]
        if pred.is_hallucination and truth:
            tp += 1
        elif pred.is_hallucination and not truth:
            fp += 1
        elif (not pred.is_hallucination) and truth:
            fn += 1
        else:
            tn += 1
        results.append({
            "id": item["id"],
            "prediction": asdict(pred),
            "ground_truth": gt_map[item["id"]],
            "error": (
                "FN" if (not pred.is_hallucination and truth)
                else "FP" if (pred.is_hallucination and not truth)
                else None
            )
        })
    precision = tp / (tp + fp) if tp + fp else 0
    recall = tp / (tp + fn) if tp + fn else 0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0
    accuracy = (tp + tn) / len(dataset) if dataset else 0
    metrics = {
        "total": len(dataset),
        "ground_truth_hallucinations": sum(1 for x in ground_truth if x["is_hallucination"]),
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": precision, "recall_detection_rate": recall,
        "f1": f1, "accuracy": accuracy,
        "false_negative_ids": [x["id"] for x in results if x["error"] == "FN"],
        "false_positive_ids": [x["id"] for x in results if x["error"] == "FP"],
    }
    return results, metrics


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--replies", default="data_replies.json")
    parser.add_argument("--ground-truth", default="data_ground_truth.json")
    parser.add_argument("--mode", choices=["mock", "api"], default="mock")
    parser.add_argument("--out", default="results")
    args = parser.parse_args()

    with open(args.replies, encoding="utf-8") as f:
        dataset = json.load(f)
    with open(args.ground_truth, encoding="utf-8") as f:
        gt = json.load(f)
    results, metrics = evaluate(dataset, gt, args.mode)
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "detection_results.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    with open(os.path.join(args.out, "metrics.json"), "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)

    print("=== 客服回复幻觉检测 ===")
    print(f"mode={args.mode}, total={metrics['total']}")
    print(f"TP={metrics['tp']} FP={metrics['fp']} FN={metrics['fn']} TN={metrics['tn']}")
    print(f"Precision={metrics['precision']:.2%}")
    print(f"Recall/检出率={metrics['recall_detection_rate']:.2%}")
    print(f"F1={metrics['f1']:.2%}")
    print(f"Accuracy={metrics['accuracy']:.2%}")
    print()
    print("逐条结果：")
    for row in results:
        p = row["prediction"]
        flag = "幻觉" if p["is_hallucination"] else "正常"
        print(f"{row['id']}: {flag:2s} | {p['hallucination_type'] or '-':6s} | {p['severity']:8s} | error={row['error'] or '-'}")
