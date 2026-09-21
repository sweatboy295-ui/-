# 客服回复幻觉检测

## 1. 项目说明

目标：对 `replies.json` 中 20 条“用户问题 + 系统回复 + 知识库证据”进行自动幻觉检测，并与 `ground_truth.json` 的人工标注进行对比。

本项目默认使用 **Mock LLM-as-a-Judge**，不依赖外部模型 API，可离线复现结果；同时提供 OpenAI-compatible API 模式，便于接入真实 LLM。

## 2. 幻觉分类体系

分类以附件人工标注出现的类型为基础，并增加统一严重程度：

| 类型 | 定义 | 严重程度 |
|---|---|---|
| 政策编造 | 编造不存在的退货、发票等规则，或扩大政策范围 | High |
| 政策偏差 | 回复部分正确，但关键执行条件、时限、渠道等与知识库不一致 | High |
| 参数编造 | 产品规格、材质、接口、性能等与知识库冲突，或肯定陈述知识库未提供的参数 | High |
| 优惠编造 | 编造优惠券、学生优惠、活动门槛或认证入口 | High |
| 能力越界 | 系统没有物流/退款/订单/工单等接口，却声称已经查询或执行成功 | High |
| 信息编造 | 编造地址、门店、品牌关联等事实性信息 | High |
| 安全误导 | 将知识库中的风险提示弱化或反转为可放心使用等建议 | Critical |
| 信息遗漏 | 忽略知识库中会显著影响用户决策的限制、反馈或条件 | Medium |

严重程度不是人工标注字段，而是本项目为了风险控制定义的业务优先级：健康风险最高；能力越界和政策/产品事实错误直接影响交易或用户决策；软性信息遗漏相对较低。

## 3. 检测方法

### 3.1 Judge 输入

每条样本向 Judge 提供三个字段：

- `user_question`
- `system_reply`
- `knowledge_base`

Judge 输出结构化 JSON：

```json
{
  "is_hallucination": true,
  "hallucination_type": "参数编造",
  "severity": "High",
  "evidence": ["回复证据", "知识库证据"],
  "reason": "..."
}
```

### 3.2 Mock 模式

Mock 模式模拟结构化 LLM Judge 的最终判断，不读取人工 `ground_truth`。

检测逻辑按风险优先级执行：

1. 安全风险冲突；
2. 能力边界冲突；
3. 政策/优惠硬冲突；
4. 商品参数硬冲突；
5. 地址、门店、品牌关系等信息编造；
6. 没有证据冲突时判正常。

这样保证没有 API Key 时仍然能够复现实验。

### 3.3 真实 LLM 模式

支持 OpenAI-compatible Chat Completions：

```bash
set LLM_BASE_URL=http://localhost:11434/v1
set LLM_MODEL=your-model
set LLM_API_KEY=
python src/detector.py --mode api
```

Linux/macOS 可使用：

```bash
export LLM_BASE_URL=http://localhost:11434/v1
export LLM_MODEL=your-model
export LLM_API_KEY=
python src/detector.py --mode api
```

真实模型应严格使用结构化 JSON 输出，并将温度设置为 0，以降低重复运行的不稳定性。

## 4. 20 条样本检测结果

| ID | 预测 | 类型 | 严重度 | Error |
|---|---|---|---|---|
| h01 | 幻觉 | 政策编造 | High | - |
| h02 | 幻觉 | 参数编造 | High | - |
| h03 | 幻觉 | 能力越界 | High | - |
| h04 | 幻觉 | 政策偏差 | High | - |
| h05 | 幻觉 | 优惠编造 | High | - |
| h06 | 幻觉 | 参数编造 | High | - |
| h07 | 幻觉 | 信息编造 | High | - |
| h08 | 幻觉 | 政策偏差 | High | - |
| h09 | 幻觉 | 参数编造 | High | - |
| h10 | 幻觉 | 能力越界 | High | - |
| h11 | 幻觉 | 信息编造 | High | - |
| h12 | 正常 | - | None | - |
| h13 | 幻觉 | 安全误导 | Critical | - |
| h14 | 幻觉 | 能力越界 | High | - |
| h15 | 幻觉 | 信息编造 | High | - |
| h16 | 正常 | - | None | - |
| h17 | 幻觉 | 参数编造 | High | - |
| h18 | 幻觉 | 能力越界 | High | - |
| h19 | 幻觉 | 优惠编造 | High | - |
| h20 | 正常 | - | None | FN |

## 5. 检出率验证

人工标注共 20 条，其中 18 条为幻觉、2 条为正常回复。`ground_truth.json` 的人工标注记录

本次 Mock Judge 结果：

| 指标 | 数值 |
|---|---:|
| TP | 17 |
| FP | 0 |
| FN | 1 |
| TN | 2 |
| Precision | 100.00% |
| Recall / 检出率 | 94.44% |
| F1 | 97.14% |
| Accuracy | 95.00% |

计算方式：

- Precision = TP / (TP + FP)
- Recall（检出率） = TP / (TP + FN)
- F1 = 2 × Precision × Recall / (Precision + Recall)
- Accuracy = (TP + TN) / N

### 漏检

唯一漏检：

- **h20：信息遗漏**。知识库提供“约 30% 的用户反馈偏大半码”，回复只给出“尺码标准、不偏大不偏小”，没有显式重复错误参数，因此硬冲突规则没有触发。人工标注将其定义为“遗漏关键信息导致建议不准确”，并明确说明这类 case 边界较模糊。`ground_truth.json` 中 h20 的人工标注

### 误报

本次没有误报（FP=0）。

## 6. 容易误判的 Case 分析

### h20：软性遗漏最难

它不是“回复 A，知识库 B”的直接矛盾，而是“知识库里存在重要信息，回复没有覆盖”。这类问题需要判断**信息是否与当前决策相关**，比字符串冲突检测难很多，也是本次唯一漏检。

### h04：部分正确 + 部分错误

回复正确说明了支持电子发票，但同时错误地声称支持纸质发票，并给出了错误申请路径。也就是说不能采用“只要存在正确事实就判正常”的策略；应做**claim-level** 检查。人工标注也明确将其归为部分正确、部分错误的政策偏差。`ground_truth.json` 中 h04 的人工标注

### h16：表面相似但不是幻觉

回复提到“轻微色差”，知识库也明确说明拍摄光线、显示器色差可能导致轻微差异，因此应避免把“语义相似改写”误报成幻觉。`ground_truth.json` 中 h16 的人工标注

### h03 / h10 / h14 / h18：能力越界

这类 case 的核心不是文本事实冲突，而是**系统实际没有工具能力**。因此 Judge 必须同时理解“知识库描述的系统能力边界”和“回复使用的完成时态”，例如“帮您查了”“已帮您修改”“已升级工单”。人工标注将这四类都归为能力越界。`ground_truth.json` 中 h03/h10/h14/h18 的人工标注

## 7. AI 工具使用情况

- AI 辅助工具：ChatGPT（用于需求拆解、分类体系设计、检测器代码骨架、README 编写和测试思路）
- 检测方法：Mock LLM-as-a-Judge + 可解释规则
- 未使用 RAGAS；本题使用的是 Judge 式判断框架
- 默认运行不依赖第三方大模型 API，便于评测和提交时复现
- 可通过 OpenAI-compatible API 切换为真实 LLM Judge

## 8. 项目结构

```text
hallucination_detector/
├── data_replies.json
├── data_ground_truth.json
├── run.py
├── requirements.txt
├── README.md
├── src/
│   └── detector.py
├── results/
│   ├── detection_results.json
│   ├── detection_results.csv
│   └── metrics.json
└── screenshots/
    ├── dev_process.png
    └── run_result.png
```

## 9. 运行方式

```bash
python run.py
```

运行后生成：

```text
results/detection_results.json
results/detection_results.csv
results/metrics.json
```

