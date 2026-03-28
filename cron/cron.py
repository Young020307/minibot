"""Cron tool for scheduling reminders and tasks."""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from contextvars import ContextVar
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from cron.service import CronService
from cron.types import CronJobState, CronSchedule


class CronToolManager:
    """Manages state and context for the Cron tool, yielding a LangChain tool."""

    def __init__(self, cron_service: CronService):
        self._cron = cron_service
        self._channel = ""
        self._chat_id = ""
        self._in_cron_context: ContextVar[bool] = ContextVar("cron_in_context", default=False)
        self._agent_callback = None  # async (message: str) -> str

    def set_agent_callback(self, callback) -> None:
        """Bind the agent's execute_background_task so cron can invoke it."""
        self._agent_callback = callback

    def set_context(self, channel: str, chat_id: str) -> None:
        """Set the current session context for delivery."""
        self._channel = channel
        self._chat_id = chat_id

    def set_cron_context(self, active: bool):
        """Mark whether the tool is executing inside a cron job callback."""
        return self._in_cron_context.set(active)

    def reset_cron_context(self, token) -> None:
        """Restore previous cron context."""
        self._in_cron_context.reset(token)

    def _add_job(
        self,
        message: str,
        every_seconds: int | None,
        cron_expr: str | None,
        tz: str | None,
        at: str | None,
        delay_seconds: int | None = None,
        is_task: bool = False,
    ) -> str:
        if not message:
            return "Error: message is required for add"
        if not self._channel or not self._chat_id:
            return "Error: no session context (channel/chat_id)"
        if tz and not cron_expr:
            return "Error: tz can only be used with cron_expr"
        if tz:
            try:
                ZoneInfo(tz)
            except (KeyError, Exception):
                return f"Error: unknown timezone '{tz}'"

        # Build schedule
        delete_after = False
        if every_seconds:
            schedule = CronSchedule(kind="every", every_ms=every_seconds * 1000)
        elif delay_seconds:
            import time
            at_ms = int(time.time() * 1000) + delay_seconds * 1000
            schedule = CronSchedule(kind="at", at_ms=at_ms)
            delete_after = True
        elif cron_expr:
            schedule = CronSchedule(kind="cron", expr=cron_expr, tz=tz)
        elif at:
            try:
                dt = datetime.fromisoformat(at)
            except ValueError:
                return f"Error: invalid ISO datetime format '{at}'. Expected format: YYYY-MM-DDTHH:MM:SS"
            at_ms = int(dt.timestamp() * 1000)
            schedule = CronSchedule(kind="at", at_ms=at_ms)
            delete_after = True
        else:
            return "Error: either every_seconds, cron_expr, or at is required"

        #核心修改：根据 is_task 决定交给谁处理
        job_kind = "agent_turn" if is_task else "message"
        job = self._cron.add_job(
            name=message[:30],
            schedule=schedule,
            message=message,
            deliver=True,
            channel=self._channel,
            to=self._chat_id,
            delete_after_run=delete_after,
            kind=job_kind
        )
        return f"Created job '{job.name}' (id: {job.id})"

    @staticmethod
    def _format_timing(schedule: CronSchedule) -> str:
        """Format schedule as a human-readable timing string."""
        if schedule.kind == "cron":
            tz = f" ({schedule.tz})" if schedule.tz else ""
            return f"cron: {schedule.expr}{tz}"
        if schedule.kind == "every" and schedule.every_ms:
            ms = schedule.every_ms
            if ms % 3_600_000 == 0:
                return f"every {ms // 3_600_000}h"
            if ms % 60_000 == 0:
                return f"every {ms // 60_000}m"
            if ms % 1000 == 0:
                return f"every {ms // 1000}s"
            return f"every {ms}ms"
        if schedule.kind == "at" and schedule.at_ms:
            dt = datetime.fromtimestamp(schedule.at_ms / 1000, tz=timezone.utc)
            return f"at {dt.isoformat()}"
        return schedule.kind

    @staticmethod
    def _format_state(state: CronJobState) -> list[str]:
        """Format job run state as display lines."""
        lines: list[str] = []
        if state.last_run_at_ms:
            last_dt = datetime.fromtimestamp(state.last_run_at_ms / 1000, tz=timezone.utc)
            info = f"  Last run: {last_dt.isoformat()} — {state.last_status or 'unknown'}"
            if state.last_error:
                info += f" ({state.last_error})"
            lines.append(info)
        if state.next_run_at_ms:
            next_dt = datetime.fromtimestamp(state.next_run_at_ms / 1000, tz=timezone.utc)
            lines.append(f"  Next run: {next_dt.isoformat()}")
        return lines

    def _list_jobs(self) -> str:
        jobs = self._cron.list_jobs()
        if not jobs:
            return "No scheduled jobs."
        lines = []
        for j in jobs:
            timing = self._format_timing(j.schedule)
            parts = [f"- {j.name} (id: {j.id}, {timing})"]
            parts.extend(self._format_state(j.state))
            lines.append("\n".join(parts))
        return "Scheduled jobs:\n" + "\n".join(lines)

    def _remove_job(self, job_id: str | None) -> str:
        if not job_id:
            return "Error: job_id is required for remove"
        if self._cron.remove_job(job_id):
            return f"Removed job {job_id}"
        return f"Job {job_id} not found"


# 1. 初始化路径与状态管理器
db_path = Path(__file__).resolve().parent.parent / "cron_jobs.json"
from cron.types import CronJob

# 2. 定义异步回调函数(解耦终端硬编码)
async def on_cron_job_execute(job: CronJob) -> None:
    if job.payload.kind == "agent_turn" and cron_state._agent_callback:
        # 让 agent 真正执行任务（可调用工具、搜索等）
        token = cron_state.set_cron_context(True)
        try:
            # 执行 agent 回调
            result = await cron_state._agent_callback(job.payload.message)
            
            # 只有在需要交付且渠道为 terminal 时才打印
            if job.payload.deliver:
                # 无论什么渠道，先打印到终端方便开发调试
                print(f"\n\n⏰ \033[93m[定时任务执行结果]: {result}\033[0m")
                print("🧑 Young: ", end="", flush=True)
        
                # TODO: 如果未来接入了其他渠道，可以在这里根据 job.payload.channel 进行消息推送分发
        finally:
            cron_state.reset_cron_context(token)
            
    elif job.payload.deliver:
        # 纯提醒，不需要调用 agent
        message = job.payload.message
        print(f"\n\n⏰ \033[93m[定时提醒]: {message}\033[0m")
        print("🧑 Young: ", end="", flush=True)

# 3. 实例化服务与管理器
# 核心：将回调函数注入 CronService
global_cron_service = CronService(
    store_path=db_path, 
    on_job=on_cron_job_execute  
)

# 核心：创建状态管理器供系统全局调用
cron_state = CronToolManager(global_cron_service)