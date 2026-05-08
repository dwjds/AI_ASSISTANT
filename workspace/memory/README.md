# MiniAgent Memory System

MiniAgent 的 memory 系统用于把短期会话、长期事实、历史摘要和可检索记忆分层管理。它的核心原则是：**session 保存原始上下文，memory_store 保存可检索长期事实，MEMORY.md 只是人类可读视图，不再作为 prompt 注入事实源。**

当前设计目标：

- **短期连续性**：每个 channel/session 保存最近原始对话，保证当前问题不断片。
- **长期可复用**：只把稳定、可复用、已验证的信息写入长期记忆。
- **结构化存储**：长期记忆以 JSONL item 存储，便于去重、冲突处理、向量检索和 rerank。
- **按需注入**：每轮不注入整份 `MEMORY.md`，只注入与当前 query 最相关的 top_k memory。
- **可观测**：consolidation 的开始、成功、解析失败、LLM 失败、embedding 失败写入 trace。

## File Roles

Memory 系统固定使用以下文件角色：

| 文件 | 角色 | 是否权威事实源 | 是否默认注入 prompt | 写入方式 |
| --- | --- | --- | --- | --- |
| `workspace/sessions/*.jsonl` | 短期会话原始记录 | 当前 session 的短期事实源 | 最近消息会进入 prompt | 每轮 user/assistant 追加后保存 |
| `workspace/memory/history.jsonl` | 每次 consolidation 的结构化历史摘要日志 | 历史归档，不是长期检索主源 | 不默认注入 | consolidation 成功后追加 |
| `workspace/memory/memory_store.jsonl` | 长期记忆主库 | **长期检索唯一事实源** | 检索 top_k 后注入 | upsert / 去重 / 冲突处理 |
| `workspace/memory/MEMORY.md` | 人类可读长期记忆总览 | 否，由 store 派生 | **不整份注入** | 根据 active memory items 重新渲染 |
| `workspace/memory/HISTORY.md` | 人类可读历史摘要 | 否，归档视图 | 不默认注入 | consolidation 成功后追加 |
| `workspace/memory/consolidation_trace.jsonl` | consolidation 运行日志 | 调试事实源 | 不注入 | 每次 consolidation 事件追加 |

重要约定：

- `memory_store.jsonl` 是长期记忆检索的唯一主库。
- `MEMORY.md` 可以手工看，但手工改它不会自动更新 `memory_store.jsonl`。
- 如果 `MEMORY.md` 和 `memory_store.jsonl` 不一致，以 `memory_store.jsonl` 为准。
- `history.jsonl` 记录“发生过什么”，`memory_store.jsonl` 记录“以后还值得记住什么”。

## Directory Layout

```text
workspace/
├── sessions/
│   ├── cli__direct.jsonl
│   └── qq__private__<openid>.jsonl
└── memory/
    ├── README.md
    ├── MEMORY.md
    ├── HISTORY.md
    ├── history.jsonl
    ├── memory_store.jsonl
    └── consolidation_trace.jsonl
```

核心实现：

```text
miniagent_core/memory.py
├── Session                 # 单个会话内存对象
├── SessionManager          # session 文件加载、保存、reset
├── HistoryRecord           # history.jsonl 结构化摘要
├── MemoryItem              # memory_store.jsonl 长期记忆条目
├── ContextBuilder          # system prompt + history note + skill section 构建
├── MemoryStore             # memory 文件读写、检索、upsert、trace
└── consolidate_memory()    # 会话压缩与长期记忆写入
```

相关配置：

```python
MAX_HISTORY_MESSAGES = 15
MEMORY_CONSOLIDATE_TRIGGER = 30
MEMORY_KEEP_RECENT = 15
MEMORY_RETRIEVAL_TOP_K = 4
MEMORY_RETRIEVAL_CANDIDATES = 8
EMBEDDING_MODEL = "text-embedding-v4"
```

## Runtime Flow

每轮用户消息后的 memory 流程：

```text
Inbound message
      |
      v
SessionManager.get_or_create(session_key)
      |
      v
Append current user message to session.messages
      |
      v
If len(session.messages) > MEMORY_CONSOLIDATE_TRIGGER:
      |
      +--> old = session.messages[:-MEMORY_KEEP_RECENT]
      +--> consolidate old messages
      +--> append history.jsonl / HISTORY.md
      +--> upsert memory_store.jsonl
      +--> re-render MEMORY.md
      +--> trim session.messages to last MEMORY_KEEP_RECENT
      |
      v
Retrieve relevant memory for current query
      |
      v
Inject # Relevant Memory if any
      |
      v
Build model messages:
  - system prompt
  - history note
  - relevant memory note
  - recent session messages
  - current user message
      |
      v
Model + tools
      |
      v
Append assistant reply to session.messages
      |
      v
SessionManager.save(session)
```

注意：

- 短期 session 和长期 memory 是两层不同机制。
- 当前 session 最近消息仍然直接进入 prompt，用于保持对话连续性。
- 长期 memory 是检索后按相关性注入，不是全文注入。

## Session Layer

`workspace/sessions/*.jsonl` 保存原始消息：

```json
{"role": "user", "content": "总结这个文件", "timestamp": "...", "attachments": [...]}
{"role": "assistant", "content": "文件摘要如下...", "timestamp": "..."}
```

session key 示例：

| Channel | session key | 文件名 |
| --- | --- | --- |
| CLI | `cli:direct` | `cli__direct.jsonl` |
| QQ private | `qq:private:<openid>` | `qq__private__<openid>.jsonl` |

当前行为：

- 不同 session 有不同 jsonl 文件。
- consolidation 只压缩当前 session 的旧消息。
- 长期 memory 目前是全局共享，不做多用户隔离。
- 如果未来要支持多用户隔离，应把 `memory_store.jsonl` 拆到 user/session scope。

## Consolidation Trigger

触发条件：

```python
len(session.messages) > MEMORY_CONSOLIDATE_TRIGGER
```

当前默认：

```python
MEMORY_CONSOLIDATE_TRIGGER = 30
MEMORY_KEEP_RECENT = 15
```

也就是当 session 消息数超过 30 时：

- 旧消息：`session.messages[:-15]`
- 保留短期上下文：`session.messages[-15:]`

consolidation 会让模型输出 JSON：

```json
{
  "history_summary": "one concise summary for history log",
  "history_topic": "main topic",
  "history_keywords": ["keyword1", "keyword2"],
  "memory_markdown": "updated MEMORY.md markdown",
  "memory_items": [
    {
      "type": "preference|project|fact|workflow|profile|tooling",
      "topic": "stable topic label",
      "summary": "standalone reusable memory sentence",
      "keywords": ["keyword1", "keyword2"],
      "tags": ["optional-tag"],
      "confidence": 0.8
    }
  ]
}
```

解析容错：

- 直接 JSON：`direct_json`
- fenced code block：`fenced_json`
- 回复中嵌入 JSON：`embedded_json`
- 解析失败：`parse_error`，写入 trace，不更新 memory。

## History Records

`history.jsonl` 每次 consolidation 追加一条：

```json
{
  "timestamp": "2026-05-07T18:00:00",
  "session_key": "qq:private:<openid>",
  "summary": "完成了 xlsx 文件筛选并输出新 Excel。",
  "topic": "xlsx workflow",
  "keywords": ["xlsx", "filter", "AI"],
  "message_count": 15
}
```

用途：

- 归档旧对话摘要。
- 帮助人类追踪项目活动。
- 后续可扩展为历史检索源。

当前检索默认不以 `history.jsonl` 为主源；长期事实仍以 `memory_store.jsonl` 为准。

## Memory Item Schema

`memory_store.jsonl` 中每条记录固定字段如下：

| 字段 | 类型 | 含义 | 说明 |
| --- | --- | --- | --- |
| `id` | `str` | 记忆条目唯一标识 | 当前由 `type + topic + summary` 计算 SHA1 前 16 位 |
| `timestamp` | `str` | 首次形成时间 | 这条 memory 最初写入长期记忆的时间 |
| `updated_at` | `str` | 最近更新时间 | 最近一次确认、刷新、冲突处理或 active 状态变更的时间 |
| `source` | `str` | 来源 session | 例如 `qq:private:<openid>` |
| `type` | `str` | 记忆类别 | 允许值：`profile / preference / project / fact / workflow / tooling` |
| `topic` | `str` | 稳定主题标签 | 用于聚类、冲突判断和 rerank |
| `summary` | `str` | 长期事实摘要 | 应该是一条可独立理解、可复用的事实 |
| `keywords` | `list[str]` | 关键词 | 用于 lexical fallback 和 rerank |
| `tags` | `list[str]` | 补充标签 | 用于调试、过滤、未来扩展 |
| `confidence` | `float` | 置信度 | `0.0 ~ 1.0`，用于排序和冲突决策 |
| `active` | `bool` | 是否活跃 | 冲突或过期记忆标记为 `false`，不直接删除 |
| `embedding` | `list[float]` | 向量表示 | 对 `topic + summary + keywords` 生成，用于相似度召回 |

示例：

```json
{
  "id": "2d4ab8f3a5e1c901",
  "timestamp": "2026-05-07T18:00:00",
  "updated_at": "2026-05-07T18:00:00",
  "source": "qq:private:AEDF...",
  "type": "workflow",
  "topic": "xlsx file processing",
  "summary": "用户常用 Excel workflow：筛选研究内容包含 AI 且需求专业包含软件工程的课题，并输出新 xlsx 文件。",
  "keywords": ["xlsx", "AI", "软件工程", "筛选"],
  "tags": ["file-workflow"],
  "confidence": 0.9,
  "active": true,
  "embedding": [0.0123, -0.0456]
}
```

## Allowed Long-Term Memory

允许进入长期记忆：

- 用户身份与稳定偏好。
- 默认位置、默认语言、默认输出风格。
- 稳定项目背景、运行环境、工具约束。
- 已验证的长期任务结论。
- 高价值 workflow 结果，例如某类文件处理流程。

不允许进入长期记忆：

- 一次性临时对话。
- 未验证推测。
- 工具报错但未解决的中间状态。
- 冗长原文摘抄。
- 重复文件列表。
- “刚刚上传了什么”这类只属于短期 session 的信息。

代码层过滤规则：

- `type` 必须属于允许集合。
- `summary` 非空，长度大致在 `8 ~ 240` 字符。
- `topic` 不应过长。
- `confidence` 必须大于 0。
- 含有 transient / unresolved / redundant hint 的 summary 会被过滤。

过滤关键词类别：

| 类别 | 示例 |
| --- | --- |
| transient | `刚刚`、`这一轮`、`临时`、`中间状态` |
| unresolved | `未解决`、`执行失败`、`报错`、`not found` |
| redundant | `文件列表`、`完整内容如下`、`原文如下` |

## Upsert / Dedup / Conflict

写入 `memory_store.jsonl` 时使用 upsert，而不是简单追加。

### Exact Dedup

同一条记忆定义为：

```text
type + topic + summary
```

如果新 item 与旧 item 完全同 key：

- 只刷新 `updated_at`。
- 保留或合并必要字段。
- 不重复产生多条相同 memory。

### Topic Conflict

冲突定义：

```text
同 type + topic，但 summary 不同
```

处理方式：

- 选择 `confidence` 更高的 item。
- 如果置信度相同或接近，选择 `updated_at` 更新的 item。
- 输掉的 item 不删除，而是 `active=false`。
- 这样可以保留审计痕迹，也避免旧记忆继续参与检索。

### MEMORY.md Rendering

每次 upsert 后：

1. 读取所有 memory items。
2. 过滤 `active=true`。
3. 按类型分组。
4. 重新渲染 `MEMORY.md`。

因此 `MEMORY.md` 是派生视图，覆盖是预期行为，不是数据丢失。真正长期记忆在 `memory_store.jsonl`。

## Embedding Storage

consolidation 产生 memory_items 后，会对每条 item 生成 embedding：

```text
text_for_embedding = topic + " | " + summary + " | " + keywords
```

调用：

```python
client.embeddings.create(model=EMBEDDING_MODEL, input=text_for_embedding)
```

然后把向量写入 `memory_store.jsonl` 的 `embedding` 字段。

这样检索时不需要每轮重新 embedding 历史 memory，只需要：

- 对当前 query 做一次 embedding。
- 从 `memory_store.jsonl` 读取预存 item embedding。
- 做 cosine similarity。

如果 embedding 写入失败：

- 写入 `consolidation_trace.jsonl`，状态为 `embedding_error`。
- memory item 仍可写入，但没有 embedding。
- 后续检索会依靠 lexical fallback / rerank。

## Retrieval Pipeline

每轮 query 的长期记忆检索流程：

```text
Current user query
      |
      v
Generate query embedding
      |
      v
Read active memory items from memory_store.jsonl
      |
      v
For each memory item:
  - embedding_score = cosine(query_embedding, item.embedding)
  - lexical_score = keyword_overlap(query_tokens, item topic/summary/keywords/tags)
      |
      v
Sort and keep candidate_pool
      |
      v
Rerank candidates
      |
      v
Return top_k
      |
      v
Format as # Relevant Memory
```

配置：

```python
MEMORY_RETRIEVAL_TOP_K = 4
MEMORY_RETRIEVAL_CANDIDATES = 8
```

## Similarity Retrieval

### Query Embedding

如果 `client` 和 `EMBEDDING_MODEL` 可用：

```python
query_embedding = embed(query)
```

否则跳过向量检索，直接 lexical fallback。

### Cosine Similarity

当 query 和 item 都有 embedding 时：

```text
embedding_score = cosine(query_embedding, item.embedding)
```

如果 item 没有 embedding，或者向量维度不一致：

```text
embedding_score = 0
```

### Lexical Fallback

query 会被 tokenize：

```python
re.findall(r"[\u4e00-\u9fff]{1,8}|[a-z0-9_./:+-]+", text)
```

item tokens 来自：

- `topic`
- `summary`
- `keywords`
- `tags`

lexical score：

```text
lexical_score = overlap(query_tokens, item_tokens) / len(query_tokens)
```

如果 query embedding 失败，会打印：

```text
[Memory] Embedding retrieval failed, fallback to lexical rerank: ...
```

然后使用 lexical score 作为 base score。

## Rerank Strategy

第一阶段召回：

```python
base_score = embedding_score if query_embedding else lexical_score
```

按：

```text
(base_score, lexical_score, confidence)
```

排序，取：

```python
candidate_pool = max(top_k, MEMORY_RETRIEVAL_CANDIDATES)
```

第二阶段 rerank：

```text
rerank_score =
  base_score * 0.80
  + lexical_score * 0.15
  + topic_bonus
  + confidence_bonus
```

其中：

```text
topic_bonus = 0.08
```

当 query tokens 与 item.topic tokens 有交集时触发。

```text
confidence_bonus = confidence * 0.05
```

最终按 `rerank_score` 排序，返回 top_k。

设计意图：

- 向量相似度负责语义召回。
- lexical overlap 防止关键词明确但 embedding 漂移。
- topic bonus 让主题标签命中的 item 更靠前。
- confidence bonus 让高置信记忆略微优先。

## Prompt Injection

检索结果统一注入为：

```markdown
# Relevant Memory
- [profile] (identity) 用户名为小明，偏好简洁技术中文交流。
- [workflow] (xlsx file processing) 用户常用 Excel workflow：筛选 AI + 软件工程课题并输出新 xlsx。
```

规则：

- 不直接注入整份 `MEMORY.md`。
- 没有检索到相关 item 时，不注入 `# Relevant Memory`。
- 模型不得硬编“相关记忆”。
- 如果用户问“你记得什么”，应基于检索结果、session 历史或显式读取 memory 文件回答，并说明信息来源。

## Observability

consolidation trace 文件：

```text
workspace/memory/consolidation_trace.jsonl
```

事件字段：

| 字段 | 含义 |
| --- | --- |
| `timestamp` | 事件时间 |
| `kind` | 当前固定为 `memory_consolidation` |
| `session_key` | 被整合的 session |
| `status` | 状态 |
| `message_count` | consolidation 前 session 消息数 |
| `trigger_messages` | 触发阈值 |
| `keep_recent` | 保留最近消息数 |
| `old_message_count` | 被压缩的旧消息数 |
| `details` | 解析模式、写入数量、错误信息等 |
| `raw_response_preview` | 解析失败时保留模型原始输出预览 |

状态：

| status | 含义 |
| --- | --- |
| `started` | 开始整合 |
| `success` | 整合成功，session 已裁剪 |
| `llm_error` | 调 consolidation 模型失败 |
| `parse_error` | 模型返回无法解析成目标 JSON |
| `embedding_error` | memory item 写入前生成 embedding 失败 |
| `empty_result` | JSON 有效，但没有 history 或 memory 内容 |

成功 details 示例：

```text
parse_mode=direct_json history_written=True memory_written=True memory_items=3 remaining_messages=15
```

## Debugging Guide

### 为什么 MEMORY.md 被覆盖？

这是预期行为。`MEMORY.md` 是由 `memory_store.jsonl` 中 `active=true` 的 item 渲染出来的人类可读视图。它不是追加日志，也不是检索主源。

如果只想保留历史演变，请看：

- `history.jsonl`
- `HISTORY.md`
- `consolidation_trace.jsonl`

### 为什么 session 达到阈值却没写 memory？

可能原因：

- consolidation 模型调用失败，查看 `llm_error`。
- 模型返回不是合法 JSON，查看 `parse_error` 和 `raw_response_preview`。
- 返回了 JSON，但没有有效 `memory_items`，查看 `empty_result`。
- memory_items 被过滤掉，例如包含“刚刚”“报错”“未解决”等短期或失败信息。

### 为什么问记忆时看不出检索？

当前检索是系统侧强制执行，不是模型自己决定。模型不一定知道“刚刚做了向量检索”，只会看到注入后的 `# Relevant Memory`。

要验证检索是否发生，可以：

- 查看终端是否有 embedding fallback 日志。
- 临时增加 memory retrieval trace。
- 问一个和已有 memory 高度相关的问题，观察回答是否只引用相关 top_k，而不是全量 memory。

### 为什么 session 里没有旧附件？

session 会在 consolidation 后裁剪，只保留最近 `MEMORY_KEEP_RECENT` 条消息。如果附件记录在旧消息中，可能被裁掉。

当前 memory 系统不会把附件对象恢复成可调用附件工具。长期 memory 只能保存“曾处理过某文件”的语义事实，不等同于附件索引。

未来应新增独立 attachment index。

### 为什么手工改 MEMORY.md 不影响检索？

因为检索读取的是 `memory_store.jsonl`。如果要影响检索，需要修改或新增 `memory_store.jsonl` item，并包含合适的 `summary/keywords/topic/embedding`。

## Current Limitations

当前仍未完善的地方：

- **多用户 memory 隔离**：目前长期 memory 是全局共享，不按 QQ 用户独立分库。
- **检索 trace**：consolidation 有 trace，但每轮 retrieval 的 query、top_k、score 还没有写入 trace。
- **embedding 修复任务**：如果旧 memory item 没有 embedding，目前没有自动后台补向量。
- **附件索引缺失**：memory 能记住文件处理事实，但不能恢复附件工具可见性。
- **冲突识别较粗**：现在主要按 `type + topic` 判断冲突，还没有更细的语义冲突检测。
- **MEMORY.md 手工编辑不可回写**：它是派生视图，不支持反向同步到 store。

## Recommended Next Improvements

建议后续按这个顺序继续系统化：

1. **Memory Retrieval Trace**：新增 `memory_retrieval_trace.jsonl`，记录 query、top_k、score、fallback、注入内容。
2. **Embedding Backfill**：提供命令补齐 `memory_store.jsonl` 中缺失的 embedding。
3. **Attachment Index**：把每次上传文件独立登记，避免 session 裁剪后找不到旧文件。
4. **User-Scoped Memory**：按 user/session 拆分 memory store，实现 QQ 多用户隔离。
5. **Conflict Review Tool**：列出 `active=false` 和同 topic 冲突记忆，支持人工审计。

