import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from langchain_core.tools import tool

from utils.logger_handler import logger
from utils.helpers import get_abs_path
from utils.config_handler import api_conf

from tavily import TavilyClient
from typing import Optional
import subprocess

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
        return f"[拒绝] 该命令已被安全策略阻止：{command}"
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

@tool(description="读取文件内容。输入的 path 为相对项目根目录的路径或绝对路径。")
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

@tool(description="当确定要使用某个技能时，调用此工具获取该技能的详细操作指南。输入技能的名称，输出对应的 Markdown 文件全文。")
def get_skill_details(skill_name: str) -> str:
    logger.info(f"[get_skill_details] 获取技能详情: {skill_name}")
    # 1. 构建该技能文件夹的绝对路径
    skill_folder = Path(get_abs_path("skills")) / skill_name
    
    # 2. 基础检查：文件夹是否存在
    if not skill_folder.exists() or not skill_folder.is_dir():
        return f"错误：未找到名为 '{skill_name}' 的技能文件夹。"

    try:
        # 3. 寻找文件夹下的第一个 .md 文件
        md_files = list(skill_folder.glob("*.md"))
        if not md_files:
            return f"错误：在技能文件夹 '{skill_name}' 中未找到任何 Markdown 说明文件。"
        
        target_md = md_files[0]
        
        # 4. 读取并返回全文
        content = target_md.read_text(encoding="utf-8")
        return content

    except Exception as e:
        logger.error(f"[get_skill_details]读取技能时发生异常： {e}")
        return f"错误：在读取技能 '{skill_name}' 的说明文件时发生异常。"

from cron.cron import cron_state
@tool()
def cron_tool(
    action: str,
    message: str = "",
    every_seconds: Optional[int] = None,
    delay_seconds: Optional[int] = None,
    cron_expr: Optional[str] = None,
    tz: Optional[str] = None,
    at: Optional[str] = None,
    job_id: Optional[str] = None,
    is_task: bool = False
) -> str:
    """
    执行提醒与周期性任务管理。支持添加、列出、删除、暂停和恢复任务。
    
    Args:
        action: 必须是以下之一：'add'(添加), 'list'(查看列表), 'remove'(删除), 'pause'(暂停任务), 'resume'(恢复任务)。
        message: 提醒内容或具体要执行的任务描述（add 操作时必填）。
        every_seconds: 循环任务的间隔秒数（如 3600 代表每小时）。
        delay_seconds: 相对现在的延迟秒数（如 1800 代表20分钟后）。
        cron_expr: Cron 表达式，用于特定时间点的循环（如 '0 9 * * *' 代表每天早上9点）。
        tz: 时区（如 'Asia/Shanghai'）。
        at: 绝对时间字符串（如 '2026-03-28T10:30:00'）。如果是相对现在的时间，请优先使用 delay_seconds。
        job_id: 任务的唯一 ID（remove, pause, resume 操作时必填）。
        is_task: 布尔值。如果仅仅是到提醒，设为 False；如果需要 Agent 到点后在后台调用工具、搜索网络或执行复杂思考，必须设为 True。
    """
    if action == "add":
        if cron_state._in_cron_context.get():
            return "Error: cannot schedule new jobs from within a cron job execution"
        return cron_state._add_job(message, every_seconds, cron_expr, tz, at, delay_seconds, is_task=is_task)
    
    elif action == "list":
        return cron_state._list_jobs()
        
    elif action == "remove":
        return cron_state._remove_job(job_id)
        
    elif action == "pause":
        if not job_id:
            return "Error: job_id is required for pause"
        job = cron_state._cron.enable_job(job_id, enabled=False)
        return f"Successfully paused job {job_id}" if job else f"Job {job_id} not found"
        
    elif action == "resume":
        if not job_id:
            return "Error: job_id is required for resume"
        job = cron_state._cron.enable_job(job_id, enabled=True)
        return f"Successfully resumed job {job_id}" if job else f"Job {job_id} not found"
        
    return f"Unknown action: {action}"