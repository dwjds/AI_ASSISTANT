from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .async_compat import run_blocking
from .attachments import AttachmentStore
from .channels import BaseChannel, CLIChannel, QQChannel
from .config import (
    EMBEDDING_MODEL,
    MAX_HISTORY_MESSAGES,
    MEMORY_CONSOLIDATE_TRIGGER,
    MEMORY_KEEP_RECENT,
    MEMORY_RETRIEVAL_CANDIDATES,
    MEMORY_RETRIEVAL_TOP_K,
    MODEL,
    WORKSPACE,
    client,
)
from .memory import ContextBuilder, MemoryStore, SessionManager, consolidate_memory
from .message import InboundMessage, MessageBus, OutboundMessage
from .skills import SkillLoader
from .tools import (
    BrowserAutomationTool,
    ExecTool,
    FindFilesTool,
    ListOutboxFilesTool,
    ListUploadedFilesTool,
    ReadFileTool,
    ReadUploadedFileTool,
    RunSkillScriptTool,
    SaveOutboxFileTool,
    SearchCodeTool,
    ToolRegistry,
    WebFetchTool,
    WebSearchTool,
    WriteFileTool,
)

ACTION_REQUEST_HINTS = (
    "打开","关闭","最小化","恢复","激活","切到","点击","发送","截图","保存","检查","列出",
    "查找","输入","拖拽","切换","处理","生成","筛选","提取","汇总","计算","转换","修改","新增",
    "删除","导出","总结","restore","activate","click","send","screenshot","save","inspect","list",
    "process","generate","filter","extract","summarize","calculate","convert","modify","edit","export",
)

TOOL_CLAIM_HINTS = (
    "browser_automation(",
    "exec(",
    "web_search(",
    "web_fetch(",
    "已执行",
    "已完成",
    "成功捕获",
    "验证结果",
)

INCOMPLETE_PROGRESS_HINTS = (
    "正在处理",
    "正在生成",
    "正在执行",
    "正在筛选",
    "正在读取",
    "正在保存",
    "正在计算",
    "下一步将",
    "接下来将",
    "将继续",
    "我将",
    "稍等",
    "请稍候",
    "处理中",
    "正在处理……",
    "processing",
    "working on it",
    "next i will",
    "i will now",
)

FULL_ATTACHMENT_OUTPUT_HINTS = (
    "全文",
    "完整内容",
    "原文",
    "逐字",
    "逐段",
    "完整表格",
    "所有内容",
    "全文输出",
    "详细展开",
    "完整展开",
    "full text",
    "verbatim",
    "raw content",
    "print all",
)


def build_default_tools(
    llm_client: Any | None = None,
    model: str | None = None,
    attachment_store: AttachmentStore | None = None,
    session_key: str | None = None,
    inbound_attachments: list[Any] | None = None,
    session_attachments: list[Any] | None = None,
    skill_loader: SkillLoader | None = None,
    workspace: Path = WORKSPACE,
) -> ToolRegistry:
    tools = ToolRegistry()
    tools.register(ExecTool())
    tools.register(ReadFileTool())
    tools.register(WriteFileTool())
    tools.register(FindFilesTool())
    tools.register(SearchCodeTool())
    tools.register(WebSearchTool())
    tools.register(WebFetchTool())
    tools.register(BrowserAutomationTool())
    tools.register(RunSkillScriptTool(skill_loader or SkillLoader(workspace)))
    if attachment_store is not None and session_key:
        tools.register(ListOutboxFilesTool(attachment_store, session_key))
        tools.register(SaveOutboxFileTool(attachment_store, session_key))
        attachments = list(inbound_attachments or [])
        for item in list(session_attachments or []):
            if all(str(existing.path) != str(item.path) for existing in attachments):
                attachments.append(item)
        if attachments:
            tools.register(ListUploadedFilesTool(attachments))
            tools.register(ReadUploadedFileTool(attachment_store, attachments))
    return tools


async def agent_loop(
    client: Any,
    model: str,
    messages: list[dict[str, Any]],
    tools: ToolRegistry,
    max_iterations: int = 10,
    metrics: dict[str, Any] | None = None,
) -> str:
    if client is None:
        return "LLM client is unavailable in this Python environment. Please activate the correct environment and configure the API key."

    forced_tool_retry = False
    forced_completion_retries = 0
    tools_executed_in_turn = 0

    if metrics is not None:
        metrics.setdefault("iterations", 0)
        metrics.setdefault("tool_calls", 0)
        metrics.setdefault("tool_call_batches", 0)
        metrics.setdefault("tool_names", [])
        metrics.setdefault("tool_errors", [])
        metrics.setdefault("finish_reason", "")

    for _ in range(max_iterations):
        if metrics is not None:
            metrics["iterations"] = int(metrics.get("iterations", 0)) + 1
        definitions = tools.get_definitions() or None

        def _create_completion():
            return client.chat.completions.create(
                model=model,
                messages=messages,
                tools=definitions,
                temperature=0.1,
            )

        resp = await run_blocking(_create_completion)
        msg = resp.choices[0].message
        tool_calls = getattr(msg, "tool_calls", None) or []
        if tool_calls:
            if metrics is not None:
                metrics["tool_call_batches"] = int(metrics.get("tool_call_batches", 0)) + 1
            prepared_tool_calls: list[dict[str, Any]] = []
            prepared_results: list[tuple[Any, dict[str, Any] | None, str | None]] = []
            for tc in tool_calls:
                raw_arguments = tc.function.arguments or "{}"
                normalized_arguments = raw_arguments
                argument_error: str | None = None
                params: dict[str, Any] | None = None
                try:
                    parsed_arguments, repaired_arguments = _parse_tool_arguments(raw_arguments)
                    if repaired_arguments:
                        normalized_arguments = json.dumps(parsed_arguments, ensure_ascii=False)
                        print(
                            "  [ToolArgs] Recovered first JSON object from malformed "
                            f"arguments for {tc.function.name}."
                        )
                except json.JSONDecodeError as exc:
                    argument_error = f"Error: invalid tool arguments JSON: {exc}"
                    normalized_arguments = "{}"
                else:
                    if not isinstance(parsed_arguments, dict):
                        argument_error = (
                            "Error: invalid tool arguments: expected a JSON object "
                            f"but got {type(parsed_arguments).__name__}."
                        )
                        normalized_arguments = "{}"
                    else:
                        params = parsed_arguments
                        normalized_arguments = json.dumps(params, ensure_ascii=False)

                prepared_tool_calls.append(
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": normalized_arguments,
                        },
                    }
                )
                prepared_results.append((tc, params, argument_error))

            messages.append(
                {
                    "role": "assistant",
                    "content": msg.content,
                    "tool_calls": prepared_tool_calls,
                }
            )
            for tc, params, argument_error in prepared_results:
                if argument_error:
                    result = argument_error
                else:
                    print(f"  [Tool] {tc.function.name}({(tc.function.arguments or '')[:80]})")
                    result = await tools.execute(tc.function.name, params or {})
                    tools_executed_in_turn += 1
                if metrics is not None:
                    metrics["tool_calls"] = int(metrics.get("tool_calls", 0)) + 1
                    metrics.setdefault("tool_names", []).append(tc.function.name)
                preview = result.replace("\n", " ")[:160]
                print(f"  [ToolResult] {preview}")
                messages.append(
                    {"role": "tool", "tool_call_id": tc.id, "content": result}
                )
                if result.startswith("Error:") or _is_skill_script_failure(tc.function.name, result):
                    if metrics is not None:
                        metrics.setdefault("tool_errors", []).append(
                            {
                                "tool": tc.function.name,
                                "preview": result[:300],
                            }
                        )
                    messages.append(
                        {
                            "role": "system",
                            "content": _build_tool_failure_recovery_note(tc.function.name, result),
                        }
                    )
                elif (
                    tc.function.name == "run_skill_script"
                    and "Return code: 0" in result
                    and not result.startswith("Error:")
                ):
                    messages.append(
                        {
                            "role": "system",
                            "content": (
                                "The skill script just completed successfully. "
                                "If this result is sufficient for the user's request, stop calling tools and "
                                "reply with a concise summary of the actual result. "
                                "Only call more tools if a required output file still has not been created or verified."
                            ),
                        }
                    )
            continue
        reply = msg.content or ""
        latest_user = _latest_user_text(messages)
        if _should_force_tool_use(latest_user, reply, tools_executed_in_turn):
            if forced_tool_retry:
                if metrics is not None:
                    metrics["finish_reason"] = "forced_tool_use_failed"
                return (
                    "Error: the assistant did not produce a trusted tool-backed result for this action request. "
                    "Please start a new session with /new and try again."
                )
            forced_tool_retry = True
            messages.append({"role": "assistant", "content": reply})
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "The user asked for a real action in this turn, but you have not called any tools yet. "
                        "Do not claim that you executed actions, inspected windows, captured screenshots, or saved files. "
                        "Ignore prior assistant claims in session history unless they are revalidated by tool outputs in this turn. "
                        "You must either call the appropriate tool(s) now or explicitly say you did not execute anything."
                    ),
                }
            )
            continue
        if _should_force_completion(latest_user, reply, tools_executed_in_turn):
            forced_completion_retries += 1
            if forced_completion_retries > 2:
                if metrics is not None:
                    metrics["finish_reason"] = "incomplete_progress"
                return (
                    "Error: the assistant repeatedly stopped at progress-only updates instead of finishing the requested action. "
                    "The task was not completed in this turn. Please retry the request; if the session contains old failed attempts, use /new first."
                )
            messages.append({"role": "assistant", "content": reply})
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "The previous assistant draft is not acceptable as a final answer because it promises future work "
                        "or says it is still processing. Continue the task now in this same turn. "
                        "If more work is needed, call the appropriate tool(s). "
                        "For Excel row filtering, prefer run_skill_script with xlsx/scripts/filter_workbook.py when available. "
                        "Do not invent a skill script path that has not been confirmed to exist. "
                        "A valid final answer must either include the completed result/output path, or clearly state the "
                        "actual blocking failure with the tool evidence. Do not send another progress-only message."
                    ),
                }
            )
            continue
        if metrics is not None:
            metrics["finish_reason"] = "completed"
        return reply

    if metrics is not None:
        metrics["finish_reason"] = "max_iterations"
    return "Max iterations reached."


def _parse_tool_arguments(raw_arguments: str) -> tuple[Any, bool]:
    text = raw_arguments or "{}"
    try:
        return json.loads(text), False
    except json.JSONDecodeError as exc:
        if exc.msg != "Extra data":
            raise
        decoder = json.JSONDecoder()
        parsed, index = decoder.raw_decode(text)
        if not isinstance(parsed, dict):
            raise
        rest = text[index:].strip()
        if not rest:
            return parsed, False
        return parsed, True


def _build_tool_failure_recovery_note(tool_name: str, result: str) -> str:
    base = (
        "The immediately preceding tool call failed. "
        "You must explicitly report that failure to the user if it blocks the task. "
        "Do not claim the action succeeded, do not invent screenshots, window states, "
        "contact lists, button text, output files, or any other observations that were not returned by tools. "
        "If the user's task is still achievable by a different available tool or by writing a small script into "
        "outbox/workspace, continue with that real tool-backed action now. "
        "Do not reply with a progress-only promise such as 'I will do it next'."
    )
    if tool_name == "run_skill_script" and "Skill script not found" in str(result or ""):
        return (
            f"{base} The requested skill script does not exist. "
            "Do not call that missing script again. Use only scripts that are documented in the loaded SKILL.md "
            "or confirmed by reading/listing the skill directory. "
            "For xlsx row filtering tasks, prefer `scripts/filter_workbook.py`. "
            "If no suitable skill script exists, create a temporary script with `write_file` and execute it with `exec`, "
            "saving outputs to workspace/outbox."
        )
    if tool_name == "run_skill_script" and _is_skill_script_failure(tool_name, result):
        return (
            f"{base} The skill script returned a non-zero exit code. "
            "Inspect stderr/stdout, correct the arguments or choose another available workflow, then continue if possible. "
            "If the failure cannot be fixed with available information, stop and provide the exact tool failure."
        )
    return base


def _latest_user_text(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        content = str(message.get("content", "") or "")
        if content.startswith("[Time:") and "\n\n" in content:
            return content.split("\n\n", 1)[1].strip()
        return content.strip()
    return ""


def _looks_like_action_request(text: str) -> bool:
    candidate = (text or "").strip().lower()
    if not candidate:
        return False
    return any(hint in candidate for hint in ACTION_REQUEST_HINTS)


def _looks_like_tool_claim(reply: str) -> bool:
    candidate = (reply or "").strip().lower()
    if not candidate:
        return False
    return any(hint in candidate for hint in TOOL_CLAIM_HINTS)


def _should_force_tool_use(latest_user: str, reply: str, tools_executed_in_turn: int) -> bool:
    return tools_executed_in_turn == 0 and _looks_like_action_request(latest_user) and _looks_like_tool_claim(reply)


def _is_skill_script_failure(tool_name: str, result: str) -> bool:
    if tool_name != "run_skill_script":
        return False
    text = str(result or "")
    return "Return code:" in text and "Return code: 0" not in text


def _looks_like_incomplete_progress(reply: str) -> bool:
    candidate = (reply or "").strip().lower()
    if not candidate:
        return False
    return any(hint in candidate for hint in INCOMPLETE_PROGRESS_HINTS)


def _should_force_completion(latest_user: str, reply: str, tools_executed_in_turn: int) -> bool:
    if tools_executed_in_turn <= 0:
        return False
    if not _looks_like_action_request(latest_user):
        return False
    return _looks_like_incomplete_progress(reply)


def _wants_full_attachment_output(text: str) -> bool:
    candidate = (text or "").strip().lower()
    if not candidate:
        return False
    return any(hint in candidate for hint in FULL_ATTACHMENT_OUTPUT_HINTS)


class MiniAgentApp:
    """把消息总线、记忆、工具和 Channel 装配成可运行的 Agent 应用。"""

    def __init__(
        self,
        workspace: Path = WORKSPACE,
        model: str = MODEL,
        llm_client: Any = client,
        tools: ToolRegistry | None = None,
        bus: MessageBus | None = None,
    ):
        self.workspace = workspace
        self.model = model
        self.client = llm_client
        self.tools = tools
        self.bus = bus or MessageBus()
        self.skill_loader = SkillLoader(workspace)
        self.ctx = ContextBuilder(workspace, skill_loader=self.skill_loader)
        self.attachment_store = AttachmentStore(workspace)
        self.memory = MemoryStore(workspace)
        self.sessions = SessionManager(workspace)
        self.channels: dict[str, BaseChannel] = {}

    def register_channel(self, channel: BaseChannel):
        self.channels[channel.name] = channel

    async def handle_inbound(self, inbound: InboundMessage):
        content = (inbound.content or "").strip()
        if not content and not inbound.media:
            return

        print(f"[App] Handling inbound from {inbound.channel}/{inbound.chat_id}: {content}")

        if content == "/new":
            self.sessions.reset(inbound.session_key)
            await self.bus.publish_outbound(
                OutboundMessage(
                    channel=inbound.channel,
                    chat_id=inbound.chat_id,
                    content="New session started.",
                )
            )
            return

        session = self.sessions.get_or_create(inbound.session_key)

        if inbound.attachments and not content:
            timestamp = datetime.now().isoformat()
            session.messages.append(
                {
                    "role": "user",
                    "content": "",
                    "timestamp": timestamp,
                    "attachments": [item.to_dict() for item in inbound.attachments],
                    "media": inbound.media,
                    "metadata": inbound.metadata,
                }
            )
            names = "、".join(item.name for item in inbound.attachments if item.name)
            if names:
                reply = f"已收到您上传的文件：{names}。"
            else:
                reply = f"已收到您上传的 {len(inbound.attachments)} 个文件。"
            session.messages.append(
                {
                    "role": "assistant",
                    "content": reply,
                    "timestamp": datetime.now().isoformat(),
                }
            )
            self.sessions.save(session)
            await self.bus.publish_outbound(
                OutboundMessage(
                    channel=inbound.channel,
                    chat_id=inbound.chat_id,
                    content=reply,
                )
            )
            print(
                f"[App] Attachment-only message acknowledged for "
                f"{inbound.channel}/{inbound.chat_id}: {reply[:120]}"
            )
            return

        if self.client is not None:
            try:
                await consolidate_memory(
                    client=self.client,
                    model=self.model,
                    session=session,
                    memory=self.memory,
                    trigger_messages=MEMORY_CONSOLIDATE_TRIGGER,
                    keep_recent=MEMORY_KEEP_RECENT,
                    embedding_model=EMBEDDING_MODEL,
                )
            except Exception as exc:
                print(f"[Memory] Consolidation skipped: {exc}")

        self.sessions.save(session)

        history = session.get_history(max_messages=MAX_HISTORY_MESSAGES)
        session_attachments = self.attachment_store.collect_session_attachments(
            session.messages
        )
        all_visible_attachments = list(inbound.attachments)
        for item in session_attachments:
            if all(str(existing.path) != str(item.path) for existing in all_visible_attachments):
                all_visible_attachments.append(item)
        prompt_content = content or "请处理我刚上传的文件。"
        current_attachment_note = self.attachment_store.describe_attachments(inbound.attachments)
        summary_first_instruction = (
            "默认只输出简短摘要、关键结论和可执行建议。"
            "不要复述文件全文，不要逐段粘贴内容，除非用户明确要求全文、原文或完整表格。"
        )
        if current_attachment_note:
            prompt_content = (
                f"{current_attachment_note}\n\n"
                "如需查看上传文件内容，请使用 `list_uploaded_files` 或 `read_uploaded_file`。"
                f"{summary_first_instruction}"
                "如果需要输出结果文件，请使用 `save_outbox_file` 保存到 workspace/outbox。\n\n"
                f"用户要求：{prompt_content}"
            )
        elif all_visible_attachments:
            prompt_content = (
                "你可以访问这个会话里最近上传过的文件。"
                "如需查看文件内容，请使用 `list_uploaded_files` 或 `read_uploaded_file`。"
                f"{summary_first_instruction}"
                "如果需要输出结果文件，请使用 `save_outbox_file` 保存到 workspace/outbox。\n\n"
                f"用户要求：{prompt_content}"
            )
        if all_visible_attachments and not _wants_full_attachment_output(content):
            prompt_content += (
                "\n\n回复要求：除非用户明确要求全文或完整展开，否则仅提供简洁摘要，"
                "优先返回 3-6 条要点、关键风险、结论或下一步建议。"
            )
        retrieval_query = content.strip()
        if not retrieval_query and all_visible_attachments:
            retrieval_query = " ".join(item.name for item in all_visible_attachments if item.name).strip()
        relevant_memory_note = await self.memory.build_relevant_memory_note(
            retrieval_query,
            client=self.client,
            embedding_model=EMBEDDING_MODEL,
            top_k=MEMORY_RETRIEVAL_TOP_K,
            candidate_pool=MEMORY_RETRIEVAL_CANDIDATES,
        )
        runtime_skill_note = self.skill_loader.build_runtime_note(
            prompt_content,
            outbox_dir=self.attachment_store.outbox_session_dir(inbound.session_key),
            attachments=all_visible_attachments,
        )
        messages = self.ctx.build_messages(
            history,
            prompt_content,
            attachments=all_visible_attachments,
            extra_system_notes=[
                note
                for note in (relevant_memory_note, runtime_skill_note)
                if str(note or "").strip()
            ] or None,
        )
        runtime_tools = self.tools or build_default_tools(
            llm_client=self.client,
            model=self.model,
            attachment_store=self.attachment_store,
            session_key=inbound.session_key,
            inbound_attachments=inbound.attachments,
            session_attachments=session_attachments,
            skill_loader=self.skill_loader,
            workspace=self.workspace,
        )

        try:
            reply = await agent_loop(
                client=self.client,
                model=self.model,
                messages=messages,
                tools=runtime_tools,
            )
        except Exception as exc:
            reply = f"Error while generating reply: {exc}"

        timestamp = datetime.now().isoformat()
        session.messages.append(
            {
                "role": "user",
                "content": content,
                "timestamp": timestamp,
                "attachments": [item.to_dict() for item in inbound.attachments],
                "media": inbound.media,
                "metadata": inbound.metadata,
            }
        )
        session.messages.append(
            {
                "role": "assistant",
                "content": reply,
                "timestamp": datetime.now().isoformat(),
            }
        )
        self.sessions.save(session)

        await self.bus.publish_outbound(
            OutboundMessage(
                channel=inbound.channel,
                chat_id=inbound.chat_id,
                content=reply,
            )
        )
        preview = reply.splitlines()[0] if reply else ""
        print(
            f"[App] Reply queued for {inbound.channel}/{inbound.chat_id}: "
            f"{preview[:120]}"
        )

    async def inbound_worker(self):
        while True:
            inbound = await self.bus.consume_inbound()
            await self.handle_inbound(inbound)

    async def outbound_worker(self):
        while True:
            outbound = await self.bus.consume_outbound()
            channel = self.channels.get(outbound.channel)
            if channel is None:
                print(f"[Bus] No channel registered for outbound message: {outbound.channel}")
                continue
            try:
                await channel.send(outbound)
            except Exception as exc:
                print(
                    f"[Bus] Outbound send failed via {outbound.channel} "
                    f"to {outbound.chat_id}: {exc}"
                )

    async def run(self, channels: list[BaseChannel]):
        for channel in channels:
            self.register_channel(channel)

        inbound_task = asyncio.create_task(self.inbound_worker(), name="miniagent-inbound")
        outbound_task = asyncio.create_task(self.outbound_worker(), name="miniagent-outbound")
        channel_tasks = [asyncio.create_task(channel.start(), name=f"channel-{channel.name}") for channel in channels]

        try:
            done, pending = await asyncio.wait(channel_tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                exc = task.exception()
                if exc is not None:
                    raise exc
            for task in pending:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        finally:
            for channel in channels:
                try:
                    await channel.stop()
                except Exception as exc:
                    print(f"[Channel] Stop failed for {channel.name}: {exc}")

            inbound_task.cancel()
            outbound_task.cancel()
            await asyncio.gather(inbound_task, outbound_task, return_exceptions=True)


async def run_terminal_app():
    print(f"Mini Agent (workspace: {WORKSPACE})")
    print("输入 exit 退出 | 输入 /new 清空会话\n")
    app = MiniAgentApp()
    cli = CLIChannel(app.bus)
    await app.run([cli])


def build_channels(app: MiniAgentApp, channel_names: list[str]) -> list[BaseChannel]:
    channels: list[BaseChannel] = []
    for name in channel_names:
        channel_name = name.strip().lower()
        if channel_name == "cli":
            channels.append(CLIChannel(app.bus))
        elif channel_name == "qq":
            channels.append(
                QQChannel(
                    app.bus,
                    workspace=app.workspace,
                    attachment_store=app.attachment_store,
                )
            )
        else:
            raise ValueError(f"Unsupported channel: {name}")
    return channels


async def run_selected_channels(channel_names: list[str]):
    app = MiniAgentApp()
    channels = build_channels(app, channel_names)
    print(f"Mini Agent (workspace: {WORKSPACE})")
    print(f"Channels: {', '.join(channel_names)}")
    if "cli" in [name.lower() for name in channel_names]:
        print("输入 exit 退出 | 输入 /new 清空会话\n")
    else:
        print("QQ 服务模式已启动，终端不会接收输入；按 Ctrl+C 退出。\n")
    await app.run(channels)


def parse_channel_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Mini Agent with selected channels.")
    parser.add_argument(
        "--channels",
        default="cli",
        help="Comma-separated channels to enable, e.g. cli or qq or cli,qq",
    )
    return parser.parse_args(argv)
