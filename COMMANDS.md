# MiniAgent Commands

这个文件是项目命令速查表。日常优先使用 `harness` 命令；`benchmark` 是兼容旧入口，除非要验证旧路径，否则不用优先记。

> Windows 示例里如果当前 shell 已经激活 `assistant` 环境，可以把 `D:\conda\envs\assistant\python.exe` 简写成 `python`。

## 0. 环境检查

```powershell
D:\conda\envs\assistant\python.exe -m compileall miniagent.py miniagent_core
D:\conda\envs\assistant\python.exe miniagent.py skills doctor
D:\conda\envs\assistant\python.exe miniagent.py harness --help
```

用途：

- `compileall`：检查 Python 语法和模块加载。
- `skills doctor`：检查 skill 文件、脚本和外部依赖。
- `harness --help`：查看 harness 子命令。

## 1. 日常运行 Agent

CLI 本地调试：

```powershell
D:\conda\envs\assistant\python.exe miniagent.py --channels cli
```

QQBot：

```powershell
D:\conda\envs\assistant\python.exe miniagent.py --channels qq
```

CLI + QQ 同时开启：

```powershell
D:\conda\envs\assistant\python.exe miniagent.py --channels cli,qq
```

等价显式 Harness 写法：

```powershell
D:\conda\envs\assistant\python.exe miniagent.py harness run --channels cli
D:\conda\envs\assistant\python.exe miniagent.py harness run --channels qq
D:\conda\envs\assistant\python.exe miniagent.py harness run --channels cli,qq
```

## 2. Agent 任务评测

快速 smoke，不跑真实任务：

```powershell
D:\conda\envs\assistant\python.exe miniagent.py harness eval --limit 0
```

跑默认任务集：

```powershell
D:\conda\envs\assistant\python.exe miniagent.py harness eval
```

默认每个任务之间会等待 3 秒，减少连续请求触发 DashScope 429 的概率。

只跑前 3 条：

```powershell
D:\conda\envs\assistant\python.exe miniagent.py harness eval --limit 3
```

关闭任务间等待：

```powershell
D:\conda\envs\assistant\python.exe miniagent.py harness eval --delay 0
```

自定义等待 5 秒：

```powershell
D:\conda\envs\assistant\python.exe miniagent.py harness eval --delay 5
```

隔离运行，推荐用于开发测试：

```powershell
D:\conda\envs\assistant\python.exe miniagent.py harness eval --limit 3 --isolated
```

指定任务文件：

```powershell
D:\conda\envs\assistant\python.exe miniagent.py harness eval --tasks workspace/benchmarks/harness_flow_tasks.json --limit 3 --isolated
```

常用任务文件：

| 文件 | 用途 |
| --- | --- |
| `workspace/benchmarks/tasks.json` | 默认端到端 Agent 任务 |
| `workspace/benchmarks/harness_flow_tasks.json` | Harness 全流程分层测试 |
| `workspace/benchmarks/memory_retrieval_tasks.json` | Memory retrieval 专项任务 |

## 3. Memory Retrieval 评测

```powershell
D:\conda\envs\assistant\python.exe miniagent.py harness memory
```

输出指标包括 `Recall@1`、`Recall@3`、`Recall@5`、`Recall@task_k`、`MRR`。

## 4. Trace Replay

先从 isolated eval 找 trace：

```powershell
Get-ChildItem workspace/benchmarks/tmp -Recurse -Filter runtime_trace.jsonl |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 5 FullName
```

然后 replay：

```powershell
D:\conda\envs\assistant\python.exe miniagent.py harness replay --source <trace_path>
```

Replay 不重新请求 LLM，也不重新执行工具；它基于 trace 重建执行轨迹并检查缺失、乱序和工具名不匹配。

## 5. Regression Compare

对比两次 eval JSON 报告：

```powershell
D:\conda\envs\assistant\python.exe miniagent.py harness compare --base workspace/benchmarks/results/old.json --head workspace/benchmarks/results/new.json
```

常见用法：

```powershell
D:\conda\envs\assistant\python.exe miniagent.py harness eval --tasks workspace/benchmarks/harness_flow_tasks.json --limit 1 --isolated
D:\conda\envs\assistant\python.exe miniagent.py harness eval --tasks workspace/benchmarks/harness_flow_tasks.json --limit 3 --isolated
D:\conda\envs\assistant\python.exe miniagent.py harness compare --base workspace/benchmarks/results/<old_run_id>.json --head workspace/benchmarks/results/<new_run_id>.json
```

## 6. 兼容旧命令

这些命令仍可用，但新开发优先使用 `harness eval` / `harness memory`：

```powershell
D:\conda\envs\assistant\python.exe miniagent.py benchmark
D:\conda\envs\assistant\python.exe miniagent.py benchmark --limit 3 --isolated --delay 3
D:\conda\envs\assistant\python.exe miniagent.py benchmark memory
```

## 7. 输出位置

| 路径 | 内容 |
| --- | --- |
| `workspace/benchmarks/results/` | eval / replay / regression 报告 |
| `workspace/benchmarks/tmp/` | isolated eval 临时 workspace |
| `workspace/traces/` | live runtime trace |
| `workspace/inbox/` | 用户上传文件 |
| `workspace/outbox/` | Agent 生成文件 |
| `workspace/sessions/` | 会话记录 |
| `workspace/memory/` | 长期记忆 |

## 8. 清理临时产物

这些目录/文件是运行产物，删除后不会影响代码：

```text
workspace/benchmarks/results/
workspace/benchmarks/tmp/
workspace/traces/
workspace/inbox/
workspace/outbox/
workspace/sessions/
```

如果要保留最近结果，可以只保留：

```text
workspace/benchmarks/results/latest.md
workspace/benchmarks/results/memory_retrieval_latest.md
workspace/benchmarks/results/replay_latest.md
workspace/benchmarks/results/regression_latest.md
```
