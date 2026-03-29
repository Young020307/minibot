import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from langchain.tools import InjectedToolCallId, tool
from langgraph.types import Command
from langchain.messages import ToolMessage, HumanMessage

from utils.logger_handler import logger
from utils.helpers import get_abs_path

from typing import Annotated, Optional

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

@tool(description="当确定要使用某个技能时，调用此工具加载该技能。系统会确认加载，并在后台将技能操作指南作为上下文注入。")
def get_skill_details(
    skill_name: str,
    tool_call_id: Annotated[str, InjectedToolCallId]  # 👉 自动注入当前的 tool_call_id
) -> Command:
    logger.info(f"[get_skill_details] 获取技能详情: {skill_name}")
    
    skill_folder = Path(get_abs_path("skills")) / skill_name
    
    # 基础检查
    if not skill_folder.exists() or not skill_folder.is_dir():
        err_msg = f"错误：未找到名为 '{skill_name}' 的技能文件夹。"
        return Command(update={"messages": [ToolMessage(content=err_msg, tool_call_id=tool_call_id)]})

    try:
        md_files = list(skill_folder.glob("*.md"))
        if not md_files:
            err_msg = f"错误：在技能文件夹 '{skill_name}' 中未找到任何 Markdown 说明文件。"
            return Command(update={"messages": [ToolMessage(content=err_msg, tool_call_id=tool_call_id)]})
        
        target_md = md_files[0]
        content = target_md.read_text(encoding="utf-8")
        
        # 👉 核心修改：使用 Command 直接修改 Graph 的状态
        return Command(
            update={
                "messages": [
                    # 1. 满足 LLM 的工具回调要求，仅返回一个简短的确认
                    ToolMessage(
                        content=f"Launching skill: {skill_name}", 
                        tool_call_id=tool_call_id
                    ),
                    # 2. 将技能内容伪装成用户的补充输入，注入到对话流中
                    HumanMessage(
                        content=f"【技能 {skill_name} 加载成功】\n以下是该技能的完整操作指南，请将其作为上下文参考，并继续执行我的请求：\n\n{content}"
                    )
                ]
            }
        )

    except Exception as e:
        logger.error(f"[get_skill_details]读取技能时发生异常： {e}")
        err_msg = f"错误：在读取技能 '{skill_name}' 的说明文件时发生异常。"
        return Command(update={"messages": [ToolMessage(content=err_msg, tool_call_id=tool_call_id)]})

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