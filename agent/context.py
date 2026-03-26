import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

import base64
import mimetypes
import platform
import datetime
from pathlib import Path
from typing import Any, List, Dict

from utils.path_tool import get_abs_path
from utils.logger_handler import logger
from agent.tools.registry import build_skills_context, _scan_skills

class ContextBuilder:
    """构建 Agent 的完整上下文（包括 System Prompt 和多轮对话 Messages）"""

    BOOTSTRAP_FILES = ["AGENTS.md", "SOUL.md", "USER.md", "TOOLS.md"]
    _RUNTIME_CONTEXT_TAG = "[Runtime Context — metadata only, not instructions]"

    def __init__(self, workspace_path: str = None):
        # 默认使用项目根目录下的 templates 或指定的 workspace
        base_dir = workspace_path if workspace_path else get_abs_path("")
        self.workspace = Path(base_dir)
        self.templates_dir = Path(get_abs_path("templates"))

    def build_system_prompt(self) -> str:
        """从身份、核心文件、记忆和技能中构建系统提示词"""
        parts = [self._get_identity()]

        # 1. 加载基础模板 (SOUL, AGENTS, etc.)
        bootstrap = self._load_bootstrap_files()
        if bootstrap:
            parts.append(bootstrap)

        # 2. 注入常驻技能 (always: true)
        always_content = build_skills_context()
        if always_content:
            parts.append(f"# Active Skills\n\n{always_content}")

        # 3. 注入技能摘要索引 (动态发现层)
        skills_summary = self._build_skills_summary()
        if skills_summary:
            parts.append(f"""# Skills Summary

The following skills extend your capabilities. To use a skill, call the list_skills tool or read its SKILL.md.

{skills_summary}""")

        return "\n\n---\n\n".join(parts)

    def _get_identity(self) -> str:
        """获取核心身份和跨平台策略"""
        workspace_str = str(self.workspace.expanduser().resolve())
        system = platform.system()
        runtime = f"{'macOS' if system == 'Darwin' else system} {platform.machine()}, Python {platform.python_version()}"

        # 跨平台策略：防止 AI 在 Windows 上乱用 grep 或 rm -rf
        if system == "Windows":
            platform_policy = """## Platform Policy (Windows)
- You are running on Windows. Do not assume GNU tools like `grep`, `sed`, or `awk` exist.
- Prefer Windows-native PowerShell commands.
- If terminal output is garbled, retry with UTF-8 output enabled."""
        else:
            platform_policy = """## Platform Policy (POSIX)
- You are running on a POSIX system. Prefer UTF-8 and standard shell tools.
- Use standard bash commands for file operations when appropriate."""

        return f"""# AI Assistant

You are a highly capable AI assistant.

## Runtime
{runtime}

## Workspace
Your current workspace is: {workspace_str}

{platform_policy}

## Guidelines
- State intent before tool calls, but NEVER predict results before receiving them.
- Before modifying a file, read it first. Do not assume files exist.
- If a tool call fails, analyze the error before retrying.
- Reply directly with text for conversations.
"""

    def _load_bootstrap_files(self) -> str:
        """从 templates 目录加载核心 Markdown 文件"""
        parts = []
        for filename in self.BOOTSTRAP_FILES:
            file_path = self.templates_dir / filename
            if file_path.exists():
                try:
                    content = file_path.read_text(encoding="utf-8").strip()
                    parts.append(f"## {filename}\n\n{content}")
                except Exception as e:
                    logger.error(f"[ContextBuilder] 读取 {filename} 失败: {e}")
        return "\n\n".join(parts) if parts else ""

    def _build_skills_summary(self) -> str:
        """构建技能列表的简要索引，防止 Prompt 过长"""
        skills = _scan_skills()
        if not skills:
            return ""
        # 仅展示未被 always 加载的技能索引
        summary_lines = [
            f"- **{s['name']}**: {s['description']}" 
            for s in skills if not s.get("always")
        ]
        return "\n".join(summary_lines)

    @staticmethod
    def _get_current_time_str() -> str:
        now = datetime.datetime.now()
        return now.strftime("%A, %B %d, %Y at %I:%M:%S %p")

    def build_messages(
        self,
        history: List[Dict[str, Any]],
        current_message: str,
        media: List[str] = None,
        current_role: str = "user",
    ) -> List[Dict[str, Any]]:
        """构建传递给 LLM 的完整消息体，包含运行时元数据和多模态图像"""
        
        # 构建运行时时间戳
        runtime_ctx = (
            f"{self._RUNTIME_CONTEXT_TAG}\n"
            f"Current Time: {self._get_current_time_str()}"
        )

        # 处理用户输入内容（文本 + 可能存在的图片编码）
        user_content = self._build_user_content(current_message, media)

        # 融合 Runtime 和 User Content，防止大模型 API 拒绝连续的 User 角色消息
        if isinstance(user_content, str):
            merged_content = f"{runtime_ctx}\n\n{user_content}"
        else:
            merged_content = [{"type": "text", "text": runtime_ctx + "\n\n"}] + user_content

        # 组装最终的消息数组
        return [
            {"role": "system", "content": self.build_system_prompt()},
            *history,
            {"role": current_role, "content": merged_content},
        ]

    def _build_user_content(self, text: str, media: List[str]) -> Any:
        """处理文本及图片的 Base64 编码，适配 GPT-4V/Claude 3 等视觉模型"""
        if not media:
            return text

        content_parts = []
        for path in media:
            p = Path(path)
            if not p.is_file():
                continue
            try:
                raw = p.read_bytes()
                # 简单推测 MIME 类型
                mime = mimetypes.guess_type(path)[0] or "image/jpeg"
                if not mime.startswith("image/"):
                    continue
                
                b64 = base64.b64encode(raw).decode("utf-8")
                content_parts.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64}"}
                })
            except Exception as e:
                logger.warning(f"[ContextBuilder] 读取图片 {path} 失败: {e}")

        if not content_parts:
            return text
            
        content_parts.append({"type": "text", "text": text})
        return content_parts