# Standalone Stirrup Multi-Turn Benchmark

这是从 AssetOpsBench 中抽出的独立可运行项目。它不导入
`assetopsbench/src`，也不使用旧 Supervisor/Specialist 系统。项目包含：

- Stirrup 0.2 真多用户轮次 runner；
- 1,076 条 MaintIE gold-release 数据和只读 MCP server；
- 50 个正式多轮场景、50 个配对单轮控制和 16 个开发场景；
- 逐轮/对话级评估、单轮对照退化比较；
- 一次真实 WTB01 四轮 PoC 的轨迹与评分输入；
- 数据重建脚本和独立测试。

## 目录

```text
.
├── pyproject.toml
├── run.sh                         # 跑场景并评分
├── check.sh                       # 离线自检
├── data/
│   ├── wtb50.jsonl
│   ├── wtb50_single_turn.jsonl
│   ├── assetops16.jsonl
│   ├── audit.csv
│   └── audit_summary.json
├── source/                        # 可重建数据集的原始输入
├── poc/                           # 已有真实四轮轨迹和报告
├── src/stirrup_benchmark/
│   ├── runner.py
│   ├── cli.py
│   ├── schema.py
│   ├── trajectory.py
│   ├── evaluate.py
│   ├── compare.py
│   ├── dataset_builder.py
│   └── maintie/
└── tests/
```

## 立即验证（不调用模型）

需要 Python 3.12+ 和 `uv`：

```bash
cd /Users/brianbai/Multi-Turn-AssetOps/stirrup-multiturn-benchmark
./check.sh
```

也可以只做一次 dry-run：

```bash
./run.sh --dry-run
```

dry-run 会验证场景、MaintIE 数据、选择器和运行配置，不读取 API key。

## 跑一个真实四轮场景

复制 `.env.example` 为 `.env` 并填写 OpenAI-compatible endpoint：

```bash
MODEL_ID=litellm_proxy/deepseek-v4-flash \
SCENARIO_IDS=WTB01 \
./run.sh
```

如果现有变量使用其他前缀，例如
`DEEPSEEK_BASE_URL`/`DEEPSEEK_API_KEY`：

```bash
ENV_FILE=/path/to/.env \
ROUTER_ENV_PREFIX=DEEPSEEK \
MODEL_ID=litellm_proxy/deepseek-v4-flash \
SCENARIO_IDS=WTB01 \
./run.sh
```

凭证只在进程内映射，不会复制到项目。

## 跑完整 50 场

这会产生模型 API 费用：

```bash
SCENARIO_IDS=all ./run.sh
```

结果写到：

```text
results/trajectories/stirrup_mt_<scenario-id>.json
results/report.json
```

## 单轮控制和退化比较

```bash
SCENARIO_FILE=data/wtb50_single_turn.jsonl \
SCENARIO_IDS=all \
OUTPUT_DIR=control-results \
./run.sh

uv run compare-multi-turn \
  --multi-turn-report results/report.json \
  --single-turn-report control-results/report.json \
  --output degradation.json
```

## 数据重建

```bash
uv run build-multi-turn-data
```

审计结论是 66 个候选对话、215 个用户轮次，其中 50 个 WTB 场景满足
可执行和正式评分条件。16 个旧对话保留为 development 数据，但因为缺少
场景级数据包和逐轮真值，不进入正式评分。

## 数据许可

MaintIE gold release 来自 `nlp-tlp/maintie`，固定到上游提交
`825e7710e4129598da997276a38b3cb40b200bc2`。MIT 许可和来源说明保存在
`src/stirrup_benchmark/maintie/data/`；项目代码保留 Apache-2.0 许可。

