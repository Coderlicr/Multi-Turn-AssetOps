# WTB50 系统改造说明

## 为什么要改

原系统主要面向楼宇设备运维，通过 IoT、工单、时序预测等 MCP Server 回答 16 组固定场景。导师新增的 50 组场景关注另一类问题：模型能否在多轮对话中正确理解指代、澄清、闲聊，以及选择串行或并行工具调用。

因此，本次改造没有推翻原系统，而是在保留原功能的基础上，增加一条独立、可复现的 MaintIE 实验链路。

## 原系统与新系统的区别

| 项目 | 原系统 | 改造后 |
| --- | --- | --- |
| 数据 | IoT、普通工单、时序数据 | 保留原数据，并加入官方 MaintIE 1,076 条人工标注工单 |
| 实验场景 | 16 组资产运维对话 | 保留原 16 组，并加入 50 组 WTB 多轮场景，共 152 轮 |
| 系统架构 | 主要运行 Supervisor-Specialist | 可以统一切换 Plan-Execute、Supervisor-Specialist、并行 Supervisor-Specialist |
| 工单分析工具 | 原工单 Server，适合按设备和日期查询 | 新增独立 MaintIE Server，支持搜索、抽取、计数、分组、排序、原文查看和对比 |
| 模型 | 主要使用 WatsonX 或通用 LiteLLM | 新增 `deepseek/deepseek-v4-flash`，按官方参数关闭 thinking，避免结构化输出被思考内容截断 |
| 评测 | 主要统计完成率、Token 和延迟 | 新增 WTB 场景加载、标准答案对齐及 APR、OPR 等评分基础 |

## 具体做了什么

### 1. 新增真实 MaintIE Server

从 MaintIE 官方 GitHub 仓库引入：

- `gold_release.json`：1,076 条人工校正工单；
- `scheme.json`：实体和关系定义；
- 上游许可证和固定 commit 说明。

Server 提供 7 个工具：

- `search`：搜索工单，返回可跨轮复用的工单 ID；
- `extract`：抽取活动、对象和故障标注；
- `count`：计数或统计不同对象类型；
- `group_count`：按活动、对象、故障模式等分组；
- `rank`：对分组结果排序；
- `get_text`：查看单条工单原文和标注；
- `compare`：对比多个工单子集。

工具只查询官方 MaintIE 图谱，不读取 WTB 标准答案，也不使用答案模拟器。

### 2. 接入三种真实架构

统一评测入口现在可以选择：

1. `plan-execute`
2. `supervisor-specialist`
3. `supervisor-specialist-parallel`

三种架构运行 WTB50 时只暴露同一个 MaintIE Server，保证数据和工具条件一致。MaintIE 的 7 个工具已加入 Supervisor-Specialist 白名单；Plan-Execute 通过 MCP 动态发现全部工具及参数定义。

### 3. 加入 50 组多轮场景

新增的数据加载器会检查：

- 是否正好有 50 组对话；
- 是否正好有 152 轮；
- 每一轮的 `task`、`follow`、`clarify`、`chat` 类型是否与标准答案对齐。

评分器会处罚缺失轮、额外轮、错误工具路径，以及本不应调用工具却调用工具的情况。

### 4. 适配 DeepSeek V4 Flash

模型统一写为：

```text
deepseek/deepseek-v4-flash
```

按照 DeepSeek 官方 OpenAI 兼容格式传入：

```json
{"thinking": {"type": "disabled"}}
```

关闭 thinking 后，三种架构均已完成 WTB01 的 4 轮 smoke test，没有 API 或 MCP 错误。

### 5. 修复实验稳定性问题

同时修复了会影响实验复现的问题，包括：

- 固定 reference date；
- 运行时缓存不再修改源码；
- 临时目录自动创建；
- NumPy 版本兼容；
- 多轮日志记录 turn ID；
- Plan-Execute 支持无工具回答；
- 未知 Server 会明确记录错误；
- 统一记录 Token、LLM 调用次数、工具调用次数和延迟。

## 如何运行

以 WTB01 为例：

```bash
uv run python eval/run_eval.py \
  --suite wtb50 \
  --architecture plan-execute \
  --dialogs 1
```

把 `--architecture` 替换为下面任意一个值，即可运行另外两种架构：

```text
supervisor-specialist
supervisor-specialist-parallel
```

WTB50 默认使用 `deepseek/deepseek-v4-flash`。API key 保存在本地 `.env`，不会提交到 GitHub。

## 当前状态

- MaintIE Server 和 7 个工具可正常调用；
- 三种架构的 WTB01 smoke test 均为 4/4 轮完成；
- 全套测试为 266 passed、2 skipped；
- 下一步是运行 5 个代表性场景的 pilot，确认评分和结果格式后冻结 prompt，再开始正式实验。
