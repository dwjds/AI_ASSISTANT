from __future__ import annotations

from typing import Any

from ..skills import SkillLoader
from .base import Tool


class RunSkillScriptTool(Tool):
    """统一执行 skill 目录内脚本的工具。"""

    def __init__(self, skill_loader: SkillLoader):
        self.skill_loader = skill_loader

    @property
    def name(self) -> str:
        return "run_skill_script"

    @property
    def description(self) -> str:
        return (
            "Run a Python script from a selected skill's scripts/ directory with path validation, "
            "execution tracing, and captured stdout/stderr. Use the normal tool parameter fields: "
            "skill_name, script_path, arguments, timeout_seconds, and optionally cwd."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "description": "Skill name, such as pdf, docx, xlsx, or weather.",
                },
                "script_path": {
                    "type": "string",
                    "description": "Relative path under the skill directory, such as scripts/recalc.py.",
                },
                "arguments": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Command-line arguments passed to the skill script.",
                },
                "timeout_seconds": {
                    "type": "integer",
                    "description": "Maximum execution time, capped by the runtime.",
                },
                "cwd": {
                    "type": "string",
                    "description": "Optional working directory. Must stay inside the project/workspace.",
                },
            },
            "required": ["skill_name", "script_path"],
        }

    async def execute(
        self,
        skill_name: str,
        script_path: str,
        arguments: list[str] | None = None,
        timeout_seconds: int = 60,
        cwd: str | None = None,
        **kwargs,
    ) -> str:
        try:
            return await self.skill_loader.run_skill_script(
                skill_name=skill_name,
                script_path=script_path,
                arguments=arguments or [],
                timeout_seconds=timeout_seconds,
                cwd=cwd,
            )
        except Exception as exc:
            return f"Error: {exc}"
