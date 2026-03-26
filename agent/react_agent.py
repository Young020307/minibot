# agent/react_agent.py
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))

import sqlite3
from langchain_core.messages import SystemMessage
from langgraph.checkpoint.sqlite import SqliteSaver
#极端耗时导包操作
from langchain.agents import create_agent 

from langchain.agents.middleware import wrap_model_call, ModelRequest, ModelResponse
from agent.context import ContextBuilder
from agent.tools.registry import get_all_tools
from utils.logger_handler import logger
from model.factory import chat_model

class ReactAgent:
    def __init__(self):
        self.conn = sqlite3.connect(
            str(Path(__file__).resolve().parent.parent / "checkpoints.db"),
            check_same_thread=False,
        )
        self.checkpointer = SqliteSaver(self.conn)
        self._build_agent()
        self.context_builder = ContextBuilder()

    def _build_agent(self):
        tools = get_all_tools()
        logger.info(f"[ReactAgent] 已加载工具: {[t.name for t in tools]}")

        @wrap_model_call
        def dynamic_prompt_middleware(request: ModelRequest, handler) -> ModelResponse:
            """每次调用大模型前，动态注入最新的 System Prompt"""
            # 通过实例调用 build_system_prompt
            system_prompt = self.context_builder.build_system_prompt()
            # 将动态生成的系统提示词插入到消息列表的最前面
            request.messages = [SystemMessage(content=system_prompt)] + request.messages
            return handler(request)

        self.agent = create_agent(
            model=chat_model,  
            tools=tools,
            checkpointer=self.checkpointer,
            middleware=[dynamic_prompt_middleware]
        )
        logger.info("[ReactAgent] Agent 构建完成")

    # ──────────────────────────────────────────
    # 流式输出
    # ──────────────────────────────────────────

    def execute_stream(self, query: str, thread_id: str = "default", media: list[str] = None):
        """流式返回 AI token，支持传入图片路径列表 (media)。"""
        
        # 4. 修改：利用 ContextBuilder 组装带有时间戳和图片的用户输入
        # 获取格式化后的内容（可能是纯字符串，也可能是包含 base64 图片的列表）
        user_content = self.context_builder._build_user_content(query, media)
        
        # 构造运行时上下文（强制带上当前时间）
        runtime_ctx = (
            f"{self.context_builder._RUNTIME_CONTEXT_TAG}\n"
            f"Current Time: {self.context_builder._get_current_time_str()}"
        )

        # 融合上下文和用户输入
        if isinstance(user_content, str):
            merged_content = f"{runtime_ctx}\n\n{user_content}"
        else:
            merged_content = [{"type": "text", "text": runtime_ctx + "\n\n"}] + user_content

        # 传入 LangGraph
        input_dict = {"messages": [{"role": "user", "content": merged_content}]}
        config = {"configurable": {"thread_id": thread_id}}

        for chunk, metadata in self.agent.stream(
            input_dict,
            stream_mode="messages",
            config=config,
        ):
            if chunk.type == "ai" and chunk.content:
                yield chunk.content

    # ──────────────────────────────────────────
    # 历史 / 线程管理
    # ──────────────────────────────────────────

    def get_history(self, thread_id: str) -> list[dict]:
        """返回指定线程的消息历史。"""
        config = {"configurable": {"thread_id": thread_id}}
        try:
            state = self.agent.get_state(config)
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

    def get_all_threads(self) -> list[str]:
        """返回所有已存在的 thread_id 列表。"""
        cursor = self.conn.cursor()
        try:
            cursor.execute(
                "SELECT DISTINCT thread_id FROM checkpoints ORDER BY thread_id"
            )
            return [row[0] for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"[ReactAgent] 获取线程列表失败: {e}")
            return []

    def delete_thread(self, thread_id: str):
        """删除指定线程的所有检查点。"""
        cursor = self.conn.cursor()
        try:
            cursor.execute(
                "DELETE FROM checkpoints WHERE thread_id = ?", (thread_id,)
            )
            cursor.execute(
                "DELETE FROM writes WHERE thread_id = ?", (thread_id,)
            )
            self.conn.commit()
            logger.info(f"[ReactAgent] 已删除线程: {thread_id}")
        except Exception as e:
            logger.error(f"[ReactAgent] 删除线程失败: {e}")

if __name__ == "__main__":
    agent = ReactAgent()

    # 设定一个固定的 thread_id，这样它就能记住你们前几轮聊了啥
    thread_id = "terminal_session_01" 
    print("==================================================")
    print("🤖 你的专属助手已启动！")
    print("💡 提示：输入 'exit' 或按下 Ctrl + C 即可结束对话。")
    print("==================================================")

    while True:
        try:
            # 1. 获取输入
            user_input = input("\n🧑 Young: ").strip()
            
            # 如果不小心直接敲了回车，就跳过这次循环
            if not user_input:
                continue
                
            # 如果输入 exit 或 quit，正常退出
            if user_input.lower() in ['exit', 'quit']:
                print("\n👋 收到!助手已下线，咱们下次聊。")
                break

            # 2. 调用 Agent 并流式输出回复
            print("🤖 助手: ", end="", flush=True)
            for chunk in agent.execute_stream(user_input, thread_id=thread_id):
                # 逐字打印 AI 的回复
                print(chunk, end="", flush=True)
            
            # 这一轮回答完了，打个换行符，准备迎接下一轮
            print() 

        except KeyboardInterrupt:
            # 捕捉咱们键盘按下的 Ctrl + C (终端标准中断按键)
            print("\n\n🛑 检测到中断信号 (Ctrl+C)，强制退出对话。拜拜！")
            break
            
        except Exception as e:
            # 万一代码或者 API 报错了，别直接崩溃，把错误打出来，还能继续聊
            print(f"\n❌ 哎呀，出错了: {e}")