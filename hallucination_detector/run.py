import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent / "src"))

from detector import evaluate

root = Path(__file__).parent
dataset = json.loads((root/"data_replies.json").read_text(encoding="utf-8"))
gt = json.loads((root/"data_ground_truth.json").read_text(encoding="utf-8"))
results, metrics = evaluate(dataset, gt, "mock")

(root/"results"/"detection_results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
(root/"results"/"metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")

print("=== 客服回复幻觉检测（Mock LLM-as-a-Judge） ===")
print(f"样本数：{metrics['total']}")
print(f"TP={metrics['tp']}  FP={metrics['fp']}  FN={metrics['fn']}  TN={metrics['tn']}")
print(f"Precision：{metrics['precision']:.2%}")
print(f"Recall / 检出率：{metrics['recall_detection_rate']:.2%}")
print(f"F1：{metrics['f1']:.2%}")
print(f"Accuracy：{metrics['accuracy']:.2%}")
print()
print("ID   预测   类型       严重度     Error")
for row in results:
    p=row["prediction"]
    print(f"{row['id']:>3}  {'幻觉' if p['is_hallucination'] else '正常':<4}  {(p['hallucination_type'] or '-'): <8} {p['severity']:<8} {row['error'] or '-'}")
