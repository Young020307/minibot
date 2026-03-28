"""Heartbeat service - periodic agent wake-up to check for tasks."""

from __future__ import annotations

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))

import asyncio
from typing import TYPE_CHECKING, Any, Callable, Coroutine

from utils.logger_handler import logger

if TYPE_CHECKING:
    from base import LLMProvider

# 虚拟心跳工具
_HEARTBEAT_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "heartbeat",
            "description": "Report heartbeat decision after reviewing tasks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["skip", "run"],
                        "description": "skip = nothing to do, run = has active tasks",
                    },
                    "tasks": {
                        "type": "string",
                        "description": "Natural-language summary of active tasks (required for run)",
                    },
                },
                "required": ["action"],
            },
        },
    }
]


class HeartbeatService:
    """
    周期性心跳服务：唤醒智能体以检查待执行任务
    第一阶段（决策阶段）：
        读取 HEARTBEAT.md 文件，
        并通过虚拟工具调用向大语言模型（LLM）询问是否存在活跃任务。
        该方案规避了自由文本解析的问题，同时摒弃了不可靠的 HEARTBEAT_OK 标记位。
    第二阶段（执行阶段）：
        仅当第一阶段返回 run 时触发。
        on_execute 回调函数会驱动智能代理完整执行任务流程，
        并将执行结果返回用于后续推送。
    """

    def __init__(
        self,
        workspace: Path,
        provider: LLMProvider,
        model: str,
        on_execute: Callable[[str], Coroutine[Any, Any, str]] | None = None,
        on_notify: Callable[[str], Coroutine[Any, Any, None]] | None = None,
        interval_s: int = 30 * 60,
        enabled: bool = True,
    ):
        self.workspace = workspace
        self.provider = provider
        self.model = model
        self.on_execute = on_execute
        self.on_notify = on_notify
        self.interval_s = interval_s
        self.enabled = enabled
        self._running = False
        self._task: asyncio.Task | None = None

    @property
    def heartbeat_file(self) -> Path:
        """返回HEARTBEAT.md 文件的路径"""
        return self.workspace / "templates" / "HEARTBEAT.md"

    def _read_heartbeat_file(self) -> str | None:
        """读取 HEARTBEAT.md 文件并返回内容。"""
        if self.heartbeat_file.exists():
            try:
                return self.heartbeat_file.read_text(encoding="utf-8")
            except Exception:
                return None
        return None

    async def _decide(self, content: str) -> tuple[str, str]:
        """
        第一阶段：通过虚拟工具调用，让大语言模型（LLM）决策是跳过任务还是执行任务
        返回值为 (动作，任务内容)，其中动作取值为'skip'（跳过）或 'run'（执行）.
        """
        from utils.helpers import current_time_str

        response = await self.provider.chat_with_retry(
            messages=[
                {"role": "system", "content": "You are a heartbeat agent. Call the heartbeat tool to report your decision."},
                {"role": "user", "content": (
                    f"Current Time: {current_time_str()}\n\n"
                    "Review the following HEARTBEAT.md and decide whether there are active tasks.\n\n"
                    f"{content}"
                )},
            ],
            tools=_HEARTBEAT_TOOL,
            model=self.model,
        )

        if not response.has_tool_calls:
            return "skip", ""

        args = response.tool_calls[0].arguments
        return args.get("action", "skip"), args.get("tasks", "")

    async def start(self) -> None:
        """开始运行 heartbeat 服务."""
        if not self.enabled:
            logger.info("Heartbeat disabled")
            return
        if self._running:
            logger.warning("Heartbeat already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(f"Heartbeat started (every {self.interval_s}s)")

    def stop(self) -> None:
        """Stop the heartbeat service."""
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None

    async def _run_loop(self) -> None:
        """Main heartbeat loop."""
        while self._running:
            try:
                await asyncio.sleep(self.interval_s)
                if self._running:
                    await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")

    async def _tick(self) -> None:
        """Execute a single heartbeat tick."""
        from utils.evaluator import evaluate_response

        content = self._read_heartbeat_file()
        if not content:
            logger.debug(f"Heartbeat: HEARTBEAT.md missing or empty")
            return

        logger.info(f"Heartbeat: checking for tasks...")

        try:
            action, tasks = await self._decide(content)

            if action != "run":
                logger.info(f"Heartbeat: OK (nothing to report)")
                return

            logger.info(f"Heartbeat: tasks found, executing...")
            if self.on_execute:
                response = await self.on_execute(tasks)

                if response:
                    should_notify = await evaluate_response(
                        response, tasks, self.provider, self.model,
                    )
                    if should_notify and self.on_notify:
                        logger.info(f"Heartbeat: completed, delivering response")
                        await self.on_notify(response)
                    else:
                        logger.info(f"Heartbeat: silenced by post-run evaluation")
        except Exception:
            logger.exception(f"Heartbeat execution failed")

    async def trigger_now(self) -> str | None:
        """人为触发一次 heartbeat 任务."""
        content = self._read_heartbeat_file()
        if not content:
            return None
        action, tasks = await self._decide(content)
        if action != "run" or not self.on_execute:
            return None
        return await self.on_execute(tasks)
