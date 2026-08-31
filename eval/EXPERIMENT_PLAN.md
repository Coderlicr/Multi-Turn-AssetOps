# 三架构实验计划

## 目标

比较同一模型、同一工具和同一场景下的三种架构：

1. `plan-execute`
2. `supervisor-specialist`
3. `supervisor-specialist-parallel`

原16场景用于现有系统基线，新50场景用于多轮意图、上下文保持和串并行路径测试。两套数据分别报告，不混成一个总分。

## 固定条件

- 三种架构使用同一个 `deepseek/deepseek-v4-flash` 模型。
- `temperature=0`。
- 同一场景使用相同 reference date、工具和超时。
- 每个完整对话使用新进程；对话内部保留多轮状态。
- API 错误立即停止，不自动重试正式实验。
- 正式实验前冻结代码和 prompt；不根据正式结果继续调 prompt。

## 实验顺序

### 1. API smoke test

只调用一次模型，确认模型名、密钥、base URL 和返回格式可用。

### 2. 三架构 smoke test

从原16场景中选择同一个短对话，每种架构运行一次。确认实际启动了不同架构，结果目录包含回答、工具调用、Token 和延迟。

### 3. 小规模 pilot

- 原场景：3个代表性对话。
- 新场景：5个对话，覆盖顺序、并行、澄清、闲聊和长距离指代。
- 三种架构各运行一次。

Pilot 只用于发现工程和评分问题，不进入论文主结果。

### 4. 正式实验

- 原16场景 × 3架构 × 3次。
- 新50场景 × 3架构 × 3次。
- 共594个完整对话、1,935轮。

如果三次结果完全稳定，不增加重复次数；如果波动明显，再扩展到五次。

## 指标

新50场景的核心指标：

- Optimal Path Rate
- Accomplish Progress Rate
- 无工具调用判断准确率
- 对话完成率
- Token、LLM调用次数、工具调用次数、端到端延迟

叙述性回答单独由固定 judge prompt 评价，不与可精确核对的数值结果混在一起。

## 当前开跑门槛

- [x] 三种架构由统一入口真实切换。
- [x] Plan-Execute 支持固定 reference date。
- [x] 50场景可加载，50个对话、152轮对齐。
- [x] WTB评分器会处罚缺失轮和额外轮。
- [x] WTB 的 OPR 只计 7 个真实 MaintIE 工具；抽象推理步骤不算工具调用，等价路径显式列入白名单。
- [x] 运行时缓存不修改源码。
- [x] 全套测试通过。
- [x] CouchDB 与三类数据已初始化。
- [x] 使用导师指定的 `deepseek-v4-flash`；仓库 `.env` 已配置 API key。
- [x] 官方 MaintIE gold release 已接入独立的真实 MCP server（7个工具），不使用答案模拟器。
- [x] WTB50 统一入口只暴露 MaintIE server，三种架构工具条件一致。
- [x] DeepSeek 单次 API smoke test 通过；按官方 OpenAI 格式关闭 thinking。
- [x] 三架构 WTB01 smoke test 通过（均为4/4轮，无 API/MCP 错误）。
- [x] Supervisor 两个变体的 WTB01/03/15 pilot 通过：11/11 轮完成，APR 9/9，OPR 10/11 与 11/11，WTB15 为 107→40→24。
- [ ] 冻结当前代码、prompt 和评分器后开始正式实验。

## 命令

单架构、单场景：

```bash
uv run python eval/run_eval.py \
  --suite wtb50 \
  --architecture plan-execute \
  --model-id deepseek/deepseek-v4-flash \
  --dialogs 1
```

其余两种架构只需替换 `--architecture`：

```text
supervisor-specialist
supervisor-specialist-parallel
```
