# agent/react_agent.py
import sys
from pathlib import Path

from langchain.messages import AIMessageChunk
from langchain_core.messages import AIMessage
sys.path.append(str(Path(__file__).resolve().parent.parent))

import sqlite3

from langgraph.checkpoint.sqlite import SqliteSaver
from langchain.agents import create_agent 
from langchain.agents.middleware import TodoListMiddleware
from langchain.agents.middleware import SummarizationMiddleware, wrap_model_call
from agent.context import ContextBuilder
from agent.tools.registry import get_all_tools
from utils.logger_handler import logger
from model.factory import chat_model
from model.factory import memory_model

class ReactAgent:
    def __init__(self):
        self.conn = sqlite3.connect(
            str(Path(__file__).resolve().parent.parent / "checkpoints.db"),
            check_same_thread=False,
        )
        self.checkpointer = SqliteSaver(self.conn)
        self.context_builder = ContextBuilder()
        self._build_agent()

    def _build_agent(self):
        tools = get_all_tools()
        logger.info(f"[ReactAgent] 已加载工具: {[t.name for t in tools]}")

        # @wrap_model_call
        # def dynamic_prompt_middleware(request: ModelRequest, handler) -> ModelResponse:
        #     """每次调用大模型前，动态注入最新的 System Prompt"""
        #     # 通过实例调用 build_system_prompt
        #     system_prompt = self.context_builder.build_system_prompt()
        #     # 将动态生成的系统提示词插入到消息列表的最前面
        #     request.messages = [SystemMessage(content=system_prompt)] + request.messages
        #     return handler(request)

        # 上下文总结中间件
        Summarization_Middleware= SummarizationMiddleware(
        model=memory_model,
        max_tokens_before_summary=2000,
        messages_to_keep=10)

        
        self.agent = create_agent(
            model=chat_model,  
            tools=tools,
            # 对话历史
            checkpointer=self.checkpointer,
            # 中间件
            middleware=[Summarization_Middleware,
                        TodoListMiddleware()],       
            system_prompt=self.context_builder.build_system_prompt(),
        )
        logger.info("[ReactAgent] Agent 构建完成")

    # ──────────────────────────────────────────
    # 流式输出
    # ──────────────────────────────────────────

    def execute_stream(self, query: str, thread_id: str = "default"):
        input_dict = {"messages": [{"role": "user", "content": query}]}
        config = {"configurable": {"thread_id": thread_id}}
    
        for chunk, metadata in self.agent.stream(
                input_dict,
                stream_mode="messages",
                context={"report": False},
                config=config
        ):
            #print(f"[DEBUG] chunk type: {type(chunk)}, content: {chunk.content if hasattr(chunk, 'content') else 'N/A'}", file=sys.stderr)
            # chunk 在这里直接是一个 MessageChunk 对象
            if isinstance(chunk, (AIMessage, AIMessageChunk)) and chunk.content:
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