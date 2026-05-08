# MiniAgent：面向 QQBot 的文件处理与记忆增强 Agent

MiniAgent 是一个本地运行的 Agent 工程项目，目标是把“聊天机器人”升级为“能接收文件、调用工具、使用 skill、维护长期记忆、并可被 benchmark 评测的任务型 Agent”。

项目当前支持：

- CLI / QQBot 双通道运行。
- QQ 文件接收、落盘到 `workspace/inbox/`，处理结果保存到 `workspace/outbox/`。
- 解析和生成 `txt / docx / pdf / xlsx` 等文件。
- 基于 skill 的按需能力加载，包括 `docx / pdf / xlsx / weather / code_navigation`。
- 统一 `run_skill_script` 运行 skill 下脚本，并记录 `skill_trace.jsonl`。
- 结构化长期记忆：`memory_store.jsonl` + embedding 相似度召回 + 规则 rerank。
- Harness / Benchmark：统计成功率、工具调用次数、平均步数、失败类型，并支持文件内容精准验收和 Memory Retrieval Recall@K / MRR。

> 当前项目更适合作为 Agent 工程设计与实验项目，而不是生产级多用户平台。QQ 多用户长期记忆隔离、附件索引、完整 workflow planner 等仍在后续迭代中。

## 项目结构

```text
AI_assistant/
├── miniagent.py                  # 项目入口，支持 cli / qq / skills doctor / harness
├── miniagent_core/               # 核心代码
│   ├── app.py                    # Agent 主循环、工具调用、channel 装配、消息处理
│   ├── async_compat.py           # 异步兼容工具，封装阻塞函数到线程执行
│   ├── attachments.py            # inbox/outbox 文件管理，Office/PDF 读写
│   ├── benchmark.py              # Benchmark / Harness 评测实现
│   ├── channels.py               # CLIChannel / QQChannel
│   ├── config.py                 # 模型、路径、记忆阈值、QQ channel 配置
│   ├── memory.py                 # Session、长期记忆、consolidation、检索与 rerank
│   ├── message.py                # InboundMessage / OutboundMessage / MessageBus
│   ├── tools/                    # 基础工具系统
│   │   ├── base.py               # Tool 抽象基类
│   │   ├── registry.py           # ToolRegistry
│   │   ├── files.py              # exec/read/write/find/search code
│   │   ├── attachments.py        # list/read uploaded, save/list outbox
│   │   ├── web.py                # web_search / web_fetch
│   │   ├── browser.py            # Playwright 浏览器自动化工具
│   │   └── skills.py             # run_skill_script 工具入口
│   ├── skills/                   # Skill runtime 框架
│   │   ├── scanner.py            # 扫描 workspace/skills
│   │   ├── registry.py           # 注册 SkillRecord
│   │   ├── router.py             # Hybrid Router：规则 + LLM 语义路由
│   │   ├── loader.py             # 按需加载 SKILL.md
│   │   ├── runtime.py            # 受控执行 skill scripts/*.py
│   │   ├── policy.py             # Skill runtime 协议与 fallback policy
│   │   ├── doctor.py             # skill health check
│   │   └── README.md             # Skill 系统详细说明
│   └── harness/                  # Harness 工程入口与说明
│       ├── __init__.py
│       └── README.md
├── workspace/                    # Agent 工作区
│   ├── AGENTS.md                 # Agent 行为说明，可被系统 prompt 读取
│   ├── SOUL.md                   # Agent 角色/风格设定
│   ├── USER.md                   # 用户偏好说明
│   ├── skills/                   # 项目级 skill 包
│   │   ├── code_navigation/
│   │   ├── docx/
│   │   ├── pdf/
│   │   ├── weather/
│   │   └── xlsx/
│   ├── memory/
│   │   └── README.md             # Memory 系统详细说明
│   └── benchmarks/
│       ├── README.md             # Harness / benchmark 说明
│       ├── tasks.json            # Agent 端到端任务集
│       ├── memory_retrieval_tasks.json
│       └── fixtures/             # benchmark 输入样例文件
├── PROJECT_QA.md                 # 项目开发过程问题复盘 QA
├── smoke_test.py                 # 本地 smoke test
├── requirements.txt              # Python 依赖
├── .env.example                  # 环境变量示例
├── .python-version               # 推荐 Python 版本
└── .gitignore
```

## Runtime 目录说明

以下目录是运行时数据，默认不建议提交到 GitHub：

```text
workspace/inbox/                 # 用户上传文件
workspace/outbox/                # Agent 生成结果文件
workspace/sessions/              # 每个 channel/session 的短期会话 jsonl
workspace/memory/*.jsonl         # 结构化长期记忆、历史摘要、trace
workspace/memory/MEMORY.md       # 长期记忆人类可读视图
workspace/memory/HISTORY.md      # 历史摘要人类可读视图
workspace/skills/skill_trace.jsonl
workspace/benchmarks/results/
workspace/benchmarks/tmp/
```

这些路径已写入 `.gitignore`。

## 环境要求

推荐环境：

- Python `3.11.x`，当前开发环境为 `3.11.15`。
- Windows + PowerShell。
- 可选：LibreOffice，用于 Excel 公式重算和 Office 转换。
- 可选：Pandoc，用于部分 docx 高级转换流程。
- 可选：Playwright 浏览器，用于浏览器自动化工具。

## 安装步骤

### 1. 克隆项目

```powershell
git clone <your-repo-url>
cd AI_assistant
```

### 2. 创建 Python 3.11 环境

示例使用 conda：

```powershell
conda create -n assistant python=3.11 -y
conda activate assistant
```

或使用你自己的 Python 3.11 虚拟环境。

### 3. 安装依赖

```powershell
python -m pip install -U pip
python -m pip install -r requirements.txt
```

如果需要浏览器自动化：

```powershell
python -m playwright install chromium
```

如果需要 LibreOffice 相关能力，请安装 LibreOffice，并确保 `soffice` 在 `PATH` 中：

```powershell
soffice --version
```

## 配置环境变量

项目使用 DashScope 的 OpenAI-compatible API：

```powershell
$env:DASHSCOPE_API_KEY="你的 DashScope API Key"
$env:DASHSCOPE_EMBEDDING_MODEL="text-embedding-v4"
```

QQBot 通道需要配置：

```powershell
$env:QQ_BOT_ENABLED="true"
$env:QQ_BOT_APP_ID="你的 QQBot AppID"
$env:QQ_BOT_SECRET="你的 QQBot Secret"
$env:QQ_BOT_ACK_MESSAGE="⏳ Processing..."
```

也可以参考 `.env.example` 自行管理环境变量。当前代码默认直接读取系统环境变量，不会自动加载 `.env` 文件。

## 运行项目

### CLI 模式

```powershell
python miniagent.py --channels cli
```

CLI 模式适合本地调试 Agent loop、工具调用、memory 和 skill 行为。

### QQBot 模式

```powershell
python miniagent.py --channels qq
```

QQBot 模式会通过 `botpy` 连接 QQ 开放平台 WebSocket。收到 QQ 私聊消息后，消息会进入 MiniAgent 的 MessageBus，再交给 Agent loop 处理。

### 同时开启 CLI 和 QQ

```powershell
python miniagent.py --channels cli,qq
```

## 常用维护命令

### Skill Health Check

```powershell
python miniagent.py skills doctor
```

检查内容包括：

- `workspace/skills` 是否存在。
- `SKILL.md` 是否可读。
- skill 中引用的脚本是否存在。
- Python 脚本是否有语法错误。
- `openpyxl / pypdf / pdfplumber / python-docx / reportlab` 等依赖是否可导入。
- `soffice / pandoc` 等外部命令是否在 `PATH` 中。

### Agent Harness

```powershell
python miniagent.py harness
```

统计：

- 成功率
- 工具调用次数
- 平均 Agent loop 步数
- 失败类型
- outbox 产物
- 文件内容精准验收

### Memory Retrieval Harness

```powershell
python miniagent.py harness memory
```

统计：

- Recall@1
- Recall@3
- Recall@5
- Recall@task_k
- MRR
- 每条 query 的命中 rank

## 核心设计说明

### 1. Tool System

基础工具位于 `miniagent_core/tools/`。

当前工具包括：

- `exec`
- `read_file`
- `write_file`
- `find_files`
- `search_code`
- `web_search`
- `web_fetch`
- `browser_automation`
- `list_uploaded_files`
- `read_uploaded_file`
- `save_outbox_file`
- `list_outbox_files`
- `run_skill_script`

所有工具通过 `ToolRegistry` 注册，并暴露给模型函数调用。

### 2. Skill Runtime

Skill 目录位于 `workspace/skills/<skill_name>/`。

每个 skill 至少包含：

```text
SKILL.md
```

可选包含：

```text
reference.md
forms.md
scripts/
```

运行机制：

1. `SkillScanner` 扫描 skill。
2. `SkillRegistry` 注册 skill 元数据。
3. `SkillRouter` 根据用户消息和附件路由 skill。
4. `SkillLoader` 只按需注入命中的 `SKILL.md`。
5. 模型如需执行脚本，统一调用 `run_skill_script`。
6. `SkillRuntime` 校验路径、执行脚本、记录 trace。

### 3. Memory System

Memory 分为三层：

- `workspace/sessions/*.jsonl`：短期会话原始记录。
- `workspace/memory/history.jsonl`：每次 consolidation 的历史摘要日志。
- `workspace/memory/memory_store.jsonl`：长期记忆主库和检索唯一事实源。

检索流程：

1. 当前 query 生成 embedding。
2. 从 `memory_store.jsonl` 读取 active memory items。
3. 使用预存 embedding 做相似度召回。
4. 结合关键词、topic、confidence 做 rerank。
5. 注入 `# Relevant Memory` 到 prompt。

### 4. Attachment / Outbox

用户上传文件保存到：

```text
workspace/inbox/<channel>/<sender>/<filename__hash>/
```

Agent 生成结果保存到：

```text
workspace/outbox/<session_key>/<filename__hash>/
```

文件处理原则：

- 不覆盖用户上传的 inbox 原始文件。
- 结果统一写入 outbox。
- 文件处理结果尽量通过真实二进制格式输出，例如 `.docx/.pdf/.xlsx`。

## 当前支持的 Skill

| Skill | 说明 |
| --- | --- |
| `code_navigation` | 代码定位、文件查找、源码阅读辅助 |
| `weather` | 天气查询，核心脚本 `scripts/query_weather.py` |
| `xlsx` | Excel 读取、筛选、修改、公式重算 |
| `pdf` | PDF 文本提取、表格提取、PDF 报告生成 |
| `docx` | Word 文档读取、生成、修订处理、Office XML 校验 |





