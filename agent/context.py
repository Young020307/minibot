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

    def build_system_prompt(self) -> str:
        """从身份、记忆和技能中构建系统提示词"""
        system_prompt = []

        # 1. 加载基础模板 (SOUL, AGENTS, etc.)
        bootstrap = self._load_bootstrap_files()
        if bootstrap:
            system_prompt.append(bootstrap)

        # 2. 加载运行环境信息：系统类型、架构、Python 版本
        system_prompt.append(self._get_identity())

        # 3. 加载长期事实记忆(MEMORY.md)
        long_term_memory = self._get_long_term_memory()
        if long_term_memory:
            system_prompt.append(long_term_memory)

        # 4. 注入技能摘要索引
        skills_summary = self._get_skills_summary()
        if skills_summary:
            system_prompt.append(skills_summary)
            
        return "\n\n---\n\n".join(system_prompt)

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
        """从 templates 目录加载核心 Markdown 文件"""
        parts = []
        for filename in self.PROMPT_FILES:
            file_path = self.templates_dir / filename
            if file_path.exists():
                try:
                    content = file_path.read_text(encoding="utf-8").strip()
                    parts.append(f"## {filename}\n\n{content}")
                except Exception as e:
                    logger.error(f"[ContextBuilder] 读取 {filename} 失败: {e}")
        return "\n\n".join(parts) if parts else ""

    def _get_skills_summary(self) -> str:
        """
        扫描 skills/ 目录下的子文件夹，解析 .md 文件的 YAML front-matter，
        并返回格式化的 JSON 索引字符串。
        """
        skills_dir = Path(get_abs_path("skills"))

        if not skills_dir.exists() or not skills_dir.is_dir():
            return "SKILLS = {}"

        skills_index = {}

        # 遍历 skills 下的每一个子目录
        for skill_folder in skills_dir.iterdir():
            if skill_folder.is_dir():
                # 👇 直接定位这个目录下的 SKILL.md 文件
                skill_md = skill_folder / "SKILL.md"
                # 👇 检查文件是否存在，不存在就跳过
                if not skill_md.exists():
                    logger.warning(f"[ContextBuilder] 技能 {skill_folder.name} 缺少 SKILL.md 文件")
                    continue
                # 👇 文件夹名作为 key
                skill_key = skill_folder.name

                try:
                    # 读取文件全部内容
                    content = skill_md.read_text(encoding="utf-8")
                    # 检查并解析 YAML front-matter
                    if content.startswith("---"):
                        # 把内容按 --- 切成 3 部分
                        # 第1部分：空
                        # 第2部分：YAML 配置（name、description 等）
                        # 第3部分：正文内容
                        parts = content.split("---", 2)
                        # 确保确实切为了 3 部分
                        if len(parts) >= 3:
                            ## 把中间那段配置文本解析成 Python 字典
                            meta = yaml.safe_load(parts[1]) or {}
                            
                            # 组装技能信息
                            skills_index[skill_key] = {
                                "name": meta.get("name", skill_key),
                                "description": meta.get("description", ""),
                                "path": f"skills/{skill_key}/{skill_md.name}"
                            }
                except Exception as e:
                    logger.warning(f"[ContextBuilder] 解析 {skill_md} 失败: {e}")

        # 将字典转换为 JSON 格式的字符串
        # ensure_ascii=False 保证中文正常显示，indent=4 增加可读性
        json_str = json.dumps(skills_index, ensure_ascii=False, indent=4)
        return f"SKILLS = {json_str}"
    
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