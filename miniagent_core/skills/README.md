# MiniAgent Skill System

MiniAgent 的 skill 系统用于把“通用聊天 Agent”扩展成“可按需调用专业能力的任务 Agent”。它不是简单把所有工具和规则塞进 prompt，而是通过扫描、注册、路由、按需加载、统一脚本运行和 trace 记录，把 `workspace/skills/*` 下的能力包接入运行时。

当前系统的设计目标：

- **按需加载**：只有命中某个 skill 时才注入该 skill 的 `SKILL.md`。
- **脚本受控执行**：skill 下的脚本不注册成一堆独立工具，统一通过 `run_skill_script` 执行。
- **可观测**：路由命中、脚本开始、成功、失败、超时都写入 `workspace/skills/skill_trace.jsonl`。
- **可恢复**：脚本失败时，Agent loop 会阻止模型把“我接下来会处理”当成最终完成结果。
- **项目化治理**：提供 `SkillDoctor` 检查 skill 文件、脚本、依赖、外部命令是否可用。

## Directory Layout

核心实现位于：

```text
miniagent_core/skills/
├── scanner.py      # 扫描 workspace/skills 和可选 builtin skill
├── registry.py     # 注册 SkillRecord，按名称解析 skill
├── router.py       # Hybrid Router: rule + LLM semantic route
├── loader.py       # 对外 facade，保持原 SkillLoader 接口
├── runtime.py      # 受控执行 scripts/*.py，并写 skill trace
├── policy.py       # 构建运行时协议、交付门禁、fallback 提示
├── doctor.py       # health check / doctor
└── README.md       # 当前文档
```

用户可扩展能力位于：

```text
workspace/skills/
├── weather/
│   ├── SKILL.md
│   └── scripts/query_weather.py
├── xlsx/
│   ├── SKILL.md
│   ├── reference.md
│   └── scripts/
├── pdf/
│   ├── SKILL.md
│   ├── reference.md
│   └── scripts/
├── docx/
│   ├── SKILL.md
│   ├── reference.md
│   └── scripts/
└── skill_trace.jsonl
```

## Module Responsibilities

| 模块 | 文件 | 职责 |
| --- | --- | --- |
| `SkillScanner` | `scanner.py` | 扫描 skill 目录，读取 `SKILL.md` front matter，构建 `SkillRecord` |
| `SkillRegistry` | `registry.py` | 缓存所有 skill，支持 `list_skills()` 和 `get(name)` |
| `RuleSkillRouter` | `router.py` | 根据扩展名、MIME、关键词、附件信息做确定性路由 |
| `LLMSkillRouter` | `router.py` | 使用模型根据 compact skill metadata 做语义路由 |
| `SkillRouter` | `router.py` | Hybrid merge，融合 LLM route 与规则强信号 |
| `SkillLoader` | `loader.py` | 外部调用入口，负责路由、加载 `SKILL.md`、构建 prompt/runtime note |
| `SkillPolicyEngine` | `policy.py` | 生成运行时协议，例如 outbox 写入、脚本失败处理、xlsx 公式重算 |
| `SkillRuntime` | `runtime.py` | 校验脚本路径并执行 Python script，捕获 stdout/stderr/return code |
| `SkillTraceLogger` | `runtime.py` | 写入 `workspace/skills/skill_trace.jsonl` |
| `SkillDoctor` | `doctor.py` | 检查 skill 系统结构、脚本、依赖、命令是否处于可运行状态 |
| `run_skill_script` | `miniagent_core/tools/skills.py` | 暴露给模型的统一 skill 脚本执行工具 |

## End-to-End Runtime Flow

每轮用户消息进入 app 后，skill 系统大致按以下顺序工作：

```text
User message + visible attachments
        |
        v
SkillLoader.build_prompt_section()
        |
        v
SkillRouter.select_with_scores()
        |
        +--> Rule router: 扩展名 / MIME / 关键词 / 附件信号
        |
        +--> LLM router: 语义判断是否需要 skill
        |
        v
Hybrid merge selected skills
        |
        v
Load matched SKILL.md only
        |
        v
Inject # Skills + runtime note into prompt
        |
        v
Model decides whether to call tools
        |
        +--> run_skill_script(skill_name, script_path, arguments)
        |
        +--> read_file / read_uploaded_file / save_outbox_file / etc.
        |
        v
SkillRuntime validates path and executes script
        |
        v
Trace started/success/error/timeout
        |
        v
Agent loop verifies whether final response is complete
```

关键点：

- Route 命中 skill 只代表“该 skill 的说明被注入 prompt”。
- 只有模型实际调用 `run_skill_script` 时，才会出现 `skill_script started/success/error/timeout`。
- 如果模型用 `save_outbox_file` 生成 `.docx`，这属于附件产物工具，不属于 `docx` script trace。
- 多 skill 命中时，当前系统会把多个 `SKILL.md` 一起注入，执行顺序暂由模型根据任务自行规划。

## Skill Package Contract

一个 skill 目录至少需要：

```text
workspace/skills/<skill_name>/
└── SKILL.md
```

推荐结构：

```text
workspace/skills/<skill_name>/
├── SKILL.md
├── reference.md       # 可选，按需读取
├── references.md      # 可选，按需读取
├── forms.md           # 可选，按需读取
└── scripts/           # 可选，脚本只通过 run_skill_script 执行
```

`SKILL.md` front matter 推荐字段：

```markdown
---
name: xlsx
description: "Use this skill when spreadsheet files are the primary input or output."
triggers:
- .xlsx
- excel
- 工作表
---
```

字段含义：

| 字段 | 是否必须 | 用途 |
| --- | --- | --- |
| `name` | 推荐 | skill 唯一名称，`run_skill_script.skill_name` 使用该值 |
| `description` | 推荐 | 给 LLM Router 和 prompt 使用的能力描述 |
| `triggers` | 推荐 | 给 Rule Router 使用的触发词、扩展名、任务词 |

## Progressive Loading Policy

当前系统采用渐进式加载：

| 内容 | 是否自动注入 prompt | 说明 |
| --- | --- | --- |
| `SKILL.md` | 是，仅在 route 命中时 | 当前 skill 的主要工作说明 |
| `reference.md` / `references.md` / `forms.md` | 否 | 只列出路径，模型需要时用 `read_file` 读取 |
| `scripts/` | 否 | 只提示脚本目录存在，不把脚本内容塞进 prompt |
| 具体脚本源码 | 否 | 需要确认脚本参数或行为时再读取 |

这样做是为了避免 prompt 膨胀，同时保持 skill 的可扩展性。

## Route Policy

路由配置在 `miniagent_core/config.py` 中显式设置：

```python
SKILL_ROUTE_MODE = "hybrid"  # 可选: "hybrid" / "rule" / "llm"
```

三种模式：

| 模式 | 行为 | 适用场景 |
| --- | --- | --- |
| `rule` | 只用规则路由 | 调试、无 LLM 环境、追求确定性 |
| `llm` | 优先 LLM，失败后规则兜底 | 想观察语义路由能力 |
| `hybrid` | LLM + 规则强信号融合 | 默认推荐 |

### Rule Router Signals

规则路由使用以下信号：

- **扩展名信号**：`.xlsx` -> `xlsx`，`.pdf` -> `pdf`，`.docx` -> `docx`。
- **MIME 信号**：`application/pdf`、Office MIME、CSV MIME 等。
- **强关键词**：`天气`、`excel`、`word`、`pdf`、`公式` 等。
- **中弱关键词**：`表格`、`报告`、`页面`、`目录`、`行`、`列` 等。
- **路径/代码信号**：`.py`、`.json`、Windows/Linux 路径等会触发 `code_navigation`。
- **skill metadata triggers**：读取 `SKILL.md` front matter 中的 `triggers`。

默认规则阈值：

```python
RULE_THRESHOLD = 35
```

注意：Hybrid Router 不再简单依赖固定 top_k；它会合并 LLM 结果和规则强信号。

### LLM Router

LLM Router 不读取完整 `SKILL.md`，只接收 compact metadata：

```json
{
  "name": "xlsx",
  "description": "...",
  "triggers": ["excel", ".xlsx", "工作表"]
}
```

它必须返回严格 JSON：

```json
{
  "selected_skills": ["xlsx", "docx"],
  "confidence": 0.9,
  "reason": "The user wants to filter an Excel file and generate a Word report."
}
```

如果模型不可用、返回不是 JSON、JSON 解析失败或没有选择 skill，Hybrid Router 会回退到规则结果。

### Hybrid Merge

Hybrid 策略：

- LLM 选择的 skill 会进入候选。
- 规则路由发现强附件信号时，即使 LLM 漏选，也会补入。
- 同一 skill 同时被 LLM 和规则命中时，会合并 `score/confidence/reasons/source`。
- 结果写入 `skill_trace.jsonl`，便于确认为什么命中。

示例 trace：

```json
{
  "kind": "skill_activation",
  "status": "selected",
  "route_status": "hybrid",
  "skills": ["weather", "docx"],
  "route": [
    {
      "skill": "weather",
      "score": 95,
      "confidence": 0.95,
      "source": "llm+rule",
      "reasons": ["用户要求查询天气", "strong hint 天气"]
    }
  ]
}
```

## Multi-Skill Behavior

当前多 skill 行为是：

1. Router 可以返回多个 skill。
2. Loader 将多个 `SKILL.md` 都注入 prompt。
3. Runtime note 会列出每个命中 skill 的补充文档和脚本目录。
4. 模型自行决定调用顺序。
5. 只有被实际调用的脚本才会写 `skill_script` trace。

例如：

```text
用户：查询今天武汉天气，并生成 Word 天气简报保存
Route: weather + docx
Actual tools:
- run_skill_script(weather/scripts/query_weather.py)
- save_outbox_file(wuhan_weather.docx)
Trace:
- skill_activation: weather + docx
- skill_script started/success: weather
```

这里没有 `docx started/success` 是正常的，因为 `.docx` 是由 `save_outbox_file` 生成，不是通过 `run_skill_script(skill_name="docx")` 生成。

当前限制：

- 系统还没有强制性的 `SkillWorkflowPlanner`。
- 多 skill 的步骤顺序仍主要依赖模型规划。
- 如果希望 trace 中也记录 docx 生成，需要把 docx 生成沉淀成 `docx/scripts/create_docx.py`，或给 `save_outbox_file` 增加产物 trace。

## Script Execution Policy

skill 脚本统一通过 `run_skill_script` 执行。

工具参数格式和其他工具一致：

```json
{
  "skill_name": "xlsx",
  "script_path": "scripts/filter_workbook.py",
  "arguments": ["input.xlsx", "output.xlsx", "--sheet", "Sheet1"],
  "timeout_seconds": 60
}
```

不要把 `arguments` 数组当成整个工具参数。错误示例：

```json
["input.xlsx", "output.xlsx"]
```

`SkillRuntime` 会执行以下校验：

- `skill_name` 必须存在。
- `script_path` 必须是相对路径。
- 脚本必须位于该 skill 的 `scripts/` 目录下。
- 不允许路径逃逸到 skill 目录外。
- 只允许执行 `.py` 文件。
- `cwd` 必须位于项目或 workspace 内。
- 超时时间限制在 `1-300` 秒。

执行结果格式：

```text
Skill script: xlsx/scripts/filter_workbook.py
Return code: 0
STDOUT:
{...}
```

非零返回码会记录为 `status=error`，并被 Agent loop 视为工具失败信号。


### skill runtime 是一套“统一执行 skill 脚本的受控运行层
执行入口不是每个脚本单独注册工具，而是统一通过：`run_skill_script`
执行时 runtime 会做这些事：
        根据 skill_name 找到对应 skill。
        校验 script_path 必须在该 skill 的 scripts/ 目录下。
        禁止路径逃逸。
        只允许执行 .py 文件。
        使用当前 Python 解释器运行脚本。
        捕获 stdout、stderr、return code。
        记录 started / success / error / timeout trace。
        返回统一格式的工具结果给模型。


## Fallback Policy

Fallback Policy 分两层。

### Skill 内 fallback

每个 `SKILL.md` 可以写自己的 fallback 规则。例如：

- `xlsx`：公式相关结果交付前应执行 `scripts/recalc.py`。
- `weather`：天气查询必须优先使用 `scripts/query_weather.py`，不要直接拼 `curl` 或 PowerShell。
- `pdf`：如果 `extract_tables.py` 抽表失败，可以退回 `extract_text.py` 后让模型结构化整理。
- `docx`：简单生成可用 `save_outbox_file`，高保真编辑需使用 `office/unpack.py` / `pack.py` / `validate.py`。

这些规则只在 skill 命中后注入，不会每轮完整注入。

### Agent loop fallback

Agent loop 会处理工具失败和不完整回复：

- `run_skill_script` 返回 `Return code != 0` 时，模型不能声称成功。
- 如果脚本不存在，系统会提示不要重复调用不存在脚本。
- 如果有可用脚本，应改用已知脚本继续完成任务。
- 如果没有现成脚本，可以用基础文件工具生成临时脚本，再用 `exec` 执行。
- 如果模型在工具调用后只回复“正在处理 / 下一步将 / 稍后生成”，会被视为不完整进度更新并继续循环。

## Delivery Policy

交付规则：

- 不覆盖 `workspace/inbox` 中用户上传的原始文件。
- 修改、转换、生成结果都应写入当前会话 `workspace/outbox/`。
- 生成文件后，必要时用 `list_outbox_files` 或读取结果进行验证。
- 回复用户时必须基于真实工具结果，而不是计划或推测。
- 如果失败，应明确失败原因和下一步可行方案。

`.xlsx` 特别规则：

- 涉及公式、汇总、计算时，交付前应运行 `xlsx/scripts/recalc.py`。
- 如果重算返回 `#REF!`、`#DIV/0!`、`#VALUE!`、`#NAME?` 等错误，不能说文件完全可交付。

`.docx` 特别规则：

- `save_outbox_file(... .docx)` 可以生成简单 Word 文档。
- 这不会产生 `docx skill_script` trace。
- 如果需要完整 trace，应通过 `docx/scripts/*.py` 执行。

## Trace System

skill trace 文件：

```text
workspace/skills/skill_trace.jsonl
```

主要事件：

| kind | status | 含义 |
| --- | --- | --- |
| `skill_activation` | `selected` | 本轮 route 命中了哪些 skill |
| `skill_script` | `started` | 开始执行某个 skill 脚本 |
| `skill_script` | `success` | 脚本返回码为 0 |
| `skill_script` | `error` | 脚本异常或返回码非 0 |
| `skill_script` | `timeout` | 脚本执行超时 |

Trace 解读要点：

- 只有 `skill_activation` 说明 skill 被选中，不说明脚本被执行。
- 只有出现 `skill_script started/success` 才说明执行了该 skill 的脚本。
- `save_outbox_file`、`read_uploaded_file`、`exec` 等普通工具不会写入 skill trace。
- `route_status=hybrid_fallback_rule:...` 表示 LLM route 不可用或失败，使用规则兜底。

## Health Check

运行：

```powershell
python miniagent.py skills doctor
```

或：

```powershell
python -m miniagent_core.skills.doctor
```

输出摘要示例：

```text
Skill Doctor
Workspace: D:\...\workspace
Summary: OK=116 WARN=2 ERROR=0
```

Doctor 检查内容：

- `workspace/skills` 是否存在。
- `workspace/outbox` 是否可写。
- `workspace/skills/skill_trace.jsonl` 是否可写。
- 是否能发现 skill。
- skill name 是否重复。
- `SKILL.md` 是否存在、可读、非空。
- `description` / `triggers` 是否完整。
- `SKILL.md` 中引用的 `scripts/*.py` 是否真实存在。
- 核心 workflow 脚本是否存在。
- skill 下所有 Python 脚本是否有语法错误。
- 是否存在 `TODO`、`NotImplementedError`、`placeholder` 等占位标记。
- `openpyxl`、`pandas`、`pypdf`、`pdfplumber`、`reportlab`、`python-docx` 等包是否可导入。
- `soffice`、`pandoc` 等外部命令是否在 `PATH` 中。

退出码：

- `0`：无 `ERROR`，可能有 `WARN`。
- `1`：存在至少一个 `ERROR`。

`WARN` 不一定阻塞运行，通常表示某些可选能力不可用或脚本里有待确认的占位痕迹。

## Current Built-In Workspace Skills

### weather

用途：

- 查询实时天气和天气摘要。

核心脚本：

```text
workspace/skills/weather/scripts/query_weather.py
```

推荐调用：

```json
{
  "skill_name": "weather",
  "script_path": "scripts/query_weather.py",
  "arguments": ["Wuhan"],
  "timeout_seconds": 60
}
```

### xlsx

用途：

- 读取、检查、筛选、修改、汇总 Excel / CSV 类表格。
- 生成新的 `.xlsx` 结果文件。
- 对公式工作簿进行 LibreOffice 重算。

核心脚本：

```text
scripts/edit_workbook.py
scripts/filter_workbook.py
scripts/recalc.py
```

常见操作：

- `edit_workbook.py --operation inspect`
- `edit_workbook.py --operation read-range`
- `edit_workbook.py --operation append-row`
- `edit_workbook.py --operation add-sum-row`
- `filter_workbook.py input.xlsx output.xlsx --criteria-json ...`
- `recalc.py output.xlsx`

### pdf

用途：

- PDF 文本提取、表格提取、页面操作、生成简单 PDF 报告。

核心脚本：

```text
scripts/extract_text.py
scripts/extract_tables.py
scripts/pdf_ops.py
scripts/create_report.py
```

注意：

- `pdf2image` 暂不作为默认能力。
- `reference.md` 中的高频代码应逐步沉淀成真实脚本。

### docx

用途：

- Word 文档读取、生成、修订处理、批注、Office XML 级验证。

核心脚本：

```text
scripts/accept_changes.py
scripts/comment.py
scripts/office/unpack.py
scripts/office/pack.py
scripts/office/validate.py
scripts/office/soffice.py
```

注意：

- 当前项目优先 Python / LibreOffice，不默认使用 `docx-js` / `npm`。
- 简单 `.docx` 生成可由 `save_outbox_file` 完成，但不会产生 `docx skill_script` trace。

## Debugging Guide

### 只看到 skill selected，没有 script success

说明路由命中了 skill，但模型没有调用该 skill 的脚本。可能原因：

- 任务可以通过普通工具完成，例如 `save_outbox_file`。
- `SKILL.md` 没有明确要求必须调用脚本。
- 模型选择了另一个 skill 的脚本完成主要任务。

### `Skill script not found`

说明模型调用了不存在的脚本。处理方式：

- 检查 `SKILL.md` 是否错误引用脚本。
- 运行 `python miniagent.py skills doctor`。
- 如果脚本确实应该存在，把 reference 中的代码沉淀成 `scripts/*.py`。
- 如果只是临时需求，模型应使用基础文件工具生成临时脚本，而不是反复调用不存在脚本。

### `invalid tool arguments JSON`

说明模型生成的工具参数不是合法 JSON object，常见于把 `arguments` 数组拼坏。当前 app 有部分恢复逻辑，但应该通过 prompt 和 tool schema 继续约束：

```json
{
  "skill_name": "xlsx",
  "script_path": "scripts/recalc.py",
  "arguments": ["file.xlsx"]
}
```

### `Return code != 0`

说明脚本执行失败。Agent loop 会把它视为工具失败，模型需要：

- 读取 stderr/stdout。
- 修正参数或换用可用工具。
- 如果无法继续，明确失败收尾。

### 文件上传后找不到附件工具

这通常不是 skill 系统本身的问题，而是附件可见性问题。当前 `list_uploaded_files` 依赖本轮附件和 session 中仍保留的附件记录；如果 session 被 memory consolidation 裁剪，旧附件可能不再作为可见附件注册。未来应增加独立附件索引。

## Known Limitations

当前还没有完成的能力：

- **SkillWorkflowPlanner**：多 skill 任务还没有强制规划层，仍由模型自行安排步骤。
- **产物 trace**：`save_outbox_file` 生成的 `.docx/.pdf/.xlsx` 不写入 `skill_trace.jsonl`。
- **附件索引**：历史上传文件没有独立持久索引，主要依赖 session 附件记录和 inbox 搜索。
- **脚本能力注册表**：目前不维护单独 `capabilities.json`，避免重复 `SKILL.md` 并增加 prompt 长度。
- **深度 smoke test**：Doctor 当前以结构和依赖检查为主，未自动跑每个脚本的真实输入输出 fixture。

## Recommended Next Improvements

优先级建议：

1. **增加产物 trace**：让 `save_outbox_file` 也记录生成了什么文件、格式、路径。
2. **补 `docx/scripts/create_docx.py`**：让 Word 生成也可以通过 `run_skill_script` 留下完整 trace。
3. **实现附件索引**：把每次上传的文件写入独立 index，避免 session 裁剪后找不到旧附件。
4. **实现 SkillWorkflowPlanner**：对多 skill 任务生成结构化步骤，例如 `extract -> transform -> write -> verify -> respond`。
5. **增加 deep doctor fixtures**：为 `weather/xlsx/pdf/docx` 准备小测试文件，自动验证脚本可真实运行。

