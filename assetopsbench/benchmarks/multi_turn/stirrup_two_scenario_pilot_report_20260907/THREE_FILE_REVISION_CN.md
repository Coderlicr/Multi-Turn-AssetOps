# 三文件格式修订与验证

场景目录现在只包含 manifest.json、question.txt、groundtruth.txt。
conversation.json 已删除，多轮消息直接从 question.txt 的 `User turn N:`
分隔标记读取。运行时每次只发送当前轮，保持同一 Stirrup session。

A16-06 保留 Chiller 6 问题。临时 failure_modes.json 已删除，manifest 改为
引用官方已有的 shared/fmea/failure_modes_sample.json。核对结果：该共享文件
与 IBM 提交 aac711fe8defdbd310ca8a6bc6a21547e69036ea 逐字节一致，但只有 pump
的 seal leakage / impeller wear，标记为 synthetic sample、exhaustive=false。
这是来源核实，不是 Chiller 6 故障可检测性的验证。

按照用户确认，A16-06 的 groundtruth.txt 设为 null，暂缓正式评分。
runner 在数据库和模型调用前拒绝正式运行该场景；标准评估器排除该场景。
null 不代表“正确答案为空”。本报告原有 A16 结果只保留为历史流程验证记录。

验证结果：

- 75 项相关测试通过，包括消息解析、同 session 多轮、缺失真值阻断和评分排除。
- 源码目录及本报告目录的两个场景均恰好三个文件，16 处 manifest 数据引用全部有效。
- WTB01 首次真实重跑遇到免费端点每分钟 8 请求的 429 限流；未得到完整结果。
- 添加 8 秒最小请求间隔后，WTB01 真实完成 4 轮，最终 static_json 得分 1.0。
- 完成运行耗时 161.1 秒，输入 token 82537，输出 token 3934，工具调用 21 次（含 finish）。
- A16-06 未进行新的正式模型评测。

新的评分和完整轨迹位于仓库的：
benchmarks/multi_turn/results/three_file_verification_paced/

运行当前可评分场景：

```bash
cd assetopsbench
SCENARIO_IDS=WTB01 ENV_FILE=.env ./benchmarks/run_multi_turn.sh
```

若不设置 SCENARIO_IDS，默认两场景运行会明确报出 A16-06 的暂停原因。
