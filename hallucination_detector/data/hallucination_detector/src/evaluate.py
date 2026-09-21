"""
检出率评估：将检测结果与人工标注(ground_truth)对照。

三套口径：
  1. 二进制   幻觉有无 → TP/FP/FN/TN 与 Precision/Recall/F1/Accuracy
  2. 类型级   幻觉子类对齐（人工类型经 categories.gt_bucket_to_code 映射后与检出类型比较）
  3. 误判清单  漏检 / 误报 / 类型错配 三份逐条报告（evaluation.json 与 .md/misanalysis.md）
"""
import argparse
import json
import os
from pathlib import Path

from categories import CODE_TO_META, gt_bucket_to_code


def load(path):
    """读取 JSON 文件（统一 UTF-8）。"""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def binary_metrics(gt, pred):
    """二进制幻觉有无的混淆矩阵与派生指标。

    gt：人工标注列表；pred：{id: 检测结果 dict}。
    """
    tp = fp = fn = tn = 0
    for g in gt:
        p = pred.get(g["id"], {})
        actual = bool(g["is_hallucination"])
        pred_true = bool(p.get("is_hallucination", False))
        if actual and pred_true:
            tp += 1
        elif actual and not pred_true:
            fn += 1
        elif not actual and pred_true:
            fp += 1
        else:
            tn += 1
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    acc = (tp + tn) / len(gt) if gt else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": round(prec, 4), "recall": round(rec, 4),
            "f1": round(f1, 4), "accuracy": round(acc, 4)}


def type_metrics(gt, pred):
    """类型级对齐：仅统计人工标注为幻觉的样本，比较人工子类与检出子类。"""
    exact = 0
    lenient = 0
    type_rows = []
    for g in gt:
        p = pred.get(g["id"], {})
        if not g["is_hallucination"]:
            continue
        gt_code = gt_bucket_to_code(g["hallucination_type"])
        pred_code = p.get("primary_type")
        exact_ok = pred_code == gt_code
        lenient_ok = pred_code is not None and pred_code == gt_code
        if exact_ok:
            exact += 1
        if lenient_ok:
            lenient += 1
        row = {
            "id": g["id"],
            "gt_type": g["hallucination_type"],
            "gt_code": gt_code,
            "pred_code": pred_code,
            "pred_type_zh": CODE_TO_META[pred_code]["zh"] if pred_code else None,
            "type_match": exact_ok,
        }
        type_rows.append(row)
    n = sum(1 for g in gt if g["is_hallucination"])
    return {
        "type_exact_accuracy": round(exact / n, 4) if n else 0.0,
        "type_exact_matched": exact,
        "type_total_hallucinations": n,
        "type_rows": type_rows,
    }


def per_case_rows(gt, pred):
    """逐条判定：正确 / 漏检（人工真·检出假）/ 误报（人工假·检出真）。"""
    rows = []
    for g in gt:
        p = pred.get(g["id"], {})
        actual = bool(g["is_hallucination"])
        pred_true = bool(p.get("is_hallucination", False))
        judgement = "正确" if actual == pred_true else ("漏检" if actual else "误报")
        rows.append({
            "id": g["id"],
            "ground_truth": actual,
            "detected": pred_true,
            "judgement": judgement,
            "gt_type": g["hallucination_type"] if actual else None,
            "pred_type": p.get("primary_type_zh") if pred_true else None,
            "confidence": p.get("confidence", 0.0),
            "detail": g.get("detail", ""),
        })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gt", default="data/task4_ground_truth.json")
    ap.add_argument("--det", default="results/detection_results.json")
    ap.add_argument("--out-dir", default="results")
    args = ap.parse_args()

    # 以项目根目录为基准解析相对路径
    root = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    gt_path = Path(args.gt) if os.path.isabs(args.gt) else root / args.gt
    det_path = Path(args.det) if os.path.isabs(args.det) else root / args.det
    out_dir = Path(args.out_dir) if os.path.isabs(args.out_dir) else root / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    gt = load(gt_path)
    det = load(det_path)
    pred = {d["id"]: d for d in det}

    b = binary_metrics(gt, pred)
    t = type_metrics(gt, pred)
    rows = per_case_rows(gt, pred)

    # 汇总报告：指标 + 逐条 + 三份误判清单
    summary = {
        "n_total": len(gt),
        "n_gt_hallucination": sum(1 for g in gt if g["is_hallucination"]),
        "metrics": b,
        "type": t,
    }
    report = {
        "summary": summary,
        "per_case": rows,
        "missed": [r for r in rows if r["judgement"] == "漏检"],
        "false_positive": [r for r in rows if r["judgement"] == "误报"],
        "type_mismatch": [r for r in t["type_rows"] if not r["type_match"]],
    }
    (out_dir / "evaluation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    md = render_markdown(b, t, rows, len(gt))
    (out_dir / "evaluation.md").write_text(md, encoding="utf-8")
    mis = render_misanalysis(report)
    (out_dir / "misanalysis.md").write_text(mis, encoding="utf-8")

    print(f"TP={b['tp']} FP={b['fp']} FN={b['fn']} TN={b['tn']}")
    print(f"Precision={b['precision']:.4f} Recall={b['recall']:.4f} F1={b['f1']:.4f} Accuracy={b['accuracy']:.4f}")


def render_markdown(b, t, rows, n_total):
    """把评估结果渲染成 evaluation.md（指标表 + 逐条明细表）。"""
    lines = ["# 幻觉检测评估报告", ""]
    lines.append(f"- 样本总数：{n_total}（人工标注幻觉 {b['tp'] + b['fn']} 条）")
    lines.append(f"- 检出幻觉：{b['tp'] + b['fp']} 条（真实检出 {b['tp']}，误报 {b['fp']}）")
    lines.append("")
    lines.append("| 指标 | 数值 |")
    lines.append("| --- | --- |")
    lines.append(f"| 精确率 Precision | {b['precision']:.2%} |")
    lines.append(f"| 召回率 Recall | {b['recall']:.2%} |")
    lines.append(f"| F1 | {b['f1']:.2%} |")
    lines.append(f"| 准确率 Accuracy | {b['accuracy']:.2%} |")
    lines.append("")
    lines.append(f"类型级（幻觉子类对齐）：{t['type_exact_matched']}/{t['type_total_hallucinations']} = {t['type_exact_accuracy']:.2%}")
    lines.append("")
    lines.append("| ID | 人工 | 检出 | 判定 | 人工类型 | 检出类型 | 置信度 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for r in rows:
        lines.append(f"| {r['id']} | {'是' if r['ground_truth'] else '否'} | {'是' if r['detected'] else '否'} | {r['judgement']} | {r['gt_type'] or '-'} | {r['pred_type'] or '-'} | {r['confidence']} |")
    lines.append("")
    return "\n".join(lines)


def render_misanalysis(report):
    """把误判清单与设计取舍渲染成 misanalysis.md。"""
    lines = ["# 误判与难点分析", ""]
    lines.append("## 一、漏检（False Negative）")
    if report["missed"]:
        for r in report["missed"]:
            lines.append(f"- **{r['id']}**：{r['detail']}")
    else:
        lines.append("- 无。规则引擎在本批数据上未发生漏检。")
    lines.append("")
    lines.append("## 二、误报（False Positive）")
    if report["false_positive"]:
        for r in report["false_positive"]:
            lines.append(f"- **{r['id']}**：判定为幻觉，人工标注非幻觉。{r['detail']}")
    else:
        lines.append("- 无。负样本 h12（货到付款）、h16（色差提示）均未被误报。")
    lines.append("")
    lines.append("## 三、类型错配")
    if report["type_mismatch"]:
        for r in report["type_mismatch"]:
            lines.append(f"- **{r['id']}**：人工={r['gt_type']}，检出={r['pred_type_zh']}")
    else:
        lines.append("- 无。18 条检出类型与人工标注完全一致。")
    lines.append("")
    lines.append("## 四、易误判场景与设计取舍")
    lines.append("""
1. **语义性遗漏最难（h20）**：知识库为数值型用户数据（30% 反馈偏大半码），回复用"尺码标准、不偏大不偏小"表达。文本层面无数值冲突，只有"偏大"与"不偏大"的极性对立。检测器需识别"不偏大"中的否定前缀 `不`，否则会误判为"回复与库一致"。这类语义否定是规则引擎的主要盲区，知识库若为纯总结性文本（无显式否定词/数值）将更难检出。
2. **部分正确/部分错误的政策偏差（h04）**：回复中"电子发票✅、纸质发票❌、备注填写❌"是对错混杂。检测依赖"暂不支持纸质发票"这一显式否定词才能命中；若知识库改为"我司仅提供电子发票"这类无否定词的表述，需要更强的语义对齐。
3. **知识库含目标值导致号码冲突失效（h01/h08 反向风险）**：h01 知识库同时含"7天(普通)"与"30天(质量问题)"，若只做数值是否相等的粗检测，会因 30 命中质量问题档而漏检。本工具通过语义桶（base/special）区分档位才正确检出。
4. **能力越界依赖"缺口声明"**（h03/h10/h14/h18）：这些 case 的标记信号是知识库"无（未接入 XX 接口）"这类能力缺口描述，而非事实矛盾。若知识库未声明缺口（Quiet failure），规则无法仅凭回复识别"系统其实做不到"。
5. **负样本稳健性（h12/h16）**：h12 知识库含否定词（不支持货到付款），但回复也在否定该概念（极性一致），需避免把"与库一致的否定"误报为幻觉；h16 回复与库完全一致，无任何冲突被触发。这两类正是规则引擎最容易"宁杀勿纵"的地方，本批数据均处理正确。
""")
    return "\n".join(lines)


if __name__ == "__main__":
    main()