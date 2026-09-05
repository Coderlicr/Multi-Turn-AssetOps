# Stirrup Agent 与多轮 Benchmark：源码关系、改动、位置和运行说明

## 1. 文档目的

本文记录以下问题：

1. Stirrup Agent 与 IBM AssetOpsBench 原仓库是什么关系；
2. Stirrup Agent 在原仓库中的位置；
3. IBM 官方原始实现如何工作；
4. 为支持真正的多用户轮次，修改和新增了哪些内容；
5. 原 benchmark 与多轮 benchmark 有什么区别；
6. 当前两份实现分别位于哪里；
7. 如何运行依赖官方源码的版本和完全独立的版本；
8. 场景、运行轨迹和评分报告分别是什么格式。

需求依据是：

```text
/Users/brianbai/Desktop/Stirrup_MultiTurn_Benchmark_Work_Guide_CN.pdf
```

当前实现基于 IBM AssetOpsBench 官方提交：

```text
repository: https://github.com/IBM/AssetOpsBench.git
commit:     aac711fe8defdbd310ca8a6bc6a21547e69036ea
date:       2026-08-31
message:    Merge pull request #529 from IBM/upgrade-stirrup-agent-0.2.0
```

---

## 2. 最重要的概念边界

这里涉及三个不同层次，不应混为一谈。

### 2.1 Stirrup 框架

Stirrup 是 Artificial Analysis 提供的外部 Python Agent 框架。它不是 IBM
AssetOpsBench 仓库中的源码，而是通过 Python 依赖安装：

```toml
stirrup[docker,litellm,mcp]>=0.2.0
```

Stirrup 提供：

- `Agent` 和 `Agent.session()`；
- 模型客户端；
- Agent 的模型/工具循环；
- MCP Tool Provider；
- 上下文压缩；
- Assistant、User、Tool 等消息模型；
- `finish` 工具机制。

### 2.2 IBM AssetOpsBench 中的 Stirrup adapter

IBM 原仓库没有复制 Stirrup 框架源码，而是实现了一个适配器，将外部
Stirrup 框架接入 AssetOpsBench 的 MCP server、轨迹和评估系统。

官方 adapter 位于：

```text
assetopsbench/src/agent/stirrup_agent/
├── __init__.py
├── cli.py
├── finish_tool.py
├── handoff_tools.py
├── runner.py
├── trajectory.py
└── workspace_bridge.py
```

其中最核心的是：

```text
assetopsbench/src/agent/stirrup_agent/runner.py
```

### 2.3 Benchmark

Benchmark 不是 Agent 本身。Benchmark 负责：

- 定义问题和真值；
- 准备/重置环境；
- 选择 Agent 和模型；
- 启动 Agent；
- 保存运行轨迹；
- 计算评分；
- 汇总不同模型或不同设置的结果。

因此当前系统边界是：

```text
AssetOpsBench / 多轮 Benchmark    环境、问题、数据、运行和评分
Stirrup                          唯一被测 Agent 框架
MaintIE MCP                     被 Agent 调用的领域工具和数据
模型 API                         Stirrup 使用的推理模型
```

---

## 3. IBM 官方原始实现如何依赖 `src`

官方仓库本来就是 Python `src-layout`：

```text
assetopsbench/
├── pyproject.toml
└── src/
    ├── agent/
    ├── benchmark/
    ├── evaluation/
    ├── llm/
    ├── observability/
    ├── servers/
    └── mcphub/
```

官方 Stirrup runner 原本就依赖同一仓库 `src` 中的模块：

```python
from observability import agent_run_span, persist_trajectory
from llm.routers import resolve_model, resolve_router_creds
from .._prompts import AGENT_SYSTEM_PROMPT
from ..models import AgentResult, Trajectory
from ..runner import AgentRunner
from .finish_tool import ASSETOPS_FINISH_TOOL
from .trajectory import build_trajectory, classify_tool, final_answer
from .handoff_tools import build_handoff_tools
```

所以，“依赖官方仓库的 `src`”是 IBM 原始实现的设计，不是多轮改造后来
引入的。

原始依赖关系如下：

```text
IBM Stirrup adapter
├── 外部 Stirrup Python 包
├── src/agent                 Agent 接口、prompt、结果类型
├── src/llm                   模型 ID 和 router 凭证解析
├── src/observability         trace 与 trajectory 持久化
└── src/servers               IoT、WO、FMSR、TSFM 等 MCP server
```

---

## 4. IBM 官方原始 Stirrup runner 如何工作

原始 runner 的主要步骤为：

```text
question
   │
   ▼
构造模型 client
   │
   ▼
启动选定的 AssetOpsBench MCP servers
   │
   ▼
构造 Stirrup Agent
   │
   ▼
进入 agent.session()
   │
   ▼
session.run(question)
   │
   ├── 模型生成
   ├── MCP 工具调用
   ├── 模型继续生成
   └── finish
   │
   ▼
将 Stirrup history 转成 AssetOpsBench Trajectory
   │
   ▼
保存答案、工具调用、token 和 timing
```

原始核心调用只有一次：

```python
async with agent.session() as session:
    finish_params, history, metadata = await session.run(question)
```

它支持的是“一个用户问题内部的多步 Agent/工具循环”，不是多个用户消息
组成的真实连续对话。

---

## 5. 在官方源码版本中做了什么改动

依赖官方源码的多轮版本位于：

```text
/Users/brianbai/Multi-Turn-AssetOps/assetopsbench
```

它仍然保留 IBM 官方完整仓库结构，并在其内部加入多轮能力。

### 5.1 修改的官方文件

| 文件 | 改动 |
|---|---|
| `pyproject.toml` | 注册 MaintIE、多轮 runner、评估和比较命令 |
| `src/agent/models.py` | 增加 `UserTurnRecord`、`ConversationTrajectory`、`ConversationResult` |
| `src/agent/stirrup_agent/runner.py` | 抽取统一 Agent factory，增加 `run_conversation()` |
| `src/agent/stirrup_agent/trajectory.py` | 增加历史消息去重、当前轮提取和存活上下文传递 |
| `src/agent/stirrup_agent/tests/test_runner.py` | 增加同 session、多轮上下文和轨迹分层测试 |

### 5.2 新增的文件和目录

```text
assetopsbench/
├── benchmarks/
│   ├── run_multi_turn.sh
│   └── multi_turn/
│       ├── README.md
│       ├── source/
│       ├── data/
│       └── poc/
├── scripts/
│   └── build_multi_turn_dataset.py
└── src/
    ├── benchmark/
    │   ├── multi_turn_runner.py
    │   ├── multi_turn_schema.py
    │   └── tests/test_multi_turn.py
    ├── evaluation/
    │   ├── multi_turn.py
    │   ├── multi_turn_compare.py
    │   └── tests/test_multi_turn.py
    └── servers/
        └── maintie/
```

### 5.3 真多轮实现

新实现只创建一个 Agent 和一个 session，然后逐轮注入消息：

```python
async with agent.session() as session:
    for message in user_messages:
        finish_params, history, metadata = await session.run(
            [*conversation_context, UserMessage(content=message)]
        )
        conversation_context = active_conversation_context(history)
```

关键约束：

1. 一个场景的所有用户轮次共用一个 Stirrup session；
2. MCP provider 在整个对话期间保持开启；
3. 每次只追加当前用户消息；
4. 不提前暴露未来用户轮次；
5. 下一轮获得前一轮存活的 User、Assistant、Tool 和摘要上下文；
6. 保存时区分“用户轮次”和“内部 Agent step”。

保存结构为：

```text
ConversationTrajectory
└── user_turns[]                       真实用户轮次
    ├── user_message
    ├── answer
    ├── duration_ms
    └── trajectory
        └── turns[]                    Stirrup 内部 Agent steps
            ├── text
            ├── input/output tokens
            └── tool_calls[]
```

### 5.4 `max_turns` 的处理

Stirrup 0.2 会把传入的历史 Assistant messages 计入 `max_turns`。如果不处理，
前几轮的历史步骤可能耗尽后续轮次的预算。

多轮 runner 因此使用：

```python
session._max_turns = prior_agent_steps + per_user_turn_budget
```

这保证每个真实用户轮次都获得配置的 Agent-step 预算。这里使用了 Stirrup
0.2 的内部字段，是未来升级 Stirrup 时需要重点回归的版本耦合点。

---

## 6. 原 Benchmark 是什么格式

IBM 官方原始 benchmark 以单问题场景目录为单位：

```text
scenario_<id>/
├── question.txt
├── manifest.json
└── groundtruth.txt
```

Profile YAML 或场景 ID 文件决定运行哪些场景。主要运行器是：

```text
assetopsbench/src/benchmark/scenario_suite_runner.py
```

官方 shell runner 是：

```text
assetopsbench/benchmarks/run.sh
```

它循环模型配置，然后对每个场景执行一次独立问题运行。这种格式无法原生
表达：

- Turn 2 对 Turn 1 的指代；
- 跨轮信息累积；
- 后续约束更新；
- 跨轮工具结果复用；
- 用户纠正或澄清；
- 逐用户轮次评分。

---

## 7. 多轮 Benchmark 改了什么

### 7.1 样本单位改变

原来：

```text
一个 benchmark case = 一个问题
```

现在：

```text
一个 benchmark case = 一整个多轮对话
```

### 7.2 统一 JSONL schema

每一行是一个完整场景：

```json
{
  "schema_version": "1.0",
  "scenario_id": "WTB01",
  "source": "mentor_wtb50",
  "split": "main",
  "overall_user_goal": "...",
  "overall_expected_outcome": "...",
  "context_dependency": [
    "reference_resolution",
    "information_accumulation",
    "constraint_update",
    "cross_turn_tool_use"
  ],
  "required_tools": ["maintie"],
  "executable": true,
  "valid_multi_turn": true,
  "ground_truth_available": true,
  "turns": [
    {
      "turn_id": 1,
      "turn_type": "task",
      "user_message": "...",
      "dependency_on_previous_turns": "...",
      "dependency_types": [],
      "expected_information": "...",
      "expected_tool_behavior": [["count", "count"]],
      "accepted_tool_plans": [
        [["count", "count"]],
        [["group_count"]],
        [["compare"]]
      ],
      "ground_truth": {
        "replace": 347,
        "repair": 127
      }
    }
  ]
}
```

依赖类型包括：

```text
reference_resolution       指代解析
information_accumulation   信息累积
constraint_update          约束更新
cross_turn_tool_use        跨轮工具使用
correction_clarification   纠正/澄清
```

### 7.3 数据集审计

候选池：

```text
66 个候选对话
215 个用户轮次
├── 原 16 个对话：63 轮
└── Mentor/WTB 50 个对话：152 轮
```

审计结论：

```text
valid multi-turn:       66
executable:             50
formal evaluation set: 50
paired controls:        50
```

50 个 WTB 场景具备 MaintIE 工具环境、客观可评分轮次真值以及工具策略，因此
作为正式集合。

16 个旧对话虽然具有真实多轮依赖，但缺少场景专用数据 manifest 和逐轮
ground truth，因此设置为：

```json
{
  "split": "development",
  "executable": false,
  "ground_truth_available": false
}
```

它们不会被伪装成正式可评分场景。

### 7.4 单轮配对控制

每个正式多轮场景都生成一个单轮版本：

```text
WTB01    多轮实验
ST-WTB01 单轮控制
```

单轮控制把原来的所有用户轮次一次性给出，并使用：

```json
{
  "scenario_id": "ST-WTB01",
  "paired_scenario_id": "WTB01",
  "valid_multi_turn": false
}
```

这样可以比较同一个任务：

```text
完整信息一次性给出时的表现
              vs
信息在多个用户轮次逐渐给出时的表现
```

### 7.5 MaintIE MCP

新增的 MaintIE MCP server 使用 1,076 条人工修正 gold-release work orders，
提供以下只读工具：

```text
search
extract
count
group_count
rank
get_text
compare
```

它不使用 CouchDB，也没有写接口。工具支持通过 `within_ids` 跨轮复用前序
结果集。

### 7.6 评估指标

逐轮指标：

- 是否有客观 ground truth；
- 答案是否正确；
- 是否应该调用工具；
- 实际工具路径；
- 是否匹配某个 accepted tool plan；
- 当前轮任务是否成功。

对话级指标：

- APR：Accomplish Progress Rate；
- OPR：Optimal Path Rate；
- overall task success；
- context retention；
- error-propagation resilience；
- reference resolution 等依赖能力分数；
- multi-turn degradation。

答案正确性和工具路径效率被分开：答案正确但存在冗余调用时，任务仍可成功，
但 OPR 会下降。

没有客观 ground truth 的 chat/clarify 轮次使用：

```json
{
  "answer_scored": false,
  "answer_correct": null,
  "turn_success": null
}
```

它们不会被自动算成正确答案；工具/不使用工具的决策仍可独立评估。

### 7.7 当前两场景静态 JSON 试运行（2026-09-05）

根据当前试运行要求，只选择两个场景：

```text
A16-06   来自旧 16 个多轮对话
WTB01    来自新 50 个多轮对话
```

它们使用 AssetOpsBench 原有的场景目录约定，并增加一个多轮文件：

```text
src/couchdb/scenarios_data/scenario_<id>/
├── manifest.json       运行前需要装载的环境状态
├── question.txt        便于人阅读的完整对话文本
├── groundtruth.txt     最终答案的静态 JSON 真值
└── conversation.json   有序用户轮次、跨轮依赖和工具期望
```

loader 会强制验证 `conversation.json` 最后一轮的 `ground_truth` 与
`groundtruth.txt` 完全相同，防止两份真值发生漂移。

`A16-06` 是对旧场景的可执行 pilot 改编：原始 16 个场景的审计 JSONL 仍保持
原样并标记为 development；试运行目录单独补充了场景级 CouchDB manifest、
故障模式数据以及可静态评分的最终输出约束。这不代表旧 16 个场景已经全部
具备可执行真值。

`WTB01` 使用 MaintIE 的 1,076 条只读工单，不需要 CouchDB，因此它的
`manifest.json` 是空对象。

本次默认设置为：

```text
Agent:                  Stirrup 0.2.0 / StirrupAgentRunner
Model:                  tokenrouter/z-ai/glm-5.3-free
Temperature:            0
Reasoning effort:       不显式传入，使用 provider 默认值
Code execution:         关闭
Agent-step budget:      每个真实用户轮次 12 步
Conversation state:     一个持续存在的 Stirrup + MCP session
Final scorer:           static_json 严格结构匹配
```

标准评估仍写出完整报告；额外的 `poor-performance.json` 只保留最终答案未通过
严格静态 JSON 匹配的场景。如果两个场景都通过，该文件中的
`poor_scenarios` 是空数组。

---

## 8. 当前 Benchmark 在哪里

目前保留两份。

### 8.1 依赖 IBM 官方源码的多轮版

位置：

```text
/Users/brianbai/Multi-Turn-AssetOps/assetopsbench
```

主要文件：

```text
assetopsbench/
├── src/agent/stirrup_agent/runner.py
├── src/agent/stirrup_agent/trajectory.py
├── src/agent/models.py
├── src/benchmark/multi_turn_schema.py
├── src/benchmark/multi_turn_runner.py
├── src/evaluation/multi_turn.py
├── src/evaluation/multi_turn_compare.py
├── src/servers/maintie/
├── scripts/build_multi_turn_dataset.py
├── benchmarks/run_multi_turn.sh
└── benchmarks/multi_turn/
    ├── README.md
    ├── source/
    ├── data/
    └── poc/
```

这一份适合：

- 继续和 IBM AssetOpsBench 上游同步；
- 与官方其他 Agent/benchmark 比较；
- 继续复用官方 observability、model router 和 server 架构；
- 将来向上游提交 patch。

### 8.2 完全独立版

位置：

```text
/Users/brianbai/Multi-Turn-AssetOps/stirrup-multiturn-benchmark
```

结构：

```text
stirrup-multiturn-benchmark/
├── pyproject.toml
├── uv.lock
├── run.sh
├── check.sh
├── README.md
├── PROVENANCE.md
├── data/
│   ├── wtb50.jsonl
│   ├── wtb50_single_turn.jsonl
│   ├── assetops16.jsonl
│   ├── audit.csv
│   └── audit_summary.json
├── source/
├── poc/
│   ├── report.json
│   └── trajectories/stirrup_mt_WTB01.json
├── src/stirrup_benchmark/
│   ├── runner.py
│   ├── cli.py
│   ├── schema.py
│   ├── models.py
│   ├── trajectory.py
│   ├── finish_tool.py
│   ├── evaluate.py
│   ├── compare.py
│   ├── dataset_builder.py
│   ├── selfcheck.py
│   └── maintie/
└── tests/
```

这一份不导入原 AssetOpsBench 的：

```text
src/agent
src/benchmark
src/evaluation
src/llm
src/observability
src/servers
```

它适合：

- 单独交付；
- 在没有完整 AssetOpsBench 的环境中运行；
- 快速复现实验；
- 只研究 Stirrup 多轮能力和 MaintIE WTB50。

两份代码不会自动同步。当前建议：

```text
assetopsbench/                  上游集成和开发版本
stirrup-multiturn-benchmark/    独立发布和复现版本
```

对其中一份继续修改时，需要决定是否将同样的改动同步到另一份。

---

## 9. 如何运行依赖官方源码的版本

### 9.1 安装

```bash
cd /Users/brianbai/Multi-Turn-AssetOps/assetopsbench
uv sync --group dev
```

### 9.2 检查两场景配置（不调用模型和数据库）

```bash
DRY_RUN=1 ./benchmarks/run_multi_turn.sh
```

### 9.3 准备本地凭证与 CouchDB

```bash
cp .env.public .env
# 在 .env 中设置 TOKENROUTER_API_KEY，不要提交该文件
docker compose -f src/couchdb/docker-compose.yaml up -d
```

`TOKENROUTER_BASE_URL` 默认为 `https://api.tokenrouter.com/v1`。截至
2026-09-05，TokenRouter 当前模型页将 `z-ai/glm-5.3-free` 列为输入和输出均
为零费用的 OpenAI-compatible 模型：

```text
https://www.tokenrouter.com/models/z-ai/glm-5.3-free/
```

### 9.4 只运行两个场景并严格评分

默认脚本已经固定 `A16-06,WTB01`，运行命令为：

```bash
ENV_FILE=.env ./benchmarks/run_multi_turn.sh
```

脚本按以下顺序执行：

1. 按场景 manifest 重置和装载 CouchDB；
2. 在同一场景内保持一个 Stirrup session，逐轮运行；
3. 使用官方 `evaluate` 命令和 `static_json` scorer 比对最终答案；
4. 从完整报告中筛出低表现场景。

输出位置：

```text
benchmarks/multi_turn/results/two_scenario_pilot/
├── trajectories/                 完整运行轨迹
├── static-json-report/            官方完整评分报告
└── poor-performance.json          只含未通过场景
```

除非显式覆盖 `SCENARIO_IDS`，此命令不会扩展到其他场景。

---

## 10. 如何运行完全独立版

### 10.1 完整离线自检

```bash
cd /Users/brianbai/Multi-Turn-AssetOps/stirrup-multiturn-benchmark
./check.sh
```

`check.sh` 会：

1. 根据 `uv.lock` 创建/同步独立环境；
2. 重建数据；
3. 运行单元测试；
4. 实际启动 MaintIE MCP 子进程；
5. 枚举 7 个 MCP tools；
6. 调用 `count` 并验证数据量为 1,076；
7. 执行 WTB01 dry-run；
8. 对 bundled PoC 重新评分。

### 10.2 只做 dry-run

```bash
./run.sh --dry-run
```

### 10.3 真实运行 WTB01

```bash
ENV_FILE=../.env \
ROUTER_ENV_PREFIX=DEEPSEEK \
MODEL_ID=litellm_proxy/deepseek-v4-flash \
SCENARIO_IDS=WTB01 \
./run.sh
```

### 10.4 运行全部 50 个多轮场景

```bash
SCENARIO_IDS=all ./run.sh
```

### 10.5 运行 50 个单轮控制

```bash
SCENARIO_FILE=data/wtb50_single_turn.jsonl \
SCENARIO_IDS=all \
OUTPUT_DIR=control-results \
./run.sh
```

### 10.6 计算多轮退化

```bash
uv run compare-multi-turn \
  --multi-turn-report results/report.json \
  --single-turn-report control-results/report.json \
  --output degradation.json
```

独立版为了兼容 Stirrup 0.2，明确锁定：

```toml
mcp>=1.26.0,<2
stirrup[litellm,mcp]>=0.2.0,<0.3
```

MCP 2.x 改变了 Stirrup 0.2 使用的 client API，因此不能无约束升级到 MCP
2.x。

---

## 11. 运行轨迹长什么样

每次运行生成：

```text
stirrup_mt_<scenario-id>.json
```

示意：

```json
{
  "run_id": "stirrup_mt_WTB01",
  "scenario_id": "WTB01",
  "runner": "stirrup-agent-multi-turn",
  "model": "litellm_proxy/deepseek-v4-flash",
  "question": "User turn 1: ...\nUser turn 2: ...",
  "answer": "...",
  "trajectory": {
    "started_at": "...",
    "user_turns": [
      {
        "index": 0,
        "user_message": "...",
        "answer": "...",
        "duration_ms": 1234.5,
        "trajectory": {
          "turns": [
            {
              "index": 0,
              "text": "...",
              "input_tokens": 100,
              "output_tokens": 20,
              "tool_calls": [
                {
                  "name": "maintie__rank",
                  "input": {},
                  "output": "...",
                  "duration_ms": 12.3
                }
              ]
            }
          ]
        }
      }
    ]
  }
}
```

---

## 12. 评分报告长什么样

```json
{
  "scenario_count": 1,
  "optimal_path_rate": 0.25,
  "accomplish_progress_rate": 1.0,
  "overall_task_success_rate": 1.0,
  "results": [
    {
      "scenario_id": "WTB01",
      "user_turns_expected": 4,
      "user_turns_observed": 4,
      "context_retention": 1.0,
      "error_propagation_resilience": 1.0,
      "overall_task_success": true,
      "capabilities": {
        "reference_resolution": 1.0,
        "information_accumulation": 1.0,
        "constraint_update": 1.0,
        "cross_turn_tool_use": 0.3333333333
      },
      "turns": []
    }
  ]
}
```

当前两份实现都保留了真实 WTB01 PoC。独立版的 PoC 是直接从独立目录自身
启动 MCP 和 Stirrup 后重新生成的，不是仅复制代码后做静态验证。

---

## 13. 当前验证状态

依赖官方源码的多轮版：

```text
两场景/多轮/评估相关 tests:             78 passed
两场景 dry-run:                         passed
static_json 失败筛选链路:                passed
Ruff:                                   passed
git diff --check:                       passed
```

真实 TokenRouter/GLM 运行需要本机设置 `TOKENROUTER_API_KEY`。在没有该凭证
时，不生成或冒充模型结果；仍可完整执行 schema、dry-run、CouchDB 数据和
静态评分链路验证。

独立版：

```text
独立 tests:                    9 passed
MaintIE MCP subprocess:        passed
MaintIE tools:                 7
MaintIE records:               1076
隔离虚拟环境 dry-run:          passed
独立 WTB01 真实四轮运行:        passed
APR:                           1.0
overall task success:          1.0
context retention:             1.0
OPR:                           0.25
```

OPR 为 0.25 是因为模型得到正确答案时执行了冗余工具调用，而不是对话失败。

---

## 14. 当前未执行的工作

尚未执行完整的：

```text
50 个多轮场景
+
50 个单轮控制场景
```

的付费模型矩阵。两份实现都已经具备运行能力，但完整实验需要明确模型、
推理设置、并发、重试策略和 API 费用预算。

---

## 15. 凭证与安全

仓库和独立目录不包含 API key。真实运行通过 `.env` 或进程环境变量加载：

```text
LITELLM_BASE_URL
LITELLM_API_KEY
TOKENROUTER_BASE_URL
TOKENROUTER_API_KEY
```

也可以通过 `--router-env-prefix` 将其他前缀的变量仅在当前进程中映射到
LiteLLM 变量。不要将真实 `.env`、API key 或模型 provider token 提交到
任一目录。
