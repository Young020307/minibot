# agent/react_agent.py
import asyncio
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))

import aiosqlite

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langchain.agents import create_agent 
from langchain_core.messages import AIMessage
from langchain.messages import AIMessageChunk
from langchain.agents.middleware import TodoListMiddleware

from agent.memory_manager import MemoryManager # 👉 引入记忆管理器
from agent.context import ContextBuilder
from agent.tools.registry import get_all_tools
from utils.logger_handler import logger
from model.factory import chat_model
from cron.cron import cron_state
from agent.middleware import (MonitorTools_Middleware,
                                    Log_Before_Model_Middleware,
                                    Summarization_Middleware)

# 内部导入心跳模块
from heartbeat.service import HeartbeatService
from heartbeat.dashscope import DashScopeProvider

class ReactAgent:
    def __init__(self):
        self.conn = None
        self.checkpointer = None
        self.agent = None
        self.context_builder = ContextBuilder()
        self.memory_manager = MemoryManager() # 👉 实例化
        self.message_counter = {} # 👉 记录每个 thread 的消息增量
        self.heartbeat = None  # 心跳服务实例（内部自动创建）

    async def initialize(self):
        """异步初始化：数据库 + Agent + 自动创建并启动心跳服务"""
        # 1. 初始化数据库和检查点
        db_path = str(Path(__file__).resolve().parent.parent / "checkpoints.db")
        self.conn = await aiosqlite.connect(db_path)
        self.checkpointer = AsyncSqliteSaver(self.conn)
        await self.checkpointer.setup()
        
        # 2. 构建 Agent
        self._build_agent()

        # 3. ✅ 核心：自动初始化并启动心跳（封装在类内部）
        await self._init_heartbeat()

        # 4. 启动 Cron 定时任务服务
        await cron_state._cron.start()
        # 5. 绑定 Agent 回调，让 Cron 能真正调用 Agent 执行任务
        cron_state.set_agent_callback(self.execute_background_task)

    def _build_agent(self):
        tools = get_all_tools()
        logger.info(f"[ReactAgent] 已加载工具: {[t.name for t in tools]}")

        self.agent = create_agent(
            model=chat_model,  
            tools=tools,
            checkpointer=self.checkpointer,
            middleware=[Summarization_Middleware,
                        TodoListMiddleware(),
                        MonitorTools_Middleware,
                        Log_Before_Model_Middleware],       
            system_prompt=self.context_builder.build_system_prompt(),
        )
        logger.info("[ReactAgent] Agent 构建完成")

    # ──────────────────────────────────────────
    # ✅ 心跳服务封装：内部自动创建、绑定、启动
    # ──────────────────────────────────────────
    async def _init_heartbeat(self):
        """内部方法：自动创建心跳服务并绑定回调 + 启动"""
        workspace = Path(__file__).resolve().parent.parent

        # 心跳执行回调（闭包绑定当前 agent 实例）
        async def on_heartbeat_execute(tasks: str) -> str:
            logger.info(f"👉 收到心跳任务，转交 Agent 执行: {tasks}")
            return await self.execute_background_task(tasks, thread_id="background_tasks")

        # 心跳通知回调
        async def on_heartbeat_notify(response: str):
            logger.info(f"🔔 【系统通知】Agent 完成了后台任务:\n{response}")

        # 创建心跳实例
        self.heartbeat = HeartbeatService(
            workspace=workspace,
            provider=DashScopeProvider(),
            interval_s= 30 * 60,  # 30分钟一次
            on_execute=on_heartbeat_execute,
            on_notify=on_heartbeat_notify,
        )

        # 启动心跳
        await self.heartbeat.start()
        logger.info("[ReactAgent] Heartbeat 服务启动成功")


    # ──────────────────────────────────────────
    # ✅ 流式输出
    # ──────────────────────────────────────────

    async def execute_stream(self, query: str, thread_id: str = "default"):
        """异步执行查询，并返回流式输出。"""
        
        # 👉 【新增代码】每次 Agent 运行前，更新 Cron 的上下文
        # 渠道标记为 "terminal"，接收者标记为当前的 thread_id
        cron_state.set_context(channel="terminal", chat_id=thread_id)

        input_dict = {"messages": [{"role": "user", "content": query}]}
        config = {"configurable": {"thread_id": thread_id}}
    
        async for chunk, metadata in self.agent.astream(
                input_dict,
                stream_mode="messages",
                config=config
        ):
            if isinstance(chunk, (AIMessage, AIMessageChunk)) and chunk.content:
                yield chunk.content

        # 👉 流式输出完成后，进行后台记忆处理机制
        # 1. 累加对话轮数
        self.message_counter[thread_id] = self.message_counter.get(thread_id, 0) + 1
        
        # 2. 设定阈值（比如每 3 轮对话，触发一次后台提取）
        if self.message_counter[thread_id] >= 3:
            # 获取最近的历史记录
            history = await self.get_history(thread_id)
            if history:
                # 仅取最近的 6 条（3轮交互）进行提炼
                recent_msgs = history[-6:] 
                # asyncio.create_task 会把任务扔到后台运行，不会阻塞当前函数返回，
                # 用户已经拿到了所有回答，此时 Agent 正在后台暗暗"做笔记"。
                asyncio.create_task(self.memory_manager.consolidate_background(recent_msgs))
            # 重置计数器
            self.message_counter[thread_id] = 0

    # ──────────────────────────────────────────
    # ✅ 会话记忆 / 线程管理
    # ──────────────────────────────────────────

    async def get_history(self, thread_id: str) -> list[dict]:
        """获取指定线程的消息历史。"""
        config = {"configurable": {"thread_id": thread_id}}
        try:
            state = await self.agent.aget_state(config)
            messages = state.values.get("messages", [])
            result = []
            for m in messages:
                if hasattr(m, "type") and m.type in ("human", "ai"):
                    result.append({
                        "role": "user" if m.type == "human" else "assistant",
                        "content": m.content,
                    })
            return result
        except Exception as e:
            logger.error(f"[ReactAgent] 获取历史失败: {e}")
            return []

    async def get_all_threads(self) -> list[str]:
        """返回所有已存在的 thread_id 列表。"""
        try:
            cursor = await self.conn.execute(
                "SELECT DISTINCT thread_id FROM checkpoints ORDER BY thread_id"
            )
            rows = await cursor.fetchall()
            return [row[0] for row in rows]
        except Exception as e:
            logger.error(f"[ReactAgent] 获取线程列表失败: {e}")
            return []

    async def delete_thread(self, thread_id: str):
        """删除指定线程的所有检查点。"""
        try:
            await self.conn.execute("DELETE FROM checkpoints WHERE thread_id = ?", (thread_id,))
            await self.conn.execute("DELETE FROM writes WHERE thread_id = ?", (thread_id,))
            await self.conn.commit()
            logger.info(f"[ReactAgent] 已删除线程: {thread_id}")
        except Exception as e:
            logger.error(f"[ReactAgent] 删除线程失败: {e}")

    async def execute_background_task(self, task_query: str, thread_id: str = "heartbeat_daemon") -> str:
        """接收心跳服务传来的任务，执行并返回完整结果。"""
        
        # 👉 【新增代码】为后台任务更新 Cron 上下文
        # 渠道标记为 "heartbeat"，接收者标记为当前的 thread_id
        cron_state.set_context(channel="heartbeat", chat_id=thread_id)

        full_response = ""
        # 这里调用的 execute_stream 内部也会更新上下文，
        # 但显式在这里写明逻辑更清晰，或者保持原样也可。
        async for chunk in self.execute_stream(task_query, thread_id=thread_id):
            full_response += chunk
        return full_response

    async def close(self):
        """关闭心跳服务 + 数据库连接"""
        if self.heartbeat:
            self.heartbeat.stop()
            logger.info("[ReactAgent] HeartbeatService 已自动关闭")
        cron_state._cron.stop()
        if self.conn:
            await self.conn.close()
