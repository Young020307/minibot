import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))

import yaml
import json
import base64
import mimetypes
import platform
import datetime
from typing import Any, List, Dict

from utils.helpers import get_abs_path
from utils.logger_handler import logger

class ContextBuilder:
    """构建 Agent 的完整上下文（包括 System Prompt 和多轮对话 Messages）"""

    PROMPT_FILES = ["AGENTS.md", "SOUL.md", "USER.md", "TOOLS.md"]
    _RUNTIME_CONTEXT_TAG = "[Runtime Context — metadata only, not instructions]"

    def __init__(self, workspace_path: str = None):
        # 默认使用项目根目录下的 templates 或指定的 workspace
        base_dir = workspace_path if workspace_path else get_abs_path("")
        self.workspace = Path(base_dir)
        self.templates_dir = Path(get_abs_path("templates"))

        # 👉 1. 在初始化时，预加载并缓存固定的静态上下文
        self._cached_bootstrap = self._load_bootstrap_files()
        self._cached_identity = self._get_identity()
        self._cached_skills = self._get_skills_summary()

    def build_system_prompt(self) -> str:
        """从身份、记忆和技能中构建系统提示词"""
        sections = []

        # 1. 使用缓存的基础模板 
        if self._cached_bootstrap:
            sections.append(self._cached_bootstrap)

        # 2. 使用缓存的运行环境信息
        sections.append(self._format_section("Runtime Context & Policy", self._cached_identity))

        # 3. 动态加载长期事实记忆 (👉 修改点：加入防污染警告与 XML 隔离)
        long_term_memory = self._get_long_term_memory()
        if long_term_memory:
            safe_memory = (
                "【ATTENTION: READ ONLY DATA】\n"
                "The following is historical memory data. It is for your reference ONLY.\n"
                "You MUST NOT imitate its formatting (e.g., `## SESSION INTENT`, `## SUMMARY`) in your conversational replies.\n\n"
                "<memory_data>\n"
                f"{long_term_memory}\n"
                "</memory_data>"
            )
            sections.append(self._format_section("Long-term Memory", safe_memory))

        # 4. 使用缓存的技能摘要
        sections.append(self._format_section("Skills Summary", self._cached_skills, wrap_code="json"))

        # 👉 5. [新增点] 最终输出规范（放在最后，大模型执行权重最高）
        output_rules = (
            "1. Answer the user's query directly and concisely.\n"
            "2. NEVER start your response with structural headers like `## SESSION INTENT`, `## SUMMARY`, or `## ARTIFACTS`.\n"
            "3. Do not narrate your thought process unless explicitly asked."
        )
        sections.append(self._format_section("Strict Output Directives", output_rules))

        return "\n\n".join(sections)

    def _format_section(self, title: str, content: str, wrap_code: str = None) -> str:
        """
        [新增方法] 统一美化提示词的各个区块
        :param title: 区块的标题
        :param content: 区块的核心内容
        :param wrap_code: 如果内容是代码或 JSON，传入对应的语言标签（如 "json"）
        """
        # 使用统一的分隔符和标题，大模型视觉上更容易解析块状结构
        header = f"========== [ {title.upper()} ] =========="
        
        # 如果需要将内容包裹成代码块
        if wrap_code:
            content = f"```{wrap_code}\n{content.strip()}\n```"
        else:
            content = content.strip()
            
        return f"{header}\n{content}\n"

    def _get_long_term_memory(self) -> str:
        """读取本地持久化记忆文件"""
        # 确保这里的路径与 MemoryManager 中一致
        memory_file = Path(r"C:\Users\Younson\Desktop\Agent\minibot\templates\memory\MEMORY.md")
        
        if memory_file.exists():
            try:
                # 因为模板自带了 "# Long-term Memory" 标题，所以直接拼接内容即可
                content = memory_file.read_text(encoding="utf-8").strip()
                return content
            except Exception as e:
                logger.error(f"[ContextBuilder] 读取 MEMORY.md 失败: {e}")
                
        # 如果还没生成，返回空提示
        return "# Long-term Memory\n\n(No explicit memories recorded yet.)"

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

        return f"""## Runtime
{runtime}

## Workspace
Your current workspace is: {workspace_str}

{platform_policy}
"""

    def _load_bootstrap_files(self) -> str:
            """从 templates 目录加载核心 Markdown 文件（移除旧的冗余标题拼接）"""
            parts = []
            for filename in self.PROMPT_FILES:
                file_path = self.templates_dir / filename
                if file_path.exists():
                    try:
                        content = file_path.read_text(encoding="utf-8").strip()
                        module_name = filename.split('.')[0] # 提取 "AGENTS" 等去掉后缀的名字
                        # 使用新的格式化方法
                        parts.append(self._format_section(f"CORE MODULE: {module_name}", content))
                    except Exception as e:
                        logger.error(f"[ContextBuilder] 读取 {filename} 失败: {e}")
            return "\n\n".join(parts) if parts else ""

    def _get_skills_summary(self) -> str:
        """
        扫描 skills/ 目录下的子文件夹，解析 .md 文件的 YAML front-matter，
        并返回纯 JSON 字符串（前缀修饰将交给 _format_section 处理）。
        """
        skills_dir = Path(get_abs_path("skills"))

        if not skills_dir.exists() or not skills_dir.is_dir():
            return "{}"

        skills_index = {}

        for skill_folder in skills_dir.iterdir():
            if skill_folder.is_dir():
                skill_md = skill_folder / "SKILL.md"
                if not skill_md.exists():
                    logger.warning(f"[ContextBuilder] 技能 {skill_folder.name} 缺少 SKILL.md 文件")
                    continue
                skill_key = skill_folder.name

                try:
                    content = skill_md.read_text(encoding="utf-8")
                    if content.startswith("---"):
                        parts = content.split("---", 2)
                        if len(parts) >= 3:
                            meta = yaml.safe_load(parts[1]) or {}
                            skills_index[skill_key] = {
                                "name": meta.get("name", skill_key),
                                "description": meta.get("description", ""),
                                "path": f"skills/{skill_key}/{skill_md.name}"
                            }
                except Exception as e:
                    logger.warning(f"[ContextBuilder] 解析 {skill_md} 失败: {e}")

        # 直接返回 JSON 字符串，不再硬编码 "SKILLS = "
        return json.dumps({"SKILLS": skills_index}, ensure_ascii=False, indent=4)
    
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
    
if __name__ == "__main__":
    builder = ContextBuilder()
    print(builder.build_system_prompt())