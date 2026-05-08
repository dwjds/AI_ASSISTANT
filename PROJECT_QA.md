# MiniAgent 项目问题复盘 QA

这份文档记录 MiniAgent 从“聊天 QQBot”逐步演进为“支持文件处理、记忆检索、skill runtime 的 Agent 项目”过程中遇到的典型问题，以及对应解决方法。它既可以作为后续维护手册，也可以作为项目复盘和简历描述的素材。

## 1. QQ Channel 与会话管理

### Q1：QQBot 一开始只能聊天，如何支持用户发送文件？

**问题现象**

QQBot 可以接收文本消息，但用户上传文件后，Agent 无法知道文件路径，也无法根据用户后续要求处理文件。

**原因**

早期 channel 只把文本消息传入 app loop，没有把 QQ 附件下载、落盘、登记成可见工具资源。

**解决方法**

- 增加附件接收与保存逻辑。
- 将用户上传文件保存到 `workspace/inbox/qq/<openid>/<filename__hash>/`。
- 为每个上传文件生成 `manifest.json`，记录文件名、路径、来源 URL、content type、sha256、大小等元数据。
- 在当前会话中注册附件工具：
  - `list_uploaded_files`
  - `read_uploaded_file`
- 处理结果保存到 `workspace/outbox/<session>/`。

**后续建议**

建立独立附件索引，例如 `workspace/attachments/index.jsonl`，避免 session 被裁剪后找不到旧附件。

### Q2：为什么重启 `python miniagent.py` 后，之前上传过的文件有时还能找到，有时找不到？

**问题现象**

重启后，用户说“处理刚才上传的文件”，Agent 有时能找到，有时找不到。

**原因**

当前附件可见性主要来自：

- 当前回合上传的附件。
- session jsonl 中仍保留的 attachment 记录。
- 模型兜底通过 `find_files` 搜索 `workspace/inbox`。

当 memory consolidation 裁剪 session 后，旧 attachment 记录可能被裁掉，工具注册时就拿不到 `list_uploaded_files`。

**解决方法**

- 当前临时兜底：允许模型通过 `find_files` 在 `workspace/inbox` 中搜索历史文件。
- 明确区分 memory 和附件索引：memory 只记语义事实，不能恢复附件对象。

**后续建议**

实现持久附件索引：

```text
workspace/attachments/index.jsonl
```

每次上传文件都登记：

- session_key
- channel
- sender_id
- filename
- path
- content_type
- sha256
- timestamp

每轮工具注册时从该索引加载当前 session 最近文件。

### Q3：为什么不同 QQ 用户是否会混用 session？

**问题现象**

担心多个 QQ 用户共用同一个 session 或记忆。

**原因**

QQ 私聊 session key 当前形如：

```text
qq:private:<openid>
```

因此不同 openid 会对应不同 session 文件：

```text
workspace/sessions/qq__private__<openid>.jsonl
```

**解决方法**

短期 session 已按 channel/user 隔离。

**仍存在的问题**

长期 memory 当前还是全局共享：

```text
workspace/memory/memory_store.jsonl
```

如果未来给多个真实用户使用，需要实现 user-scoped memory。

## 2. 附件与文件处理

### Q4：为什么上传文件后，Agent 自动生成摘要并保存了？

**问题现象**

用户只是上传了一个文件，还没提出要求，Agent 却自动读取文件、生成摘要并保存到 outbox。

**原因**

早期 app loop 把“只有附件、没有文本要求”的消息也交给模型处理。模型看到文件后倾向于主动总结。

**解决方法**

增加 attachment-only short-circuit：

- 如果当前消息有附件但文本为空，只保存附件记录。
- 直接回复：

```text
已收到您上传的文件：xxx
```

- 不调用 LLM。
- 不调用工具。
- 不生成 outbox 产物。

### Q5：为什么用户上传 PDF 后，文件名变成了 `pdf.pdf`？

**问题现象**

QQ 上传的 PDF 明明有原文件名，但 inbox 中只保存成 `pdf.pdf`。

**原因**

QQ 文件下载 URL 或 SDK 附件元数据没有稳定提供原始文件名，早期逻辑根据 content type 或 URL 兜底生成了过于泛化的名字。

**解决方法**

- 优先使用 QQ 附件对象中的原始文件名。
- 如果没有扩展名，根据 content type 推断扩展名。
- inbox/outbox 子目录改成基于文件名命名：

```text
电子商务课程论文__9a0894f3/
Agent_Rec_范式分类表__e18e7c53/
```

而不是一串不可读的 message id。

### Q6：为什么不能直接用 `read_file` 读取 `.xlsx`？

**问题现象**

模型尝试：

```text
read_file("xxx.xlsx")
```

然后报：

```text
'utf-8' codec can't decode byte ...
```

**原因**

`.xlsx`、`.docx`、`.pdf` 都是二进制或压缩格式，不是纯文本文件。`read_file` 适合读取 `.py/.md/.txt/.json` 等文本文件。

**解决方法**

- `.xlsx` 使用 `openpyxl` 或 `xlsx` skill 脚本。
- `.docx` 使用 `python-docx` 或 `read_uploaded_file` 的解析逻辑。
- `.pdf` 使用 `pypdf/pdfplumber` 或 `pdf` skill 脚本。

**后续建议**

在 `read_file` 中对二进制扩展名返回更明确的错误提示：

```text
这是二进制 Office/PDF 文件，请使用 read_uploaded_file 或对应 skill。
```

## 3. Office 文件解析与生成

### Q7：一开始只能处理 `.txt` 吗？

**问题现象**

用户问是否只能分析 txt，是否能分析 Word、PDF、Excel。

**原因**

早期附件解析只对文本文件天然友好，Office/PDF 需要专门解析库。

**解决方法**

增加依赖和解析逻辑：

- PDF：`pypdf`，后续增加 `pdfplumber`。
- XLSX：`openpyxl`。
- DOCX：`python-docx`。
- CSV/TSV：文本表格解析。

生成逻辑：

- DOCX：`python-docx` 写标题、段落、表格。
- PDF：`reportlab` 生成真正 PDF。
- XLSX：`openpyxl` 写单元格、工作表、公式。

### Q8：处理结果只能保存成 Markdown 吗？

**问题现象**

用户希望输出 Word、PDF、Excel，而不是只输出 `.md`。

**原因**

早期 `save_outbox_file` 偏向保存文本内容，缺少按扩展名生成二进制 Office/PDF 的分支。

**解决方法**

扩展 `save_outbox_file`：

- `.md/.txt`：直接写文本。
- `.docx`：用 `python-docx` 生成真实 Word。
- `.pdf`：用 `reportlab` 生成真实 PDF。
- `.xlsx`：用 `openpyxl` 生成真实 Excel。

### Q9：为什么 `.docx` 已经生成了，但 `skill_trace.jsonl` 没有 docx script 的 success？

**问题现象**

任务命中了 `weather + docx`，trace 里只有：

```text
weather/scripts/query_weather.py started/success
```

没有 docx script。

**原因**

`.docx` 是通过普通工具 `save_outbox_file` 生成的，不是通过：

```text
run_skill_script(skill_name="docx", ...)
```

因此不会记录 `skill_script` trace。

**解决方法**

当前行为是正常的：

- `skill_activation` 表示 docx 被路由命中。
- 没有 `docx skill_script` 只表示没有调用 docx 脚本。

**后续建议**

- 给 `save_outbox_file` 增加产物 trace。
- 或补充 `docx/scripts/create_docx.py`，让 Word 生成也走 skill runtime。

## 4. XLSX 处理流程

### Q10：为什么 LibreOffice `soffice` 找不到或不可用？

**问题现象**

运行 xlsx 公式重算脚本时，LibreOffice 相关命令失败。

**原因**

`soffice` 没有加入系统 `Path`，或 PowerShell 当前环境没有重新加载环境变量。

**解决方法**

- 安装 LibreOffice。
- 将 LibreOffice 程序目录加入系统 `Path`，例如：

```text
C:\Program Files\LibreOffice\program
```

- 重新打开终端。
- 用命令测试：

```powershell
soffice --version
```

### Q11：为什么测试 xlsx 文件里看起来没有公式？

**问题现象**

打开测试文件时，单元格显示的是计算结果，而不是公式。

**原因**

Excel/WPS 默认显示公式计算结果，除非点进单元格或开启显示公式。

另一个可能原因是测试文件确实写了值，没有写公式。

**解决方法**

用 `openpyxl` 明确写入公式：

```python
ws["D2"] = "=B2-C2"
ws["E2"] = "=D2/B2"
```

然后用 LibreOffice 打开或重算。

### Q12：为什么模型会调用不存在的 `scripts/recalc.py` 或错误路径？

**问题现象**

模型调用：

```text
python scripts/recalc.py
```

结果报：

```text
No such file or directory
```

**原因**

模型把 skill 内部路径当成项目根目录路径执行，没有通过统一 skill runtime。

**解决方法**

引入统一工具：

```text
run_skill_script
```

调用方式：

```json
{
  "skill_name": "xlsx",
  "script_path": "scripts/recalc.py",
  "arguments": ["<file.xlsx>"],
  "timeout_seconds": 60
}
```

`SkillRuntime` 负责解析到：

```text
workspace/skills/xlsx/scripts/recalc.py
```

### Q13：为什么模型想筛选 Excel 时调用了不存在的 `filter_ai_sw_eng.py`？

**问题现象**

用户要求筛选 Excel：

```text
提取专业软件工程，研究内容包含 AI 的课题
```

模型调用：

```text
scripts/filter_ai_sw_eng.py
```

但该脚本不存在。

**原因**

模型根据任务语义“幻想”了一个具体脚本名，而不是先查看 skill 已有脚本。

**解决方法**

新增通用脚本：

```text
workspace/skills/xlsx/scripts/filter_workbook.py
```

它支持通过 criteria JSON 做通用筛选：

```json
{
  "include": [
    {"columns": ["专业", "需求专业"], "keywords": ["软件工程"]},
    {"columns": ["项目名称", "具体项目需求工作描述", "现有研究基础与应用前景"], "keywords": ["AI", "人工智能", "大模型", "LLM"]}
  ],
  "exclude": []
}
```

同时强化 Agent loop：

- 脚本不存在时，不允许模型重复调用不存在脚本。
- 不允许回复“我接下来会处理”作为最终结果。
- 应改用已有脚本，或生成临时脚本完成任务。

### Q14：为什么 Excel 修改任务只处理一步就回复“正在生成”？

**问题现象**

模型先读取了 Excel 前几行，然后回复：

```text
下一步将生成筛选脚本并执行……
```

但本轮没有真正生成结果文件。

**原因**

模型把中间进度当成最终回复，Agent loop 没有拦截这种不完整状态。

**解决方法**

增加 incomplete progress guard：

- 如果工具调用后，最终回复只包含：
  - 正在处理
  - 下一步将
  - 稍后生成
  - 正在生成
- 且任务明显要求产物或实际操作，则继续循环，不把它发给用户。

同时对 `run_skill_script Return code != 0` 视为失败，要求模型恢复或明确失败。

## 5. Skill 系统

### Q15：为什么不把 skill 下每个脚本注册成独立工具？

**问题现象**

用户希望 skill 的 `scripts/` 可以使用，但不希望每个脚本都变成一个工具。

**原因**

如果把所有脚本注册成工具：

- 工具列表会膨胀。
- prompt 变长。
- 每个脚本 schema 都要维护。
- 新增脚本需要改核心工具注册逻辑。

**解决方法**

采用统一 runtime：

```text
run_skill_script(skill_name, script_path, arguments, timeout_seconds)
```

优点：

- 工具入口稳定。
- skill 脚本按需执行。
- 路径可控。
- trace 统一。
- 不需要为每个脚本注册单独 tool。

### Q16：命中 skill 后为什么不立即加载 `reference.md/forms.md`？

**问题现象**

用户担心不加载 reference 会影响能力完整性。

**原因**

如果每次命中 skill 都加载所有 reference：

- prompt 会非常长。
- 很多任务不需要 reference 细节。
- 低相关上下文会干扰模型。

**解决方法**

采用 progressive loading：

- 命中 skill：只注入 `SKILL.md`。
- 如果需要更细规则，再用 `read_file` 读取 `reference.md/forms.md`。
- scripts 也只提示目录，不自动读取源码。

### Q17：为什么 Anthropic skill 里的 reference 代码不会自动执行？

**问题现象**

reference 中给了示例代码，但模型不会直接根据代码执行。

**原因**

reference 是说明文档，不是可执行脚本。模型可以读它、理解它，但不会天然把里面的代码变成可靠命令。

**解决方法**

把高频 reference 代码沉淀成真实脚本：

```text
workspace/skills/pdf/scripts/extract_text.py
workspace/skills/pdf/scripts/extract_tables.py
workspace/skills/pdf/scripts/pdf_ops.py
workspace/skills/pdf/scripts/create_report.py
```

这样模型可以通过 `run_skill_script` 稳定执行。

### Q18：为什么 weather skill 一开始没有按模板调用？

**问题现象**

天气查询时，模型直接拼 PowerShell/curl 命令，没有按 `SKILL.md` 的模板。

**原因**

命令模板只是文本提示，不是强约束。模型可能选择自己熟悉的命令方式。

**解决方法**

把模板升级成脚本：

```text
workspace/skills/weather/scripts/query_weather.py
```

并在 policy 中明确：

```text
天气查询必须优先执行 run_skill_script(weather/scripts/query_weather.py)
```

### Q19：为什么 `skill_trace.jsonl` 里日志太多重复？

**问题现象**

trace 中大量重复 `skill_activation` 或脚本执行记录。

**原因**

每轮 prompt 构建和 runtime note 构建可能都会触发 skill route；如果没有控制 trace，就会重复记录。

**解决方法**

- `build_prompt_section(... trace_activation=False)` 不写 trace。
- `build_runtime_note(... trace_activation=True)` 统一写一次 activation trace。
- 脚本执行 trace 只由 `SkillRuntime` 写。

### Q20：为什么命中多个 skill 时，只执行了一个 skill？

**问题现象**

用户请求：

```text
查询天气，并写在 docx 里保存
```

trace 显示：

```json
"skills": ["weather", "docx"]
```

但脚本 trace 只有 weather。

**原因**

当前多 skill 机制是：

- Router 可以命中多个 skill。
- Loader 注入多个 `SKILL.md`。
- 模型自行规划执行顺序。

但如果某个步骤由普通工具完成，例如 `save_outbox_file(.docx)`，就不会有 docx script trace。

**解决方法**

当前这是合理行为。

**后续建议**

实现 `SkillWorkflowPlanner`：

```text
route -> plan -> execute -> verify -> respond
```

并补充 docx/pdf/xlsx 产物生成脚本，让多 skill 执行更可观测。

### Q21：为什么要从规则路由升级到 Hybrid Router？

**问题现象**

规则路由阈值固定，最多命中数量固定，对“总结这个文件”“处理刚刚那个表”这种模糊表达不够灵活。

**原因**

规则适合强信号，例如 `.xlsx/.pdf/.docx`，但不擅长语义判断。

**解决方法**

实现 Hybrid Router：

- Rule Router：负责扩展名、MIME、附件、强关键词。
- LLM Router：负责语义路由。
- Hybrid Merge：合并两者，强附件信号不会被 LLM 漏掉。

配置：

```python
SKILL_ROUTE_MODE = "hybrid"
```

## 6. Memory 系统

### Q22：为什么 QQ session 已经很长了，但 memory 没有整合？

**问题现象**

session jsonl 超过阈值，但 `MEMORY.md` 和 `history.jsonl` 没有更新。

**原因**

可能原因包括：

- 触发条件没有满足。
- consolidation 模型返回不是合法 JSON。
- LLM 调用失败。
- 返回内容被过滤，没有有效 memory item。

**解决方法**

增加可观测性：

```text
workspace/memory/consolidation_trace.jsonl
```

记录：

- started
- success
- llm_error
- parse_error
- embedding_error
- empty_result

### Q23：为什么出现 `Consolidation JSON parse failed`？

**问题现象**

终端出现：

```text
[Memory] Consolidation JSON parse failed
```

**原因**

模型没有按要求返回 JSON，或返回了带多余文本的内容。

**解决方法**

增加 JSON 解析容错：

- 直接解析 JSON。
- 解析 fenced JSON。
- 从回复中截取第一个 `{...}`。
- 仍失败则写入 trace，不更新 memory。

### Q24：为什么 `MEMORY.md` 被覆盖，而不是追加？

**问题现象**

用户发现之前 `MEMORY.md` 的内容只剩新整合的一条。

**原因**

`MEMORY.md` 已经被定义为人类可读视图，不是权威日志。它由 `memory_store.jsonl` 中 `active=true` 的 item 重新渲染。

**解决方法**

明确文件职责：

- `memory_store.jsonl`：长期记忆主库。
- `MEMORY.md`：派生视图，可以覆盖。
- `history.jsonl/HISTORY.md`：历史追加日志。

### Q25：为什么不直接把 `MEMORY.md` 注入 prompt？

**问题现象**

用户希望记忆参与回答，但不希望每轮注入全部记忆。

**原因**

整份注入会导致：

- prompt 增长。
- 无关记忆干扰当前任务。
- 无法做相似度检索和重排。

**解决方法**

改为：

1. 对当前 query 做 embedding。
2. 从 `memory_store.jsonl` 读取 active items。
3. 用预存 embedding 做相似度召回。
4. 关键词/topic/confidence rerank。
5. 注入 top_k：

```markdown
# Relevant Memory
- [workflow] (xlsx file processing) ...
```

### Q26：是否每轮都重新 embedding 历史记忆？

**问题现象**

用户担心每轮都对历史会话做 embedding，成本高且慢。

**原因**

如果没有向量缓存，确实会这样。

**解决方法**

`memory_store.jsonl` 每个 item 都保存 `embedding` 字段。

每轮只需要：

- 对当前 query 做一次 embedding。
- 与 memory item 的预存 embedding 做 cosine similarity。

### Q27：Agent 知道自己做了相似度检索吗？

**问题现象**

用户问记忆时，模型回答看起来像自己读了文件，而不是明确说做了相似度检索。

**原因**

检索是系统侧动作，模型只看到注入后的 `# Relevant Memory`，不一定知道检索过程细节。

**解决方法**

当前可以通过回答内容间接验证。

**后续建议**

增加 retrieval trace：

```text
workspace/memory/memory_retrieval_trace.jsonl
```

记录：

- query
- selected memory ids
- embedding score
- lexical score
- rerank score
- fallback 状态

## 7. Tool Grounding 与失败恢复

### Q28：为什么工具失败后，模型还说“已成功”？

**问题现象**

工具返回 Error，但模型仍然给出成功语气。

**原因**

模型没有严格把工具返回作为最高优先级事实来源。

**解决方法**

增加 Tool Grounding Policy：

- 工具结果是最高优先级事实来源。
- 工具返回 `Error:` 时必须说明失败。
- `Return code != 0` 不能声称成功。
- 不允许编造工具没有返回的结论。

### Q29：为什么模型会继续输出“正在处理”，但实际没有处理？

**问题现象**

用户收到“正在处理……”后没有后续结果。

**原因**

模型把中间态当成最终回复。

**解决方法**

Agent loop 增加不完整回复检测：

- 如果用户请求是操作型任务。
- 且已经调用过工具。
- 最终回复仍是“正在处理 / 下一步将 / 稍后生成”。

则不发送给用户，继续循环，要求模型完成任务或明确失败。

## 8. 运行环境与依赖

### Q30：为什么固定 Python 3.11.15？

**问题现象**

用户本地环境是 `assistant (3.11.15)`，希望项目按这个版本来。

**原因**

Office 处理、依赖安装和本地脚本执行都依赖 Python 环境稳定。

**解决方法**

在 config 中明确：

```python
PREFERRED_PYTHON = "3.11.15"
REQUIRED_PYTHON_SERIES = (3, 11)
PREFERRED_PYTHON_EXECUTABLE = Path(r"D:\conda\envs\assistant\python.exe")
```

启动时检查 Python 主版本。

### Q31：为什么 PowerShell 每次都有 profile 执行策略报错？

**问题现象**

每次运行命令都会出现：

```text
profile.ps1 cannot be loaded because running scripts is disabled
```

**原因**

PowerShell 尝试加载用户 profile，但当前执行策略禁止脚本。

**影响**

大多数命令仍然正常执行，只是终端输出会带噪音。

**解决方法**

可以忽略；如果要清理，使用 `-NoProfile` 启动 PowerShell，或调整执行策略。

### Q32：如何检查 skill 系统整体是否可运行？

**问题现象**

随着 skill 增多，不知道脚本、依赖、命令是否完整。

**解决方法**

新增 Skill Doctor：

```powershell
python miniagent.py skills doctor
```

检查：

- `workspace/skills` 是否存在。
- `skill_trace.jsonl` 是否可写。
- `SKILL.md` 是否可读。
- 引用脚本是否存在。
- Python 脚本是否有语法错误。
- `openpyxl/pdfplumber/python-docx/reportlab` 等包是否可导入。
- `soffice/pandoc` 是否在 PATH。

## 9. 当前仍未完全解决的问题

### Q33：项目现在最大的架构短板是什么？

**答案**

主要有四个：

1. **附件索引缺失**
   session 裁剪后，旧附件工具可见性不稳定。

2. **多用户长期 memory 未隔离**
   session 已隔离，但 `memory_store.jsonl` 仍全局共享。

3. **多 skill workflow 未显式规划**
   当前只是注入多个 `SKILL.md`，执行顺序由模型自己决定。

4. **产物 trace 不完整**
   `save_outbox_file` 生成的 `.docx/.pdf/.xlsx` 不进入 `skill_trace.jsonl`。

### Q34：下一步最值得做什么？

**推荐顺序**

1. 增加 attachment index，解决历史文件可见性。
2. 增加 memory retrieval trace，让检索过程可观测。
3. 给 `save_outbox_file` 增加产物 trace。
4. 补 `docx/scripts/create_docx.py`，让 Word 生成走 skill runtime。
5. 实现轻量 `SkillWorkflowPlanner`，让多 skill 任务有显式步骤。
6. 实现 user-scoped memory，支持多 QQ 用户隔离。

