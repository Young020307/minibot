import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

import subprocess
import yaml
from langchain_core.tools import tool
from utils.logger_handler import logger
from utils.path_tool import get_abs_path
from utils.config_handler import api_conf
from tavily import TavilyClient

# 基础工具

#初始化Tavily
tavily_client = TavilyClient(api_key=api_conf.get("TAVILY_API_KEY"))
@tool(description="用于实时网页搜索的工具，适用于需要获取最新信息、无法通过知识库回答的事实性问题、需要验证或补充最新数据的问题。")
def web_search(query: str) -> str:
    # 调用Tavily API（深度搜索模式，适合Agent）
    search_results = tavily_client.search(
        query = query,
        search_depth = "basic",  # 爬取方式网页正文
        max_results=3,  # 控制返回结果数量，避免Agent处理过载
        include_answer=True,  # 返回AI总结的答案
        include_raw_content=False  # 简化结果，只返回摘要（如需完整内容可改为True）
    )
    # 格式化结果（让Agent更容易理解和使用）
    formatted_results = []
    # 优先用Tavily的AI总结答案
    if search_results.get("answer"):
        formatted_results.append(f"【AI网页总结】: {search_results['answer']}\n")
    # 补充原始搜索结果（带来源，增强可信度）
    for idx, result in enumerate(search_results["results"], 1):
        formatted_results.append(
            f"【结果{idx}】\n"
            f"标题: {result['title']}\n"
            f"链接: {result['url']}\n"
            f"内容: {result['content'][:500]}...\n"  # 截断过长内容
        )
    return "\n".join(formatted_results)

@tool(description="执行 shell 命令并返回输出。用于调用 weather、github、tmux 等 CLI 技能。命令超时默认 60 秒。")
def bash_exec(command: str, timeout: int = 60) -> str:
    """Run a shell command and return stdout+stderr."""
    logger.info(f"[bash_exec] 执行: {command}")
    # 危险命令黑名单
    _BLOCKED = ["rm -rf /", "format ", "dd if=", "shutdown", "mkfs"]
    if any(b in command for b in _BLOCKED):
        return f"[拒绝] 该命令已被安全策略阻止: {command}"
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = (result.stdout + result.stderr).strip()
        if len(output) > 10000:
            output = output[:10000] + "\n...[输出已截断]"
        return output or "(无输出)"
    except subprocess.TimeoutExpired:
        return f"[超时] 命令执行超过 {timeout} 秒"
    except Exception as e:
        return f"[错误] {e}"

@tool(description="读取文件内容。path 为相对项目根目录的路径或绝对路径。")
def read_file(path: str) -> str:
    """Read a file and return its text content."""
    logger.info(f"[read_file] 读取: {path}")
    try:
        p = Path(path) if Path(path).is_absolute() else Path(get_abs_path(path))
        return p.read_text(encoding="utf-8")
    except Exception as e:
        return f"[错误] 无法读取文件 {path}: {e}"

@tool(description="将内容写入文件（覆盖）。path 为相对项目根目录的路径或绝对路径。")
def write_file(path: str, content: str) -> str:
    """Write text content to a file (overwrite)."""
    logger.info(f"[write_file] 写入: {path}")
    try:
        p = Path(path) if Path(path).is_absolute() else Path(get_abs_path(path))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"已成功写入: {path}"
    except Exception as e:
        return f"[错误] 无法写入文件 {path}: {e}"

@tool(description="向文件末尾追加内容。path 为相对项目根目录的路径或绝对路径。")
def edit_file(path: str, content: str) -> str:
    """Append text content to a file."""
    logger.info(f"[edit_file] 追加: {path}")
    try:
        p = Path(path) if Path(path).is_absolute() else Path(get_abs_path(path))
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write("\n" + content)
        return f"已成功追加到: {path}"
    except Exception as e:
        return f"[错误] 无法追加文件 {path}: {e}"

@tool(description="调用此工具获取该技能的完整操作指南和代码示例。输入技能名称（目录名），输出该技能的完整 SKILL.md 内容，供 Agent 理解和使用。")
def get_skill_details(skill_name: str) -> str:
    from .registry import registry # 避免循环引用
    content = registry.skills_loader.load_skill(skill_name)
    if content:
        # 移除元数据，只给 Agent 看正文
        body = registry.skills_loader._strip_frontmatter(content)
        return f"### 技能 {skill_name} 的详细操作指南：\n\n{body}"
    return f"未找到技能: {skill_name}"

@tool(description="列出所有可用的本地技能（skills）及其描述")
def list_skills() -> str:
    """List all available local skills loaded from the skills/ directory."""
    skills = _scan_skills()
    if not skills:
        return "暂无可用技能"
    lines = [f"- **{s['name']}**: {s['description']}" for s in skills]
    return "## 可用技能\n\n" + "\n".join(lines)

def _scan_skills() -> list[dict]:
    """扫描 skills/ 目录，解析每个 SKILL.md 的 YAML front-matter。"""
    skills_dir = Path(get_abs_path("skills"))
    if not skills_dir.exists():
        return []
    results = []
    for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
        try:
            text = skill_md.read_text(encoding="utf-8")
            if text.startswith("---"):
                _, fm, body = text.split("---", 2)
                meta = yaml.safe_load(fm)
                results.append({
                    "name": meta.get("name", skill_md.parent.name),
                    "description": meta.get("description", ""),
                    "always": meta.get("always", False),
                    "body": body.strip(),
                })
        except Exception as e:
            logger.warning(f"[registry] 解析 skill 失败: {skill_md} — {e}")
    return results