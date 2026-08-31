# WTB-50 三架构 Pilot

## 设置

- 模型：`deepseek/deepseek-v4-flash`，关闭 thinking。
- 数据：官方 MaintIE 1,076 条人工校正工单。
- 工具：真实 MaintIE server 的 7 个工具。
- 对话：WTB01、WTB03、WTB15，共 11 轮；其中 9 轮有确定结果。
- 每轮预算：最多 2 次 Specialist 派发、6 次工具调用。
- API 错误不重试；本次没有出现 API、MCP 或超时错误。

## 修复结果

| 架构 | APR | OPR | 工具决策准确率 | 完成轮次 | Tokens | LLM 调用 | MaintIE 调用 | 总耗时 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Plan-Execute | 6/9 | 2/11 | 9/11 | 11/11 | 60,785 | 47 | 26 | 85.57 秒 |
| Supervisor-Specialist | 9/9 | 10/11 | 10/11 | 11/11 | 76,475 | 29 | 9 | 39.06 秒 |
| Supervisor-Specialist-Parallel | 9/9 | 11/11 | 11/11 | 11/11 | 69,368 | 26 | 9 | 36.87 秒 |

逐对话结果：

| 架构 | WTB01 APR / OPR | WTB03 APR / OPR | WTB15 APR / OPR |
|---|---:|---:|---:|
| Plan-Execute | 3/3 · 0/4 | 3/3 · 2/4 | 0/3 · 0/3 |
| Supervisor-Specialist | 3/3 · 4/4 | 3/3 · 3/4 | 3/3 · 3/3 |
| Supervisor-Specialist-Parallel | 3/3 · 4/4 | 3/3 · 4/4 | 3/3 · 3/3 |

WTB15 的三轮集合大小均为预期值：

```text
107（Lines & drives 的故障集合）
 → 40（在 107 个 ID 内筛选 Replace）
 → 24（在 40 个 ID 内筛选 hose）
```

完整 ID 只保存在 typed state 中；提示词和普通日志只保留集合大小、来源轮次和过滤条件。

Plan-Execute 没有 typed selection：WTB15 三轮实际为 `98 → 347 → 37`，所以该对话 APR 和 OPR 都是 0。

## 与修复前对比

修复前两个 Supervisor 变体的 APR 都是 1/9、OPR 都是 3/11；顺序版只完成 10/11 轮，并出现大量重复调用。修复后：

- 两个变体都完成 11/11 轮，无超时；
- APR 从 1/9 提升到 9/9；
- OPR 从 3/11 提升到 10/11 和 11/11；
- WTB15 从跨轮集合丢失变为稳定的 `107 → 40 → 24`；
- MaintIE 调用从修复前的 151/100 次下降到两个变体各 9 次；
- Token 从 1,665,393/1,021,391 降到 76,475/69,368。

顺序版保存的最终运行中，WTB03 第 2 轮多调用了一次 `compare`，因此 OPR 为 10/11。随后加入的本地比较复用规则已在并行版真实运行中验证，该轮不再调用工具。

## 评分口径

- APR 检查回答是否覆盖完整金标准。Supervisor 直接读取 JSONL 的结构化 `result`；评分器只规范化 `count`/`n`、`replacements`/`replace`、键值对列表/字典等展示差异。Plan-Execute 尚未输出 `result`，本次按保存答案逐项核对；数值错误、数值对调或缺项仍然失败。
- OPR 只统计 7 个真实 MaintIE 工具。并行组内部顺序不计，串行顺序、重复调用、额外调用和漏调用都会扣分。
- 工具决策准确率只判断该轮是否应该调用真实 MaintIE，不判断具体工具和参数。

APR 分母为 9：11 轮中有 9 轮包含可精确核对的结果，2 轮是澄清或闲聊。OPR 和工具决策准确率分母均为全部 11 轮；缺失轮、额外轮、额外工具和本应无工具却调用工具都会扣分。

## 运行产物

- Plan-Execute：`eval/results/pilot_wtb50_plan_execute_latest/`
- 顺序版：`eval/results/pilot_wtb50_supervisor_specialist_fixed_v4/`
- 并行版：`eval/results/pilot_wtb50_supervisor_specialist_parallel_fixed/`
- 修复前基线：`eval/results/pilot_wtb50_supervisor_specialist/` 和 `eval/results/pilot_wtb50_supervisor_specialist_parallel/`

Pilot 已达到计划门槛。下一步应冻结代码、prompt、模型和评分器，再开始完整 WTB-50 实验；Pilot 结果不并入论文主结果。
