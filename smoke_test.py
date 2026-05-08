from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import miniagent
from miniagent_core.attachments import Attachment, AttachmentStore
from miniagent_core.app import MiniAgentApp, build_default_tools
from miniagent_core.async_compat import run_blocking
from miniagent_core.channels import CLIChannel, QQChannel
from miniagent_core.config import CHANNELS, MEMORY_CONSOLIDATE_TRIGGER, MODEL, QQ_CHANNEL, WORKSPACE, client
from miniagent_core.memory import (
    ContextBuilder,
    MemoryStore,
    Session,
    SessionManager,
    _build_memory_item,
    consolidate_memory,
)
from miniagent_core.message import InboundMessage, MessageBus, OutboundMessage
from miniagent_core.skills import SkillLoader
from miniagent_core.tools import (
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


class SmokeTestFailure(RuntimeError):
    pass


def check(condition: bool, message: str):
    if not condition:
        raise SmokeTestFailure(message)
    print(f"[PASS] {message}")


def info(message: str):
    print(f"[INFO] {message}")


async def test_tools(workspace: Path):
    print("\n[TOOLS]")
    registry = ToolRegistry()
    registry.register(ExecTool())
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())
    registry.register(FindFilesTool())
    registry.register(SearchCodeTool())
    registry.register(WebSearchTool())
    registry.register(WebFetchTool())
    registry.register(BrowserAutomationTool())
    skill_dir = workspace / "skills" / "tool_skill"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: tool_skill\ndescription: tool skill\n---\n# Tool Skill\n",
        encoding="utf-8",
    )
    script_dir = skill_dir / "scripts"
    script_dir.mkdir(parents=True, exist_ok=True)
    (script_dir / "hello.py").write_text(
        "import sys\nprint('skill hello ' + ' '.join(sys.argv[1:]))\n",
        encoding="utf-8",
    )
    registry.register(RunSkillScriptTool(SkillLoader(workspace)))
    store = AttachmentStore(workspace)

    blocked = await registry.execute("exec", {"command": "rm -rf /"})
    check("not allowed" in blocked.lower(), "ExecTool blocks dangerous commands")

    out = await registry.execute("exec", {"command": "echo smoke-tools"})
    if out.startswith("Error:"):
        info(f"ExecTool basic command is unavailable in this Python runtime: {out}")
    else:
        check("smoke-tools" in out.lower(), "ExecTool can execute a basic shell command")

    sample = workspace / "sample.txt"
    write_result = await registry.execute("write_file", {"path": str(sample), "content": "hello"})
    check("Wrote" in write_result, "WriteFileTool can write a file")

    read_result = await registry.execute("read_file", {"path": str(sample)})
    check(read_result == "hello", "ReadFileTool can read the written file")

    find_result = await registry.execute("find_files", {"pattern": "app.py", "root": "."})
    check("miniagent_core/app.py" in find_result.replace("\\", "/"), "FindFilesTool can locate files across the project")

    search_result = await registry.execute(
        "search_code",
        {"pattern": "class MiniAgentApp", "root": ".", "glob": "*.py"},
    )
    check("miniagent_core/app.py" in search_result.replace("\\", "/"), "SearchCodeTool can find code content across the project")

    uploaded = store.save_inbound_bytes(
        channel="qq",
        sender_id="openid-1",
        message_id="msg-1",
        filename="note.txt",
        content="hello upload".encode("utf-8"),
        content_type="text/plain",
    )
    registry.register(ListUploadedFilesTool([uploaded]))
    registry.register(ReadUploadedFileTool(store, [uploaded]))
    registry.register(SaveOutboxFileTool(store, "qq:private:openid-1"))
    registry.register(ListOutboxFilesTool(store, "qq:private:openid-1"))

    uploaded_list = await registry.execute("list_uploaded_files", {})
    check("note.txt" in uploaded_list, "Attachment tools can list uploaded files")
    check(
        Path(uploaded.path).parent.name.startswith("note"),
        "Attachment inbox directory names are based on the uploaded filename",
    )

    uploaded_text = await registry.execute("read_uploaded_file", {"filename": "note.txt"})
    check("hello upload" in uploaded_text, "Attachment tools can read uploaded file text")

    suffixless_pdf = store.save_inbound_bytes(
        channel="qq",
        sender_id="openid-1",
        message_id="msg-pdf",
        filename="pdf",
        content=b"%PDF-1.7\n%test\n",
        content_type="application/octet-stream",
    )
    check(suffixless_pdf.name.endswith(".pdf"), "Attachment store can infer PDF extension from file signature")

    save_result = await registry.execute(
        "save_outbox_file",
        {"filename": "result.md", "content": "# done"},
    )
    check("workspace/outbox" in save_result.replace("\\", "/"), "Attachment tools can save generated files to outbox")
    saved_outbox = store.list_session_outbox("qq:private:openid-1")[0]
    check(
        Path(saved_outbox.path).parent.name.startswith("result"),
        "Attachment outbox directory names are based on the output filename",
    )

    outbox_list = await registry.execute("list_outbox_files", {})
    check("result.md" in outbox_list, "Attachment tools can list generated outbox files")

    docx_result = await registry.execute(
        "save_outbox_file",
        {"filename": "report.docx", "title": "Report", "content": "Line 1"},
    )
    if docx_result.startswith("Error:"):
        check("python-docx" in docx_result, "DOCX export explains missing python-docx dependency clearly")
    else:
        check("report.docx" in docx_result, "Attachment tools can export DOCX files")

    pdf_result = await registry.execute(
        "save_outbox_file",
        {"filename": "report.pdf", "title": "Report", "content": "Line 1"},
    )
    if pdf_result.startswith("Error:"):
        check("reportlab" in pdf_result, "PDF export explains missing reportlab dependency clearly")
    else:
        check("report.pdf" in pdf_result, "Attachment tools can export PDF files")

    xlsx_result = await registry.execute(
        "save_outbox_file",
        {
            "filename": "metrics.xlsx",
            "title": "Metrics",
            "table_json": json.dumps(
                {"headers": ["metric", "value"], "rows": [["hr@5", 0.91]]},
                ensure_ascii=False,
            ),
        },
    )
    if xlsx_result.startswith("Error:"):
        check("openpyxl" in xlsx_result, "XLSX export explains missing openpyxl dependency clearly")
    else:
        check("metrics.xlsx" in xlsx_result, "Attachment tools can export XLSX files")

    import miniagent_core.tools.web as web_module

    original_http_get = web_module._http_get

    def fake_search_http_get(url: str, timeout: int = 15):
        return web_module._HttpResponse(
            url=url,
            content_type="text/html; charset=utf-8",
            text=(
                '<html><body>'
                '<a class="result__a" href="https://example.com/a">Example A</a>'
                '<div class="result__snippet">Alpha snippet</div>'
                '<a class="result__a" href="https://example.com/b">Example B</a>'
                '<div class="result__snippet">Beta snippet</div>'
                "</body></html>"
            ),
        )

    def fake_fetch_http_get(url: str, timeout: int = 15):
        return web_module._HttpResponse(
            url=url,
            content_type="text/html; charset=utf-8",
            text=(
                "<html><head><title>Example Page</title></head>"
                "<body><main>Hello <b>world</b>.</main></body></html>"
            ),
        )

    try:
        web_module._http_get = fake_search_http_get
        web_search_result = await registry.execute("web_search", {"query": "example query", "max_results": 2})
        check("Example A" in web_search_result and "Example B" in web_search_result, "WebSearchTool can format parsed search results")

        web_module._http_get = fake_fetch_http_get
        web_fetch_result = await registry.execute("web_fetch", {"url": "https://example.com"})
        check("Example Page" in web_fetch_result and "Hello world." in web_fetch_result, "WebFetchTool can extract readable page text")
    finally:
        web_module._http_get = original_http_get

    browser_result = await registry.execute("browser_automation", {"action": "launch"})
    if browser_result.startswith("Error:"):
        check("playwright" in browser_result.lower(), "BrowserAutomationTool explains missing playwright dependency clearly")
    else:
        check("launched" in browser_result.lower(), "BrowserAutomationTool can launch a browser session")
        close_result = await registry.execute("browser_automation", {"action": "close"})
        check("closed" in close_result.lower(), "BrowserAutomationTool can close a browser session")

    skill_script_result = await registry.execute(
        "run_skill_script",
        {"skill_name": "tool_skill", "script_path": "scripts/hello.py", "arguments": ["ok"]},
    )
    check("skill hello ok" in skill_script_result, "RunSkillScriptTool can execute a script inside a skill scripts directory")
    blocked_skill_script = await registry.execute(
        "run_skill_script",
        {"skill_name": "tool_skill", "script_path": "../outside.py"},
    )
    check("Error:" in blocked_skill_script, "RunSkillScriptTool blocks paths outside the skill scripts directory")


def test_memory(workspace: Path):
    print("\n[MEMORY]")
    session_manager = SessionManager(workspace)
    session = session_manager.get_or_create("cli:test")
    session.messages.append({"role": "user", "content": "你好"})
    session.messages.append({"role": "assistant", "content": "你好，我在"})
    session_manager.save(session)

    reloaded = session_manager.get_or_create("cli:test")
    check(len(reloaded.messages) == 2, "SessionManager can persist session messages")
    check(reloaded.get_history()[0]["role"] == "user", "Session history starts from the latest user message")

    memory = MemoryStore(workspace)
    memory.write_memory("喜欢 Python")
    memory.append_history("测试摘要")
    check("喜欢 Python" in memory.read_memory(), "MemoryStore can read and write long-term memory")
    check(memory.history_file.exists(), "MemoryStore can append history logs")

    (workspace / "AGENTS.md").write_text("system hints", encoding="utf-8")
    skill_dir = workspace / "skills" / "test_skill"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "description: test skill\n"
        "triggers:\n"
        "- 测试\n"
        "---\n"
        "# Test Skill\n"
        "When asked, use this skill.\n",
        encoding="utf-8",
    )
    (skill_dir / "reference.md").write_text(
        "# Reference\n\nExtra reference guidance.\n",
        encoding="utf-8",
    )
    (skill_dir / "forms.md").write_text(
        "# Forms\n\nForm handling notes.\n",
        encoding="utf-8",
    )
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    (scripts_dir / "helper.py").write_text("print('ok')\n", encoding="utf-8")
    xlsx_skill_dir = workspace / "skills" / "xlsx"
    xlsx_skill_dir.mkdir(parents=True, exist_ok=True)
    (xlsx_skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: xlsx\n"
        "description: spreadsheet skill\n"
        "triggers:\n"
        "- xlsx\n"
        "---\n"
        "# XLSX Skill\n"
        "Use this skill for spreadsheet work.\n",
        encoding="utf-8",
    )
    xlsx_scripts_dir = xlsx_skill_dir / "scripts"
    xlsx_scripts_dir.mkdir(parents=True, exist_ok=True)
    (xlsx_scripts_dir / "recalc.py").write_text("print('{}')\n", encoding="utf-8")
    builder = ContextBuilder(workspace, skill_loader=SkillLoader(workspace))
    runtime_note = builder.skill_loader.build_runtime_note(
        "请测试这个 skill 并在需要时执行脚本",
        outbox_dir=workspace / "outbox" / "cli__test",
    )
    xlsx_runtime_note = builder.skill_loader.build_runtime_note(
        "请处理 xlsx 并检查公式",
        outbox_dir=workspace / "outbox" / "cli__xlsx",
    )
    attachment_driven_prompt = builder.build_system_prompt(
        "请继续处理这个文件",
        attachments=[Attachment(name="report.xlsx", path=str(workspace / "report.xlsx"), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")],
    )
    attachment_driven_runtime_note = builder.skill_loader.build_runtime_note(
        "请继续处理这个文件",
        outbox_dir=workspace / "outbox" / "cli__xlsx_attachment",
        attachments=[Attachment(name="report.xlsx", path=str(workspace / "report.xlsx"), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")],
    )
    prompt = builder.build_system_prompt()
    triggered_skill_prompt = builder.build_system_prompt("请测试这个 skill")
    non_triggered_skill_prompt = builder.build_system_prompt("完全无关的问题")
    file_prompt = builder.build_system_prompt("请检查 app.py 里的代码问题")
    search_prompt = builder.build_system_prompt("帮我搜索最新官方文档")
    fetch_prompt = builder.build_system_prompt("请读取 https://example.com 的网页正文")
    browser_prompt = builder.build_system_prompt("请打开网页并点击登录按钮后截图")
    hybrid_prompt = builder.build_system_prompt("请先修改 app.py 再打开网页点击提交")
    messages = builder.build_messages(reloaded.get_history(), "请读取 https://example.com 的网页正文")
    generic_messages = builder.build_messages(reloaded.get_history(), "继续")
    attachment_messages = builder.build_messages(
        reloaded.get_history(),
        "帮我看一下这个文件",
        attachments=[Attachment(name="a.txt", path=str(workspace / "a.txt"))],
    )
    messages_with_runtime_note = builder.build_messages(
        reloaded.get_history(),
        "请测试这个 skill 并在需要时执行脚本",
        extra_system_notes=[runtime_note],
    )
    check("system hints" in prompt, "ContextBuilder can inject bootstrap files")
    check("Test Skill" in prompt, "ContextBuilder can inject workspace skill content without user filter")
    check("Test Skill" in triggered_skill_prompt, "ContextBuilder injects triggered skills on demand")
    check("reference.md" in triggered_skill_prompt, "ContextBuilder lists supplemental reference files on demand")
    check("forms.md" in triggered_skill_prompt, "ContextBuilder lists supplemental form files on demand")
    check("Extra reference guidance." not in triggered_skill_prompt, "ContextBuilder does not eagerly inject reference content")
    check("Form handling notes." not in triggered_skill_prompt, "ContextBuilder does not eagerly inject forms content")
    check("只有当前任务确实需要" in triggered_skill_prompt, "ContextBuilder tells the model to lazily read supplemental skill docs")
    check("run_skill_script" in triggered_skill_prompt and "scripts" in triggered_skill_prompt, "ContextBuilder exposes skill script workspace for runtime-based execution")
    check("不要立即查看或执行全部脚本" in triggered_skill_prompt, "ContextBuilder tells the model to lazily inspect skill scripts")
    check("helper.py" not in triggered_skill_prompt, "ContextBuilder does not eagerly list individual skill scripts")
    check("Test Skill" not in non_triggered_skill_prompt, "ContextBuilder skips unrelated skills")
    check("项目根目录" in prompt and "工作区目录" in prompt, "ContextBuilder distinguishes project root and workspace")
    check("Tool Use Policy" not in prompt, "ContextBuilder does not inject tool policy by default")
    check("喜欢 Python" not in prompt, "ContextBuilder no longer eagerly injects MEMORY.md content into every prompt")
    check("必须先调用 `find_files`" in file_prompt, "ContextBuilder injects file-navigation policy on demand")
    check("优先考虑调用 `web_search`" in search_prompt, "ContextBuilder injects web search policy on demand")
    check("优先考虑调用 `web_fetch`" in fetch_prompt, "ContextBuilder injects web fetch policy on demand")
    check("优先考虑调用 `browser_automation`" in browser_prompt, "ContextBuilder injects browser policy on demand")
    check("先用文件工具定位或生成文件" in hybrid_prompt, "ContextBuilder injects hybrid file-browser policy on demand")
    check("工具返回 `Error:`" in fetch_prompt, "ContextBuilder injects grounding policy for tool-backed tasks")
    check("不要编造" in fetch_prompt, "ContextBuilder forbids fabricated tool-backed observations when tools are relevant")
    check(messages[1]["role"] == "system", "ContextBuilder injects a session-history instruction")
    check("不要否认自己看到了会话历史" in messages[1]["content"], "ContextBuilder tells the model to use persisted session history")
    check("优先调用 `web_fetch`" in messages[1]["content"], "ContextBuilder tells the model when to use web fetch")
    check("优先调用 `web_search`" not in messages[1]["content"], "ContextBuilder skips unrelated history policies")
    check("不要默认只给步骤说明" not in messages[1]["content"], "ContextBuilder skips unrelated browser history policies")
    check("不要把推测写成已经验证的事实" in messages[1]["content"], "ContextBuilder tells the model not to present guesses as verified facts")
    check("优先调用 `web_fetch`" not in generic_messages[1]["content"], "ContextBuilder keeps generic history note lean")
    check("默认只给简短摘要和关键结论" in attachment_messages[2]["content"], "ContextBuilder tells the model to summarize uploaded files by default")
    check("当前会话 outbox 目录" in runtime_note, "SkillLoader runtime note includes the current session outbox path")
    check("run_skill_script" in runtime_note, "SkillLoader runtime note requires the unified skill script runner")
    check("不要直接覆盖 workspace/inbox" in runtime_note, "SkillLoader runtime note protects uploaded originals")
    check("recalc.py" in xlsx_runtime_note, "SkillLoader runtime note requires XLSX formula recalculation before delivery")
    check("status=success" in xlsx_runtime_note, "SkillLoader runtime note explains the XLSX delivery gate")
    check("XLSX Skill" in attachment_driven_prompt, "ContextBuilder can trigger XLSX skill from visible attachments")
    check("recalc.py" in attachment_driven_runtime_note, "SkillLoader runtime note can trigger from attachment types alone")
    check(any("当前会话 outbox 目录" in item["content"] for item in messages_with_runtime_note if item["role"] == "system"), "ContextBuilder can include extra runtime system notes")
    check(messages[-1]["role"] == "user", "ContextBuilder can build message list")


async def test_memory_consolidation(workspace: Path):
    print("\n[MEMORY CONSOLIDATION]")

    class FakeMessage:
        def __init__(self, content: str):
            self.content = content

    class FakeChoice:
        def __init__(self, content: str):
            self.message = FakeMessage(content)

    class FakeResponse:
        def __init__(self, content: str):
            self.choices = [FakeChoice(content)]

    class FakeCompletions:
        def create(self, **kwargs):
            return FakeResponse(
                json.dumps(
                    {
                        "history_summary": "summary",
                        "history_topic": "preferences",
                        "history_keywords": ["偏好", "中文"],
                        "memory_markdown": "updated",
                        "memory_items": [
                            {
                                "type": "preference",
                                "topic": "communication_style",
                                "summary": "用户偏好简洁、专业、技术导向的中文表达。",
                                "keywords": ["中文", "简洁", "技术"],
                                "tags": ["user_profile", "style"],
                                "confidence": 0.95,
                            }
                        ],
                    },
                    ensure_ascii=False,
                )
            )

    class FakeEmbeddingData:
        def __init__(self, embedding):
            self.embedding = embedding

    class FakeEmbeddingResponse:
        def __init__(self, embedding):
            self.data = [FakeEmbeddingData(embedding)]

    class FakeEmbeddings:
        def create(self, model, input):
            text = str(input or "")
            return FakeEmbeddingResponse(
                [
                    1.0 if any(token in text for token in ("偏好", "中文", "技术")) else 0.0,
                    1.0 if any(token in text for token in ("天气", "武汉")) else 0.0,
                ]
            )

    class FakeChat:
        def __init__(self):
            self.completions = FakeCompletions()

    class FakeClient:
        def __init__(self):
            self.chat = FakeChat()
            self.embeddings = FakeEmbeddings()

    memory = MemoryStore(workspace)
    session = Session(key="cli:test")
    session.messages = [{"role": "user", "content": f"m{i}"} for i in range(MEMORY_CONSOLIDATE_TRIGGER)]
    await consolidate_memory(
        client=FakeClient(),
        model=MODEL,
        session=session,
        memory=memory,
        trigger_messages=MEMORY_CONSOLIDATE_TRIGGER,
        keep_recent=15,
        embedding_model="fake-embed",
    )
    check(
        len(session.messages) == MEMORY_CONSOLIDATE_TRIGGER,
        "Memory is not consolidated before exceeding the trigger threshold",
    )

    session.messages.append({"role": "assistant", "content": "extra"})
    await consolidate_memory(
        client=FakeClient(),
        model=MODEL,
        session=session,
        memory=memory,
        trigger_messages=MEMORY_CONSOLIDATE_TRIGGER,
        keep_recent=15,
        embedding_model="fake-embed",
    )
    check(len(session.messages) == 15, "Memory consolidation trims session to keep_recent after crossing trigger")
    trace_lines = [
        json.loads(line)
        for line in memory.trace_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    check(any(item["status"] == "started" for item in trace_lines), "Memory consolidation logs a started trace event")
    check(any(item["status"] == "success" for item in trace_lines), "Memory consolidation logs a success trace event")
    stored_items = memory.read_memory_items()
    check(len(stored_items) == 1, "Memory consolidation writes structured long-term memory items")
    check(
        "用户偏好简洁、专业、技术导向的中文表达。" in memory.read_memory() and "updated" not in memory.read_memory(),
        "MEMORY.md is regenerated as a human-readable overview from structured memory items",
    )
    relevant_note = await memory.build_relevant_memory_note(
        "用户的中文沟通偏好是什么？",
        client=FakeClient(),
        embedding_model="fake-embed",
        top_k=2,
        candidate_pool=4,
    )
    check("用户偏好简洁、专业、技术导向的中文表达" in relevant_note, "Memory retrieval can inject only the most relevant memory snippets")
    memory.upsert_memory_items(
        [
            _build_memory_item(
                timestamp=datetime.now().isoformat(),
                session_key="cli:test",
                item_type="preference",
                topic="communication_style",
                summary="用户偏好非常详细、啰嗦的口语化表达。",
                keywords=["详细", "口语"],
                confidence=0.2,
            ),
            _build_memory_item(
                timestamp=datetime.now().isoformat(),
                session_key="cli:test",
                item_type="workflow",
                topic="temporary_error",
                summary="上一轮工具报错，暂未解决。",
                keywords=["报错", "未解决"],
                confidence=0.4,
            ),
        ]
    )
    stored_items_all = memory.read_memory_items(active_only=False)
    active_style_items = [
        item for item in stored_items_all if item.type == "preference" and item.topic == "communication_style" and item.active
    ]
    check(len(active_style_items) == 1, "Memory store keeps only one active item for conflicting type/topic memories")
    check(
        "简洁、专业、技术导向" in active_style_items[0].summary,
        "Memory store prefers the higher-confidence conflict winner",
    )
    check(
        all(item.topic != "temporary_error" for item in stored_items_all),
        "Memory store filters unresolved transient items from long-term memory",
    )

    class BadJsonCompletions:
        def create(self, **kwargs):
            return FakeResponse("not-json")

    class BadJsonChat:
        def __init__(self):
            self.completions = BadJsonCompletions()

    class BadJsonClient:
        def __init__(self):
            self.chat = BadJsonChat()
            self.embeddings = FakeEmbeddings()

    class FencedJsonCompletions:
        def create(self, **kwargs):
            return FakeResponse(
                '```json\n{"history_summary":"wrapped summary","memory_markdown":"wrapped memory","memory_items":[{"type":"fact","topic":"workflow","summary":"结果文件默认保存到 workspace/outbox。","keywords":["outbox","结果文件"],"confidence":0.9}]}\n```'
            )

    class FencedJsonChat:
        def __init__(self):
            self.completions = FencedJsonCompletions()

    class FencedJsonClient:
        def __init__(self):
            self.chat = FencedJsonChat()
            self.embeddings = FakeEmbeddings()

    bad_session = Session(key="qq:private:test")
    bad_session.messages = [{"role": "user", "content": f"q{i}"} for i in range(MEMORY_CONSOLIDATE_TRIGGER + 1)]
    await consolidate_memory(
        client=BadJsonClient(),
        model=MODEL,
        session=bad_session,
        memory=memory,
        trigger_messages=MEMORY_CONSOLIDATE_TRIGGER,
        keep_recent=15,
        embedding_model="fake-embed",
    )
    check(
        len(bad_session.messages) == MEMORY_CONSOLIDATE_TRIGGER + 1,
        "Memory consolidation keeps session messages intact when JSON parsing fails",
    )
    trace_lines = [
        json.loads(line)
        for line in memory.trace_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    check(
        any(item["status"] == "parse_error" for item in trace_lines),
        "Memory consolidation logs parse failures to consolidation_trace.jsonl",
    )

    fenced_session = Session(key="qq:private:fenced")
    fenced_session.messages = [{"role": "user", "content": f"z{i}"} for i in range(MEMORY_CONSOLIDATE_TRIGGER + 1)]
    await consolidate_memory(
        client=FencedJsonClient(),
        model=MODEL,
        session=fenced_session,
        memory=memory,
        trigger_messages=MEMORY_CONSOLIDATE_TRIGGER,
        keep_recent=15,
        embedding_model="fake-embed",
    )
    check(len(fenced_session.messages) == 15, "Memory consolidation can parse fenced JSON payloads and trim session")
    trace_lines = [
        json.loads(line)
        for line in memory.trace_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    check(
        any(item["status"] == "success" and "parse_mode=fenced_json" in item.get("details", "") for item in trace_lines),
        "Memory consolidation records when JSON was recovered from a fenced payload",
    )


async def test_message_and_channels(workspace: Path):
    print("\n[MESSAGE / CHANNEL]")
    bus = MessageBus()

    inbound = InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="hello")
    await bus.publish_inbound(inbound)
    got_inbound = await bus.consume_inbound()
    check(got_inbound.session_key == "cli:direct", "MessageBus can round-trip inbound messages")

    outbound = OutboundMessage(channel="cli", chat_id="direct", content="world")
    await bus.publish_outbound(outbound)
    got_outbound = await bus.consume_outbound()
    check(got_outbound.content == "world", "MessageBus can round-trip outbound messages")

    cli = CLIChannel(bus)
    await cli.handle_message("user", "direct", "cli test")
    cli_msg = await bus.consume_inbound()
    check(cli_msg.channel == "cli" and cli_msg.content == "cli test", "CLIChannel can publish inbound messages")
    cli._response_event = asyncio.Event()
    await cli.send(OutboundMessage(channel="cli", chat_id="direct", content="ok"))
    check(cli._response_event.is_set(), "CLIChannel send releases the input wait state")

    qq = QQChannel(
        bus,
        config={"appId": "123456", "secret": "secret-value", "allowFrom": ["openid-1"]},
        workspace=workspace,
    )
    check(qq.app_id == "123456" and qq.secret == "secret-value", "QQChannel reads official appId and secret config")
    check("openid-1" in qq.allow_from, "QQChannel loads allowFrom allowlist")

    await qq.handle_message("openid-1", "private:openid-1", "qq inbound", media=["a.png"], metadata={"message_id": "1"})
    qq_msg = await bus.consume_inbound()
    check(qq_msg.media == ["a.png"], "QQChannel can publish inbound media metadata through the bus")
    check(qq_msg.attachments[0].name == "a.png", "QQChannel converts legacy media paths into structured attachments")

    message_type, target_id = qq._parse_chat_id("private:openid-1")
    check(message_type == "private" and target_id == "openid-1", "QQChannel parses private chat ids")
    check(qq._next_seq("openid-1") == 1 and qq._next_seq("openid-1") == 2, "QQChannel maintains message sequence per user")
    check(qq._remember_message_id("m1"), "QQChannel accepts a new inbound message id")
    check(not qq._remember_message_id("m1"), "QQChannel deduplicates repeated inbound message ids")

    try:
        await qq.start()
    except RuntimeError as exc:
        check("botpy" in str(exc).lower(), "QQChannel explains the missing botpy dependency clearly")
    else:
        raise SmokeTestFailure("QQChannel.start() unexpectedly succeeded without botpy")


async def test_app_flow(workspace: Path):
    print("\n[APP]")

    class FakeMessage:
        def __init__(self, content: str):
            self.content = content
            self.tool_calls = []

    class FakeChoice:
        def __init__(self, content: str):
            self.message = FakeMessage(content)

    class FakeResponse:
        def __init__(self, content: str):
            self.choices = [FakeChoice(content)]

    class FakeCompletions:
        def __init__(self):
            self.calls: list[dict] = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            last_user = kwargs["messages"][-1]["content"]
            return FakeResponse(f"fake reply to: {last_user.splitlines()[-1]}")

    class FakeEmbeddingData:
        def __init__(self, embedding):
            self.embedding = embedding

    class FakeEmbeddingResponse:
        def __init__(self, embedding):
            self.data = [FakeEmbeddingData(embedding)]

    class FakeEmbeddings:
        def create(self, model, input):
            text = str(input or "")
            return FakeEmbeddingResponse(
                [
                    1.0 if any(token in text for token in ("偏好", "中文", "技术")) else 0.0,
                    1.0 if any(token in text for token in ("天气", "武汉")) else 0.0,
                ]
            )

    class FakeChat:
        def __init__(self):
            self.completions = FakeCompletions()

    class FakeClient:
        def __init__(self):
            self.chat = FakeChat()
            self.embeddings = FakeEmbeddings()

    fake_client = FakeClient()
    app = MiniAgentApp(workspace=workspace, llm_client=fake_client)
    app.memory.upsert_memory_items(
        [
            _build_memory_item(
                timestamp=datetime.now().isoformat(),
                session_key="cli:direct",
                item_type="preference",
                topic="communication_style",
                summary="用户偏好简洁、专业、技术导向的中文表达。",
                keywords=["中文", "简洁", "技术"],
                confidence=0.95,
                embedding=[1.0, 0.0],
            )
        ]
    )
    inbound = InboundMessage(
        channel="cli",
        sender_id="u1",
        chat_id="direct",
        content="请按我的中文技术偏好简洁回答，测试 app",
    )
    await app.handle_inbound(inbound)
    outbound = await app.bus.consume_outbound()
    check(outbound.channel == "cli", "MiniAgentApp publishes replies to the same channel")
    check("fake reply to" in outbound.content, "MiniAgentApp can generate and publish a reply")
    app_messages = fake_client.chat.completions.calls[-1]["messages"]
    relevant_memory_notes = [
        item["content"]
        for item in app_messages
        if item.get("role") == "system" and "# Relevant Memory" in item.get("content", "")
    ]
    check(relevant_memory_notes, "MiniAgentApp injects retrieved relevant memory snippets into prompt context")
    check(
        "用户偏好简洁、专业、技术导向的中文表达。" in relevant_memory_notes[0],
        "MiniAgentApp injects only the retrieved relevant memory summary instead of the full MEMORY.md body",
    )

    attachment = Attachment(
        name="upload.txt",
        path=str(workspace / "inbox" / "upload.txt"),
        content_type="text/plain",
        size=6,
    )
    Path(attachment.path).parent.mkdir(parents=True, exist_ok=True)
    Path(attachment.path).write_text("sample", encoding="utf-8")
    inbound_with_file = InboundMessage(
        channel="cli",
        sender_id="u1",
        chat_id="direct",
        content="请处理上传文件",
        attachments=[attachment],
    )
    await app.handle_inbound(inbound_with_file)
    outbound_with_file = await app.bus.consume_outbound()
    check(bool(outbound_with_file.content.strip()), "MiniAgentApp can handle inbound attachments without breaking reply flow")

    attachment_only = Attachment(
        name="only_upload.docx",
        path=str(workspace / "inbox" / "only_upload.docx"),
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        size=7,
    )
    Path(attachment_only.path).parent.mkdir(parents=True, exist_ok=True)
    Path(attachment_only.path).write_bytes(b"sample")
    prior_llm_calls = len(fake_client.chat.completions.calls)
    inbound_attachment_only = InboundMessage(
        channel="cli",
        sender_id="u1",
        chat_id="direct",
        content="",
        attachments=[attachment_only],
    )
    await app.handle_inbound(inbound_attachment_only)
    outbound_attachment_only = await app.bus.consume_outbound()
    check(
        "已收到您上传的文件" in outbound_attachment_only.content,
        "MiniAgentApp acknowledges attachment-only messages without processing them",
    )
    check(
        len(fake_client.chat.completions.calls) == prior_llm_calls,
        "MiniAgentApp does not call the LLM for attachment-only messages",
    )
    attachment_history = app.sessions.get_or_create("cli:direct").messages
    check(
        any(
            item.get("role") == "user"
            and any(att.get("name") == "only_upload.docx" for att in item.get("attachments", []))
            for item in attachment_history
        ),
        "MiniAgentApp still records attachment-only uploads for later turns",
    )

    prior_session = app.sessions.get_or_create("cli:direct")
    attachment_from_history = Attachment(
        name="history.txt",
        path=str(workspace / "inbox" / "history.txt"),
        content_type="text/plain",
        size=7,
    )
    Path(attachment_from_history.path).parent.mkdir(parents=True, exist_ok=True)
    Path(attachment_from_history.path).write_text("persist", encoding="utf-8")
    prior_session.messages.append(
        {
            "role": "user",
            "content": "",
            "attachments": [attachment_from_history.to_dict()],
            "media": [attachment_from_history.path],
            "metadata": {"message_id": "m-history"},
        }
    )
    app.sessions.save(prior_session)

    runtime_tools = build_default_tools(
        attachment_store=app.attachment_store,
        session_key="cli:direct",
        inbound_attachments=[],
        session_attachments=app.attachment_store.collect_session_attachments(prior_session.messages),
    )
    history_list = await runtime_tools.execute("list_uploaded_files", {})
    check("history.txt" in history_list, "Runtime tools can surface session attachments from earlier turns")
    history_read = await runtime_tools.execute("read_uploaded_file", {"filename": "history.txt"})
    check("persist" in history_read, "Runtime tools can read session attachments from earlier turns")


def test_skills(workspace: Path):
    print("\n[SKILLS]")
    skill_dir = workspace / "skills" / "demo_skill"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "description: demo skill description\n"
        "---\n"
        "# Demo\n",
        encoding="utf-8",
    )

    weather_dir = workspace / "skills" / "weather"
    weather_dir.mkdir(parents=True, exist_ok=True)
    (weather_dir / "SKILL.md").write_text(
        "---\n"
        "name: weather\n"
        "description: weather skill\n"
        "triggers:\n"
        "- 天气\n"
        "- 温度\n"
        "---\n"
        "# Weather\n",
        encoding="utf-8",
    )

    builtin_dir = workspace / "builtin_skills" / "builtin_one"
    builtin_dir.mkdir(parents=True, exist_ok=True)
    (builtin_dir / "SKILL.md").write_text(
        "---\n"
        "description: builtin skill\n"
        "---\n"
        "# Builtin\n",
        encoding="utf-8",
    )

    loader = SkillLoader(workspace, builtin_dir=workspace / "builtin_skills")
    skills = loader.list_skills()
    names = {skill["name"] for skill in skills}
    check(
        {"demo_skill", "builtin_one", "weather"}.issubset(names),
        "SkillLoader can discover workspace and builtin skills",
    )
    weather_prompt = loader.build_prompt_section("今天天气怎么样")
    check("## weather" in weather_prompt, "SkillRouter can trigger weather skill from Chinese weather questions")

    docx_dir = workspace / "skills" / "docx"
    docx_dir.mkdir(parents=True, exist_ok=True)
    (docx_dir / "SKILL.md").write_text(
        "---\n"
        "name: docx\n"
        "description: docx skill\n"
        "triggers:\n"
        "- Word文档\n"
        "- docx\n"
        "---\n"
        "# DOCX\n",
        encoding="utf-8",
    )
    pdf_dir = workspace / "skills" / "pdf"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    (pdf_dir / "SKILL.md").write_text(
        "---\n"
        "name: pdf\n"
        "description: pdf skill\n"
        "triggers:\n"
        "- PDF文件\n"
        "- pdf\n"
        "---\n"
        "# PDF\n",
        encoding="utf-8",
    )
    xlsx_dir = workspace / "skills" / "xlsx"
    xlsx_dir.mkdir(parents=True, exist_ok=True)
    (xlsx_dir / "SKILL.md").write_text(
        "---\n"
        "name: xlsx\n"
        "description: xlsx skill\n"
        "triggers:\n"
        "- Excel表格\n"
        "- 表格\n"
        "- 重算\n"
        "---\n"
        "# XLSX\n",
        encoding="utf-8",
    )

    loader = SkillLoader(workspace, builtin_dir=workspace / "builtin_skills")
    docx_prompt = loader.build_prompt_section("帮我生成一个Word文档")
    pdf_prompt = loader.build_prompt_section("总结这个PDF文件")
    xlsx_prompt = loader.build_prompt_section("给这个表格新增公式并重算")
    check("## docx" in docx_prompt, "SkillRouter can trigger docx skill from Chinese Word document requests")
    check("## pdf" in pdf_prompt, "SkillRouter can trigger pdf skill from Chinese PDF requests")
    check("## xlsx" in xlsx_prompt, "SkillRouter can trigger xlsx skill from Chinese spreadsheet requests")


async def test_llm():
    print("\n[LLM]")
    if client is None:
        info("LLM test skipped: openai client is unavailable in this Python environment")
        return

    def _call_llm() -> str:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "You are a concise assistant."},
                {"role": "user", "content": "请只回复：smoke test ok"},
            ],
            temperature=0,
        )
        return (resp.choices[0].message.content or "").strip()

    try:
        reply = await run_blocking(_call_llm)
    except Exception as exc:
        raise SmokeTestFailure(f"LLM call failed: {exc}") from exc

    check(bool(reply), "LLM can return a non-empty reply")
    info(f"LLM reply: {reply}")


def test_exports():
    print("\n[EXPORTS]")
    info(f"python executable: {sys.executable}")
    check(hasattr(miniagent, "QQChannel"), "Top-level miniagent exports QQChannel")
    check(hasattr(miniagent, "ToolRegistry"), "Top-level miniagent exports ToolRegistry")
    check(hasattr(miniagent, "BrowserAutomationTool"), "Top-level miniagent exports BrowserAutomationTool")
    check(MODEL.startswith("qwen-plus"), "Config constants are importable")
    check("qq" in CHANNELS and QQ_CHANNEL is CHANNELS["qq"], "QQ channel config is exported in channels.qq style")
    print(f"[INFO] openai client available: {client is not None}")
    print(f"[INFO] workspace path: {WORKSPACE}")


async def main():
    print("MiniAgent smoke test starting...")
    test_exports()

    with tempfile.TemporaryDirectory(prefix="miniagent_smoke_") as tmp:
        workspace = Path(tmp)
        await test_tools(workspace)
        test_memory(workspace)
        await test_memory_consolidation(workspace)
        await test_message_and_channels(workspace)
        await test_app_flow(workspace)
        test_skills(workspace)
        await test_llm()

    print("\nAll smoke tests passed.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except SmokeTestFailure as exc:
        print(f"\n[FAIL] {exc}")
        raise SystemExit(1)
