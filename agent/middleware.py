from typing import Callable, Awaitable
from langchain.agents import AgentState
from langchain.agents.middleware import SummarizationMiddleware, wrap_tool_call, before_model
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.runtime import Runtime
from langgraph.types import Command

from utils.logger_handler import logger
from model.factory import memory_model

@wrap_tool_call
async def MonitorTools_Middleware(
        # 请求的数据封装
        request: ToolCallRequest,
        # 执行的函数本身，在异步环境中它返回一个 Awaitable 对象
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
) -> ToolMessage | Command:             
    # 工具执行的监控
    logger.info(f"[tool monitor]执行工具：{request.tool_call['name']}")
    logger.info(f"[tool monitor]传入参数：{request.tool_call['args']}")

    try:
        # 使用 await 等待异步 handler 执行完成
        result = await handler(request)
        logger.info(f"[tool monitor]工具{request.tool_call['name']}调用成功")

        if request.tool_call['name'] == "fill_context_for_report":
            request.runtime.context["report"] = True

        return result
    except Exception as e:
        logger.error(f"工具{request.tool_call['name']}调用失败，原因：{str(e)}")
        raise e

@before_model
async def Log_Before_Model_Middleware(
        state: AgentState,          # 整个Agent智能体中的状态记录
        runtime: Runtime,           # 记录了整个执行过程中的上下文信息
):         
    # 在模型执行前输出日志
    logger.info(f"[log_before_model]即将调用模型，带有{len(state['messages'])}条消息。")
    logger.debug(f"[log_before_model]{type(state['messages'][-1]).__name__} | {state['messages'][-1].content.strip()}")

    return None

# 上下文总结中间件的实例化（实例化过程本身是同步的，它的异步执行由 LangChain/LangGraph 内部框架调度）
Summarization_Middleware = SummarizationMiddleware(
    model=memory_model,
    max_tokens_before_summary=2000,
    messages_to_keep=10
)