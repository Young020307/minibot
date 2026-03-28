#model/dashscope.py
import os
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from typing import Any

from langchain_community.chat_models.tongyi import ChatTongyi
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

# 导入基类和响应类 
from heartbeat.base import LLMProvider, LLMResponse 

class DashScopeProvider(LLMProvider):
    """基于 LangChain ChatTongyi 实现的通义千问 Provider。"""
    def __init__(self, api_key: str | None = None, api_base: str | None = None):
        super().__init__(api_key, api_base)
        self.api_key = os.getenv("DASHSCOPE_API_KEY")
        if not self.api_key:
            raise ValueError("⚠️ 缺少 DASHSCOPE_API_KEY 环境变量！")

    def get_default_model(self) -> str:
        from utils.config_handler import agent_conf
        return agent_conf.get("heartbeat_model_name")

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> LLMResponse: 
        
        actual_model = model or self.get_default_model()
        llm = ChatTongyi(
            model_name=actual_model, dashscope_api_key=self.api_key,
            temperature=temperature, max_tokens=max_tokens,
        )

        # 👉 关键点 1：把心跳服务发来的虚拟工具透传给模型
        if tools:
            llm = llm.bind_tools(tools)

        lc_messages = []
        clean_messages = self._sanitize_empty_content(messages)
        for msg in clean_messages:
            role = msg.get("role")
            content = msg.get("content", "")
            if role == "system":
                lc_messages.append(SystemMessage(content=content))
            elif role == "user":
                lc_messages.append(HumanMessage(content=content))
            elif role == "assistant":
                lc_messages.append(AIMessage(content=content))
        
        ai_msg = await llm.ainvoke(lc_messages)
        print(f"\n[大模型真实回答] 文本内容: {ai_msg.content}")
        print(f"[大模型调用的工具] {getattr(ai_msg, 'tool_calls', '没有调用工具')}\n")
        # 👉 关键点 2：把模型吐出来的虚拟工具参数，原样装回 LLMResponse 给心跳服务
        from base import ToolCallRequest
        parsed_tool_calls = []
        if hasattr(ai_msg, "tool_calls") and ai_msg.tool_calls:
            for tc in ai_msg.tool_calls:
                parsed_tool_calls.append(
                    ToolCallRequest(
                        id=tc.get("id", ""),
                        name=tc["name"],
                        arguments=tc["args"],
                    )
                )

        # has_tool_calls 是 @property，直接对 tool_calls 赋值即可，不要单独对 has_tool_calls 赋值
        response = LLMResponse(
            content=ai_msg.content,
            finish_reason="stop",
            tool_calls=parsed_tool_calls,
        )

        return response