# MiniAgent Benchmark Harness

这个目录保存 MiniAgent harness 的任务集、输入 fixtures、临时工作区和评测报告。

## Commands

推荐使用 harness 命令：

```powershell
D:\conda\envs\assistant\python.exe miniagent.py harness
D:\conda\envs\assistant\python.exe miniagent.py harness memory
```

兼容旧命令：

```powershell
D:\conda\envs\assistant\python.exe miniagent.py benchmark
D:\conda\envs\assistant\python.exe miniagent.py benchmark memory
```

## Task Files

| 文件 | 说明 |
| --- | --- |
| `tasks.json` | 端到端 Agent 任务，包括普通问答、附件读取、xlsx/docx/pdf 文件操作 |
| `memory_retrieval_tasks.json` | Memory retrieval 任务，包括 memory items 和 query 标准答案 |

## Reports

报告输出到：

```text
workspace/benchmarks/results/
```

主要报告：

| 文件 | 说明 |
| --- | --- |
| `latest.md` | 最近一次 Agent Task Harness 的 Markdown 报告 |
| `<run_id>.json` | 某次 Agent Task Harness 的完整 JSON 报告 |
| `memory_retrieval_latest.md` | 最近一次 Memory Retrieval Harness 的 Markdown 报告 |
| `memory_retrieval_<run_id>.json` | 某次 memory retrieval 的完整 JSON 报告 |

## Agent Task Pass Criteria

每个任务可以配置以下验收项：

- `expected_reply_contains`: 最终回复必须包含的文本。
- `expected_tools_all`: 必须全部调用的工具。
- `expected_tools_any`: 至少调用其中一个工具。
- `expected_outbox_suffixes`: 必须生成指定后缀文件。
- `expected_outbox_files`: 打开生成文件做内容精准验收。
- `expected_max_tool_calls`: 工具调用次数上限。

文件内容精准验收支持：

- `.xlsx`: `contains_all`、`contains_any`、`not_contains`、`sheet`、`min_rows`、`max_rows`
- `.docx`: `contains_all`、`contains_any`、`not_contains`
- `.pdf`: `contains_all`、`contains_any`、`not_contains`
- `.txt/.md/.json/.csv`: 文本包含断言

## Memory Retrieval Metrics

Memory retrieval harness 会统计：

- `Recall@1`
- `Recall@3`
- `Recall@5`
- `Recall@task_k`
- `MRR`
- 每条 query 的命中 rank

它使用临时 workspace 构建 `memory_store.jsonl`，不会污染真实记忆。

## Why Harness Matters

Harness 不是普通单元测试，而是 Agent 工程中的“行为评测系统”。它回答的问题是：

- 模型是否真的调用了工具？
- 文件是否真的生成了？
- 生成文件内容是否正确？
- 平均需要多少步？
- 失败集中在哪些类型？
- memory 相似度检索和 rerank 能否召回正确条目？

