# agent/memory_manager.py
import datetime
import tiktoken
from pathlib import Path
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage
from langchain_core.messages.modifier import RemoveMessage

from utils.logger_handler import logger
from model.factory import memory_model 

class MemoryUpdateResponse(BaseModel):
    history_update: str = Field(
        description="一段总结当前对话关键事件的长期记忆文本。必须以 [YYYY-MM-DD HH:MM] 开头，包含便于后续 grep 检索的关键细节。"
    )
    memory_update: str = Field(
        description="完整的最新记忆(Markdown格式)。必须严格遵循预设的 Headers 结构，将新发现的事实补充到对应的分类下。"
    )

class MemoryStore:
    """负责物理文件的读写与初始模板管理"""
    def __init__(self, workspace_path: Path):
        self.memory_dir = workspace_path / "templates" / "memory"
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.memory_file = self.memory_dir / "MEMORY.md"
        self.history_file = self.memory_dir / "HISTORY.md"
        
        self.template_structure = """# Long-term Memory
This file stores important information that should persist across sessions.

## User Information
(Important facts about the user)

## Preferences
(User preferences learned over time)

## Project Context
(Information about ongoing projects)

## Important Notes
(Special rules that must be followed, pitfalls we have encountered together, or dynamically generated global constraints.)
"""

    def read_long_term(self) -> str:
        if self.memory_file.exists():
            return self.memory_file.read_text(encoding="utf-8")
        return self.template_structure

    def write_long_term(self, content: str) -> None:
        self.memory_file.write_text(content, encoding="utf-8")

    def append_history(self, entry: str) -> None:
        with open(self.history_file, "a", encoding="utf-8") as f:
            f.write(entry.strip() + "\n\n")


class DualMemoryManager:
    """双层记忆压缩器：监控 Token，寻找安全边界，执行压缩"""
    
    def __init__(self, workspace_path: str = r"C:\Users\Younson\Desktop\Agent\minibot"):
        self.store = MemoryStore(Path(workspace_path))
        self.llm = memory_model.with_structured_output(MemoryUpdateResponse)
        # 默认使用 cl100k_base 估算 Token
        self.tokenizer = tiktoken.get_encoding("cl100k_base") 
        
        # 上下文预算配置
        self.MAX_CONTEXT_TOKENS = 4000  # 触发压缩的阈值
        self.TARGET_TOKENS = 2000      # 压缩后希望保留的 Token 数量

    def _estimate_tokens(self, text: str) -> int:
        return len(self.tokenizer.encode(text))

    def _find_safe_boundary(self, messages: list, tokens_to_remove: int) -> int:
        """寻找安全的截断边界：必须是 HumanMessage，且不能破坏 Tool Call 的成对关系"""
        removed_tokens = 0
        safe_index = 0
        
        # 记录当前遇到的未闭合的 Tool Call ID
        pending_tool_calls = set()

        for i, msg in enumerate(messages):
            # 估算当前消息 Token
            removed_tokens += self._estimate_tokens(msg.content if isinstance(msg.content, str) else str(msg.content))
            
            # 维护 Tool Call 成对状态
            if isinstance(msg, AIMessage) and msg.tool_calls:
                for tc in msg.tool_calls:
                    pending_tool_calls.add(tc["id"])
            elif isinstance(msg, ToolMessage):
                pending_tool_calls.discard(msg.tool_call_id)

            # 只有当：1. 是用户消息 2. 之前积累的 token 够了 3. 没有悬空的工具调用 时，才是安全边界
            if isinstance(msg, HumanMessage):
                if removed_tokens >= tokens_to_remove and len(pending_tool_calls) == 0:
                    safe_index = i
                    break
                    
        return safe_index

    async def maybe_consolidate(self, messages: list) -> list:
        """
        检查是否超载。如果超载，提取老消息进行压缩，并返回需要从状态中删除的消息列表。
        返回的列表中包含 RemoveMessage 对象。
        """
        if not messages:
            return []

        # 估算当前总 Token
        total_tokens = sum(self._estimate_tokens(m.content if isinstance(m.content, str) else str(m.content)) for m in messages)
        
        if total_tokens < self.MAX_CONTEXT_TOKENS:
            return [] # 未超载，不需要压缩
            
        logger.info(f"[MemoryManager] 当前 Token ({total_tokens}) 超过阈值 ({self.MAX_CONTEXT_TOKENS})，准备触发后台压缩...")
        
        tokens_to_remove = total_tokens - self.TARGET_TOKENS
        boundary_idx = self._find_safe_boundary(messages, tokens_to_remove)
        
        if boundary_idx <= 0:
            logger.warning("[MemoryManager] 无法找到安全的截断边界，跳过本次压缩。")
            return []

        # 获取需要被压缩的老旧消息
        messages_to_consolidate = messages[:boundary_idx]
        
        # 异步执行总结并写入文件
        await self._consolidate_and_save(messages_to_consolidate)
        
        # 返回 LangGraph 原生的 RemoveMessage 指令，彻底从短期记忆(SQLite)中抹除这些老消息
        return [RemoveMessage(id=m.id) for m in messages_to_consolidate if m.id]

    async def _consolidate_and_save(self, messages: list):
        """核心合并逻辑"""
        current_memory = self.store.read_long_term()
        dialogue = "\n".join([f"{m.__class__.__name__.replace('Message', '').upper()}: {m.content}" for m in messages])
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        
        prompt = f"""
        # 任务目标
        分析近期老旧对话，提取长期事实，生成历史日志摘要。如果新发现的事实与已有事实冲突，请以【更改】开头。
        
        ## 当前的长期事实内容 (MEMORY.md)
        {current_memory}
        
        ## 需要归档的老旧对话记录
        {dialogue}

        ## 当前时间
        {current_time}
        """

        try:
            result: MemoryUpdateResponse = await self.llm.ainvoke(
                [SystemMessage(content="你是一个遵循严格 Markdown 结构的记忆管理员助手。"),
                HumanMessage(content=prompt)],
                config={"callbacks": []} # <--- 新增这行，防止总结记忆的输出显示出来！)
                ) 
            
            if result.history_update:
                self.store.append_history(result.history_update)
            
            if result.memory_update and result.memory_update.strip() != current_memory.strip():
                self.store.write_long_term(result.memory_update)
                logger.info(f"[MemoryManager] 成功将 {len(messages)} 条老旧消息压缩进 MEMORY.md")
                
        except Exception as e:
            logger.error(f"[MemoryManager] 记忆压缩失败: {e}")
            self.store.append_history(f"[{current_time}] [RAW ARCHIVE] {len(messages)} messages dumped due to LLM error.\n\n")