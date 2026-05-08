## 明确 Agent 工程：

### 多 Channel Agent 架构：
CLI + QQBot，支持 session 管理、消息总线、入站/出站消息处理。

### 文件型 Agent 能力：
支持用户上传文件，落盘到 inbox，处理结果写入 outbox，能解析/生成 txt/docx/pdf/xlsx。

### Skill Runtime：
有 scanner / registry / router / loader / runtime / policy / doctor，支持按需加载 skill、统一执行脚本、trace 可观测。

### Hybrid Skill Router：
规则路由 + LLM 语义路由，支持多 skill 命中。

### 长期记忆系统：
session 短期记忆 + memory_store.jsonl 长期结构化记忆 + embedding 检索 + rerank。

### 可观测性：
skill_trace.jsonl、consolidation_trace.jsonl、benchmark report。

### Benchmark 框架：统计成功率、工具调用次数、平均步数、失败类型；还有 memory retrieval benchmark，能测 Recall@K / MRR。

### 工程文档：
skill README、memory README、PROJECT_QA，都已经有项目级说明。


## 但最好定位为“正在持续迭代的 Agent 工程项目”，不要包装成生产级平台。

如果想让它在简历上更硬，再补 3 个东西会很加分：

扩 benchmark 到 20-40 条，给出稳定指标。
加附件索引，解决历史文件可见性。
加一张架构图和一次 benchmark 截图/表格放 README 首页。