# agent/memory_manager.py
import asyncio
import datetime
from pathlib import Path
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage, SystemMessage

from utils.logger_handler import logger
from model.factory import memory_model 

class MemoryUpdateResponse(BaseModel):
    history_entry: str = Field(
        description="一段总结当前对话关键事件的文本。必须以 [YYYY-MM-DD HH:MM] 开头，包含便于后续 grep 检索的关键细节。"
    )
    memory_update: str = Field(
        description="完整的最新长期记忆(Markdown格式)。必须严格遵循预设的 Headers 结构，将新发现的事实补充到对应的分类下。"
    )

class MemoryManager:
    def __init__(self):
        # 👉 1. 指定绝对路径
        self.memory_dir = Path(r"C:\Users\Younson\Desktop\Agent\minibot\templates\memory")
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        
        self.memory_file = self.memory_dir / "MEMORY.md"
        self.history_file = self.memory_dir / "HISTORY.md"
        
        self.llm = memory_model.with_structured_output(MemoryUpdateResponse)

        # 👉 2. 定义严格的模板结构
        self.template_structure = """# Long-term Memory

This file stores important information that should persist across sessions.

## User Information

(Important facts about the user)

## Preferences

(User preferences learned over time)

## Project Context

(Information about ongoing projects)

## Important Notes

(Things to remember)"""

    def _read_current_memory(self) -> str:
        if self.memory_file.exists():
            return self.memory_file.read_text(encoding="utf-8")
        # 如果文件不存在，返回初始模板
        return self.template_structure

    async def consolidate_background(self, recent_messages: list[dict]):
        """在后台异步执行的记忆合并逻辑"""
        if not recent_messages:
            return
            
        current_memory = self._read_current_memory()
        dialogue = "\n".join([f"{m['role'].upper()}: {m['content']}" for m in recent_messages])
        
        # 👉 3. 强化 Prompt，要求严格保持骨架不变
        prompt = f"""
        ## 任务目标
        分析近期对话，提取长期事实，并生成历史日志摘要。
        
        ## 格式要求
        你在更新 `memory_update` 时，必须**严格保留以下 Markdown 标题骨架完全不变**：
        - ## User Information
        - ## Preferences
        - ## Project Context
        - ## Important Notes
        请将新发现的事实精准插入到对应的类别下。如果没有新事实，请原样返回现有的记忆内容。
        
        ## 当前长期记忆 (MEMORY.md)
        {current_memory}
        
        ## 近期对话记录
        {dialogue}
        """

        try:
            logger.info("[MemoryManager] 开始后台记忆提取...")
            result: MemoryUpdateResponse = await self.llm.ainvoke([
                SystemMessage(content="你是一个遵循严格 Markdown 结构的记忆管理员助手。"),
                HumanMessage(content=prompt)
            ])
            
            # 写入 HISTORY.md 
            if result.history_entry:
                with open(self.history_file, "a", encoding="utf-8") as f:
                    f.write(result.history_entry.strip() + "\n\n")
            
            # 覆写 MEMORY.md 
            if result.memory_update and result.memory_update.strip() != current_memory.strip():
                self.memory_file.write_text(result.memory_update, encoding="utf-8")
                logger.info("[MemoryManager] MEMORY.md 已按照预设结构更新")
                
        except Exception as e:
            logger.error(f"[MemoryManager] 后台记忆更新失败: {e}")
            ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            with open(self.history_file, "a", encoding="utf-8") as f:
                 f.write(f"[{ts}] [RAW ARCHIVE] {len(recent_messages)} messages dumped due to LLM error.\n\n")