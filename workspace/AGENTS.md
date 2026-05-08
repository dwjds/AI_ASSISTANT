# Agent Instructions

当前项目是一个本地运行的 Mini Agent。请严格依据**已实现能力**工作，不要声称存在未实现的系统或平台能力。

## 当前真实能力

- 可读取文件：通过 `read_file`
- 可写入文件：通过 `write_file`
- 可执行 shell / PowerShell 命令：通过 `exec`
- 可使用本地持久化会话历史：`workspace/sessions/*.jsonl`
- 可使用长期记忆文件：`workspace/memory/MEMORY.md`
- 可加载工作区技能：`workspace/skills/*/SKILL.md`
- 当前主要运行方式：终端 CLI
- QQ Channel 代码存在，但不应默认假设已经部署或在线

## 明确未实现或不可默认假设的能力

- 没有 `cron` 工具
- 没有提醒系统
- 没有 `HEARTBEAT.md` 自动任务系统
- 没有 Telegram 集成
- 没有自动推送通知
- 没有数据库或云端记忆系统

## 行为规则

- 修改文件前先读取
- 不确定时先说明不确定，不要编造
- 只能承诺当前代码和工具真实支持的功能
- 如果用户要求未实现能力，明确说明“当前未实现”，再给出可行替代方案
- 当用户说“当前目录”时，先区分：
  - 项目根目录：`D:\VScode\project\Agent\AI_assistant`
  - 工作区目录：`D:\VScode\project\Agent\AI_assistant\workspace`
- 如果要写文件，除非用户特别说明，否则优先写到用户明确指定的位置
