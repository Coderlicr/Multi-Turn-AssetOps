# AssetOpsBench Agent Refactoring — Change Log

> 每个 Phase 完成后在此记录改动内容、文件变更和后续计划。

---

## Phase 1 — Structured Foundation (2026-04-05)

**目标**：在不改变架构的前提下加固现有管线——强类型模型、artifact 追踪、step 验证、失败重试。仍然只有一个 PlanExecuteRunner，没有新 agent。

### 1. 强类型 Pydantic 模型 (`src/agent/models.py`)

- 新增 `TaskStatus` 枚举：`pending / running / success / failed / skipped`
- 新增 `PlanStepV2`、`PlanV2`、`StepResultV2`（Pydantic BaseModel），通过 `from_legacy()` 包装现有 dataclass，**不替换文本解析逻辑**
- `PlanV2.independent_groups()` 按依赖关系分组，为未来并行执行铺路

### 2. Artifact 追踪 (`src/agent/artifacts.py` — 新文件)

- `Artifact` 模型：记录每步产出的元数据（type、step、server、summary、raw_data、依赖链）
- `ArtifactRegistry`：内存 dict 存储，支持 `register / get / get_by_step / lineage`
- Summary 用 `text[:200]` 简单截断，不调 LLM

### 3. Step 验证器 (`src/agent/validator.py` — 新文件)

- `validate_step()` 做三项纯规则检查：有无 error、响应是否为空、JSON 是否合法
- 返回 `ValidationResult(passed, reason, action="continue" | "retry" | "replan")`

### 4. 重试 + 重规划

- **Executor** (`src/agent/plan_execute/executor.py`)：新增 `execute_plan_v2()` 方法——每步执行后过 validator，失败则 retry（默认最多 2 次重试），每次成功都注册 artifact
- **Planner** (`src/agent/plan_execute/planner.py`)：新增 `replan()` 方法 + `_REPLAN_PROMPT`——当步骤耗尽重试后，让 LLM 基于已完成步骤和失败原因重新规划剩余步骤
- **Runner** (`src/agent/plan_execute/runner.py`)：`run()` 内部切换到 V2 管线（PlanV2 → execute_plan_v2 → 检查失败 → replan），返回值仍是原始 `OrchestratorResult`，CLI 完全无感知

### 文件变更汇总

| 文件 | 状态 | 说明 |
|------|------|------|
| `src/agent/models.py` | 修改 | 新增 TaskStatus、PlanStepV2、PlanV2、StepResultV2 |
| `src/agent/artifacts.py` | 新建 | Artifact + ArtifactRegistry |
| `src/agent/validator.py` | 新建 | ValidationResult + validate_step |
| `src/agent/plan_execute/executor.py` | 修改 | 新增 execute_plan_v2（验证 + 重试 + artifact） |
| `src/agent/plan_execute/planner.py` | 修改 | 新增 replan() + _REPLAN_PROMPT |
| `src/agent/plan_execute/runner.py` | 修改 | run() 内部走 V2 管线 |
| `src/agent/__init__.py` | 修改 | 导出新增符号 |
| `src/agent/tests/test_artifacts.py` | 新建 | 20 tests |
| `src/agent/tests/test_validator.py` | 新建 | 8 tests |
| `src/agent/tests/test_phase1_models.py` | 新建 | 11 tests |
| `src/agent/tests/test_phase1_integration.py` | 新建 | 7 tests（retry、max-retries、lineage、re-plan） |

### 测试结果

- 原有 66 tests：全部通过（无退化）
- 新增 46 tests：全部通过
- 合计 **112 passed, 0 failed**

---

## Phase 2 — Blackboard, World Model Interface, and State Machine（计划）

**目标**：引入全局共享状态层，添加工作流阶段追踪（状态机）和 world model 接口。仍然是单编排器，多 agent 拆分留到 Phase 3。

| 模块 | 文件 | 内容 |
|------|------|------|
| **Blackboard** | `src/agent/blackboard.py` | 全局共享状态对象（Pydantic），替代 executor 里 ad-hoc 的 `context: dict`。包含 intent、identified_assets、workflow_phase、world_state、artifact_ids、constraints 等字段 |
| **状态机** | `src/agent/state_machine.py` | 纯函数 `try_transition(blackboard, trigger)` 驱动工作流阶段：INTAKE → INVESTIGATING → DIAGNOSING → ACTIONING → CLOSED，含反向回退（info_gap → 退回 INVESTIGATING）。每个阶段限定可调用的 MCP server 集合 |
| **World Model** | `src/agent/world_model.py` | `WorldModelInterface`：基于 artifact 类型用规则更新 `AssetBelief`（健康状态、假说、信息缺口）。Phase 2 是规则版，Phase 4+ 可替换为 LLM/知识图谱版 |
| **Runner V2** | `src/agent/plan_execute/runner.py` | run() 流程变成：初始化 Blackboard → 意图分类 → 按 phase 限定可用 server → plan → execute_plan_v2 → 更新 world model → 检查状态机转移 → 用 world model summary 做摘要 |

**关键约束**：仍然是单个 PlanExecuteRunner 编排，不引入多 agent。Phase 1 的 ArtifactRegistry 和 validator 直接复用。

---

## Phase 3 — Multi-Agent Split and Parallel Execution（计划）

**目标**：将单一 executor 拆分为 Supervisor + Specialist 架构，启用并行执行，引入 MCP session 复用。

| 模块 | 文件 | 内容 |
|------|------|------|
| **Supervisor** | `src/agent/supervisor.py` | 新的编排层。读 blackboard → 生成 task DAG → 分发给 specialist → 每步后更新 blackboard + world model + 检查状态机 → phase 变化则生成下一轮 DAG |
| **Specialist Executor** | `src/agent/specialist.py` | 限定作用域的执行器，每个绑定一个 MCP server。内置 ReAct 式 retry，失败后上报 Supervisor（不自行 re-plan） |
| **MCP Session Pool** | `src/agent/mcp_pool.py` | 持久化 MCP stdio session，启动时连接一次后续复用，避免每次 `_call_tool` 的冷启动开销 |
| **并行执行** | Supervisor 内 | 利用 `PlanV2.independent_groups()` 识别无依赖步骤，`asyncio.gather()` 并行调度到不同 Specialist |

**关键变化**：Phase 3 才真正出现多 agent 架构——Supervisor 负责全局编排和状态管理，Specialist 负责单 server 的工具调用。Phase 1/2 建立的 Blackboard、ArtifactRegistry、状态机、validator 都成为 Supervisor 和 Specialist 之间的共享协议。
