# MiniAgent Benchmarks

`workspace/benchmarks/` 保存 Harness 评测任务、fixtures、临时 isolated workspace 和评测报告。

这里的 JSON 任务文件是“等待执行的测试用例”，不是已经执行过的记录。运行结果会写到 `results/`。

## Layout

```text
workspace/benchmarks/
├── README.md
├── HARNESS_FLOW_CASES.md
├── tasks.json
├── harness_flow_tasks.json
├── memory_retrieval_tasks.json
├── fixtures/
├── results/          # runtime generated, ignored by git
└── tmp/              # isolated eval workspace, ignored by git
```

## Task Files

| File | Meaning |
| --- | --- |
| `tasks.json` | 端到端 Agent 任务集，当前 20 个任务 |
| `harness_flow_tasks.json` | 逐步验证 Harness 流程的任务集 |
| `memory_retrieval_tasks.json` | Memory retrieval 评测任务，当前 20 条 query |
| `HARNESS_FLOW_CASES.md` | 手动/逐步测试说明 |
| `fixtures/` | 评测输入文件 |

## Commands

推荐通过 Harness 入口运行：

```powershell
python miniagent.py harness eval --tasks workspace/benchmarks/tasks.json --limit 3 --isolated
python miniagent.py harness eval --tasks workspace/benchmarks/harness_flow_tasks.json --limit 3 --isolated
python miniagent.py harness eval --tasks workspace/benchmarks/tasks.json --delay 5 --isolated
python miniagent.py harness memory
```

Replay 和 regression：

```powershell
python miniagent.py harness replay --source workspace/benchmarks/tmp/<run_id>/<task_id>/traces/runtime_trace.jsonl
python miniagent.py harness compare --base workspace/benchmarks/results/old.json --head workspace/benchmarks/results/new.json
```

兼容旧入口仍可用：

```powershell
python miniagent.py benchmark
python miniagent.py benchmark memory
```

## Isolated Eval

`--isolated` 会把运行状态写到：

```text
workspace/benchmarks/tmp/<run_id>/<task_id>/
```

它会复用真实项目的 skills 和 prompt 文件，但不会污染真实：

- `workspace/inbox/`
- `workspace/outbox/`
- `workspace/sessions/`
- `workspace/memory/`
- `workspace/traces/`

注意：这是 workspace 状态隔离，不是系统级 sandbox。

## Reports

报告输出到：

```text
workspace/benchmarks/results/
```

常见文件：

| File | Meaning |
| --- | --- |
| `latest.md` | 最近一次 agent eval Markdown |
| `<run_id>.json` | agent eval JSON |
| `memory_retrieval_latest.md` | 最近一次 memory retrieval Markdown |
| `memory_retrieval_<run_id>.json` | memory retrieval JSON |
| `replay_latest.md` | 最近一次 replay Markdown |
| `replay_<run_id>.json` | replay JSON |
| `regression_latest.md` | 最近一次 regression Markdown |
| `regression_<run_id>.json` | regression JSON |

`results/` 可以删除，不影响任务定义。删除后只是丢失历史评测报告。

## Agent Task Assertions

任务可以配置：

- `expected_reply_contains`
- `expected_reply_contains_any`
- `expected_tools_all`
- `expected_tools_any`
- `expected_outbox_suffixes`
- `expected_outbox_files`
- `expected_max_tool_calls`

文件内容断言支持：

- `.xlsx`：sheet、行数、包含/不包含文本。
- `.docx`：文本包含/不包含。
- `.pdf`：文本包含/不包含。
- `.txt/.md/.json/.csv`：文本包含/不包含。

`expected_reply_contains` 表示所有列出的文本都必须出现在回复中；`expected_reply_contains_any` 表示同义表达任选其一即可，例如 `trace / 追溯 / 可追踪 / 回放`。

Agent eval 默认任务间 `--delay 3`，用于降低连续请求模型时遇到 429/限流的概率。调试本地逻辑时可用 `--delay 0`。

## Memory Retrieval Metrics

Memory retrieval eval 会构建临时 memory workspace，不污染真实 memory。

指标：

- `Recall@1`
- `Recall@3`
- `Recall@5`
- `Recall@task_k`
- `MRR`
- 每条 query 的命中 rank

## Harness Flow Cases

`harness_flow_tasks.json` 用于逐步验证完整 runtime：

- 普通回复。
- 文件读取。
- skill route。
- `actions.json` 自动执行。
- `run_skill_script` 工具执行。
- 输出文件验证。
- trace 记录。
- replay / regression 可用性。

## Debug Tips

评测失败时优先看：

```text
workspace/benchmarks/tmp/<run_id>/<task_id>/traces/runtime_trace.jsonl
```

重点事件：

```text
skill_activation
skill_action_plan
llm_request
llm_response
tool_call
tool_result
output_artifact
grounding_violation
output_violation
script_tool_violation
judge_result
turn_completed
```

如果 `llm_response.tool_calls=[]`，但任务需要文件或脚本，说明 runtime gate 是否触发是排查重点。
