# MiniAgent

MiniAgent 是一个本地运行的任务型 Agent 项目，面向 QQBot / CLI 场景，支持文件处理、工具调用、项目级 skill、长期记忆、runtime trace、评测、回放和回归比较。

当前版本的重点不是“让模型自由聊天”，而是把 Agent 放进一个可观测、可约束、可复现的工程运行层里：

- CLI / QQBot 双通道运行。
- 上传文件落到 `workspace/inbox/`，生成文件落到 `workspace/outbox/`。
- `docx / pdf / xlsx / weather / code_navigation` 项目级 skill。
- 统一通过 `run_skill_script` 执行 skill 脚本。
- `actions.json` 支持可自动执行的确定性 action，例如 Excel 转 PDF、PDF 合并/抽页/旋转、接受 Word 修订。
- `TurnIntent` 集中判断本轮是否需要文件证据、输出产物或脚本执行，避免散落 prompt hint。
- `RuntimeVerifier` / `RuntimeRecovery` 独立负责校验与恢复，不把假行为拦截全塞在 agent loop 里。
- runtime 会记录 `llm_request`、`llm_response`、`tool_call`、`tool_result`、`memory_retrieval`、`skill_activation`、`output_artifact`、`file_created`、`turn_completed` 等 trace。
- 对文件读取、输出文件、脚本执行有 runtime gate，防止模型假装读文件、假装保存文件、假装执行脚本。
- Harness 支持 live runtime、isolated eval、deterministic replay 和 regression compare。

架构图见 [ARCHITECTURE.md](ARCHITECTURE.md)。

## Project Layout

```text
AI_assistant/
├── miniagent.py                  # 项目入口
├── COMMANDS.md                   # 命令速查
├── ARCHITECTURE.md               # 架构图与 runtime 流程
├── miniagent_core/
│   ├── app.py                    # Agent loop、runtime gate、channel 处理
│   ├── attachments.py            # inbox/outbox 与文件读写
│   ├── benchmark.py              # benchmark suites 与 report
│   ├── intent.py                 # TurnIntent 推断
│   ├── memory.py                 # session、长期记忆、检索、consolidation
│   ├── runtime_guards.py         # 文本/行为 guard 规则
│   ├── runtime_verifier.py       # 最终回复事实校验
│   ├── runtime_recovery.py       # 按错误类型重试/失败恢复
│   ├── tools/                    # 基础工具与 run_skill_script
│   ├── skills/                   # skill 扫描、路由、action planner、runtime
│   └── harness/                  # 工程级 runtime/eval/trace/replay/regression
└── workspace/
    ├── AGENTS.md                 # Agent 行为说明
    ├── SOUL.md                   # Agent 风格
    ├── USER.md                   # 用户偏好
    ├── skills/                   # 项目级 skill 包
    ├── memory/                   # memory store 与说明
    ├── benchmarks/               # eval tasks、fixtures、results
    ├── inbox/                    # 用户上传文件，运行时生成
    ├── outbox/                   # Agent 输出文件，运行时生成
    ├── sessions/                 # 会话 jsonl，运行时生成
    └── traces/                   # runtime_trace.jsonl，运行时生成
```

## Install

推荐 Python 3.11。

```powershell
conda create -n assistant python=3.11 -y
conda activate assistant
python -m pip install -U pip
python -m pip install -r requirements.txt
```

可选依赖：

- LibreOffice：Excel 公式重算、Office 转 PDF。
- Pandoc：部分文档转换。
- Playwright：浏览器自动化。

```powershell
python -m playwright install chromium
soffice --version
```

## Configuration

模型使用 DashScope OpenAI-compatible API：

```powershell
$env:DASHSCOPE_API_KEY="your-key"
$env:DASHSCOPE_EMBEDDING_MODEL="text-embedding-v4"
```

QQBot：

```powershell
$env:QQ_BOT_ENABLED="true"
$env:QQ_BOT_APP_ID="your-app-id"
$env:QQ_BOT_SECRET="your-secret"
$env:QQ_BOT_ACK_MESSAGE="Processing..."
```

## Run

```powershell
python miniagent.py --channels cli
python miniagent.py --channels qq
python miniagent.py --channels cli,qq
```

普通入口和 `harness run` 都会走同一套工程 runtime：

```powershell
python miniagent.py harness run --channels cli
python miniagent.py harness run --channels qq
```

更多命令见 [COMMANDS.md](COMMANDS.md)。

## Harness

Harness 是项目级运行控制层。它负责统一装配 app、tools、skills、memory、sessions、attachments、trace。

常用命令：

```powershell
python miniagent.py harness --help
python miniagent.py harness eval --limit 3 --isolated
python miniagent.py harness memory
python miniagent.py harness replay --source workspace/traces/runtime_trace.jsonl
python miniagent.py harness compare --base old.json --head new.json
```

详细说明见 [miniagent_core/harness/README.md](miniagent_core/harness/README.md)。

## Runtime Gates

当前 Agent loop 不再完全相信模型自然语言承诺。它先用 `TurnIntent` 判断本轮目标，再由 `RuntimeVerifier` 根据真实工具结果校验，失败后交给 `RuntimeRecovery` 按错误类型重试或返回明确错误。

- **File grounding gate**：本轮请求涉及附件内容时，必须有 `read_uploaded_file`、`read_file`、`run_skill_script` 或 runtime preload 证据。
- **Output file gate**：用户要求保存/导出/修改文件时，必须有真实产物工具成功，例如 `save_outbox_file` 或返回 `Return code: 0` 的 `run_skill_script`。
- **Script gate**：命中脚本型 skill 且任务需要脚本时，runtime 会设置 `tool_choice=run_skill_script`；如果模型仍返回 `tool_calls=[]`，会记录 `script_tool_violation` 并重试。
- **Claim gate**：如果模型声称“已保存路径”但本轮没有文件产物，会记录 `output_violation` 并阻止最终回复。
- **Completion gate**：如果工具调用后仍只回复“正在处理/下一步将”，会触发恢复，不把中间态当最终结果发给用户。

这些 gate 的目标是减少“假装读文件 / 假装保存 / 假装执行脚本”。

## Skills

项目级 skill 位于 `workspace/skills/<name>/`。

当前内置 workspace skills：

| Skill | 主要能力 |
| --- | --- |
| `weather` | 天气查询，脚本 `scripts/query_weather.py` |
| `xlsx` | Excel 读取、筛选、修改、公式重算、导出 PDF |
| `pdf` | PDF 提取、合并、抽页、旋转、生成报告 |
| `docx` | Word 读取、生成、修订处理、Office XML 校验 |
| `code_navigation` | 代码/路径/项目文件定位 |

`actions.json` 是 runtime action contract，用于声明可自动执行的任务模板。当前已覆盖：

- `xlsx/export_pdf`
- `pdf/merge_pdfs`
- `pdf/extract_pages`
- `pdf/rotate_pages`
- `docx/accept_tracked_changes`

详细说明见 [miniagent_core/skills/README.md](miniagent_core/skills/README.md)。

## Memory

Memory 分三层：

- `workspace/sessions/*.jsonl`：短期会话原始记录。
- `workspace/memory/history.jsonl`：consolidation 历史摘要。
- `workspace/memory/memory_store.jsonl`：长期记忆唯一检索主库。

`MEMORY.md` 是由 `memory_store.jsonl` 渲染的人类可读视图，不是权威事实源。

详细说明见 [workspace/memory/README.md](workspace/memory/README.md)。

## Trace

Live trace 默认写入：

```text
workspace/traces/runtime_trace.jsonl
```

Skill script trace 写入：

```text
workspace/skills/skill_trace.jsonl
```

如果任务出错，优先看 `runtime_trace.jsonl` 中最近一轮的：

```text
turn_intent -> skill_activation -> llm_request -> llm_response -> tool_call/tool_result -> recovery_plan/violation -> turn_completed
```

## Benchmarks

任务集位于 `workspace/benchmarks/`：

- `tasks.json`：端到端 Agent 任务。
- `harness_flow_tasks.json`：逐步验证 harness 流程。
- `memory_retrieval_tasks.json`：memory retrieval 评测。

Agent eval 默认每个任务间隔 3 秒，降低 DashScope 连续请求触发 429 的概率；可用 `--delay 0` 关闭。

详细说明见 [workspace/benchmarks/README.md](workspace/benchmarks/README.md)。
