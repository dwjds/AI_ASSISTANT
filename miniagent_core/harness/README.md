# MiniAgent Harness Engineering

`miniagent_core.harness` 是 MiniAgent 的评测工程入口。它把 Agent 任务、文件处理任务、memory retrieval 任务组织成可重复运行的 harness，用于持续衡量系统改动是否真的提升了 Agent 能力。

当前 harness 复用 `miniagent_core.benchmark` 的实现，并提供更稳定的工程命名：

```powershell
D:\conda\envs\assistant\python.exe miniagent.py harness
D:\conda\envs\assistant\python.exe miniagent.py harness memory
```

兼容旧命令：

```powershell
D:\conda\envs\assistant\python.exe miniagent.py benchmark
D:\conda\envs\assistant\python.exe miniagent.py benchmark memory
```

## Scope

当前 harness 覆盖两类评测：

| Suite | 命令 | 目标 |
| --- | --- | --- |
| Agent Task Harness | `miniagent.py harness` | 端到端评测 Agent 是否完成任务、调用工具、生成正确文件 |
| Memory Retrieval Harness | `miniagent.py harness memory` | 评测长期记忆相似度召回和 rerank 后的 Recall@K / MRR |

## Metrics

Agent Task Harness 统计：

- success rate
- total tool calls
- average tool calls
- average steps / LLM loop iterations
- failure type distribution
- generated outbox files
- per-tool execution events
- file content assertions for `.xlsx` / `.docx` / `.pdf` / text files

Memory Retrieval Harness 统计：

- Recall@1
- Recall@3
- Recall@5
- Recall@task_k
- MRR
- hit rank for each query
- retrieved memory ids

## Files

```text
workspace/benchmarks/
├── tasks.json                    # Agent task harness cases
├── memory_retrieval_tasks.json   # Memory retrieval cases
├── fixtures/                     # Input files used by tasks
├── results/                      # JSON and Markdown reports
└── tmp/                          # Temporary isolated workspaces
```

## Design Notes

- Harness runs use isolated benchmark session keys such as `benchmark:<run_id>:<task_id>`.
- File operation tasks are judged by actual outbox files, not only by model claims.
- Content assertions open generated files and inspect their real contents.
- Memory retrieval tests construct a temporary `memory_store.jsonl` so they do not pollute real user memory.
- The harness treats tool argument JSON errors, missing tools, and missing skill scripts as blocking failures.

## Next Improvements

- Add more task cases until the suite reaches 20-40 examples.
- Add per-step trace export for model planning and tool recovery.
- Add route accuracy checks for skill selection.
- Add regression baseline comparison between two benchmark runs.
- Add deep fixtures for malformed files and expected failure recovery.

