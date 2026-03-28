# agent/memory_manager.py
import datetime
from pathlib import Path
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage, SystemMessage

from utils.logger_handler import logger
from model.factory import memory_model 

class MemoryUpdateResponse(BaseModel):
    history_update: str = Field(
        description="一段总结当前对话关键事件的长期记忆文本。必须以 [YYYY-MM-DD HH:MM] 开头，包含便于后续 grep 检索的关键细节。"
    )
    memory_update: str = Field(
        description="完整的最新记忆(Markdown格式)。必须严格遵循预设的 Headers 结构，将新发现的事实补充到对应的分类下。"
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
        self.template_structure = """
            # Long-term Memory
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

    def _read_current_memory(self) -> str:
        if self.memory_file.exists():
            return self.memory_file.read_text(encoding="utf-8")
        # 如果文件不存在，返回初始模板
        return self.template_structure

    async def consolidate_background(self, recent_messages: list[dict]):
        """在后台异步执行的 memory 合并逻辑"""
        if not recent_messages:
            return
            
        current_memory = self._read_current_memory()
        dialogue = "\n".join([f"{m['role'].upper()}: {m['content']}" for m in recent_messages])
        
        # 获取当前时间
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        
        # 👉 3. 强化 Prompt
        prompt = f"""
        # 任务目标
        分析近期对话，提取长期事实，生成历史日志摘要。
        
        ## 提取的长期事实需要归为以下类别中：
        - ## User Information (用户的基本信息，如姓名、年龄、性别、职业、教育程度、收入、家庭情况、技能等)
        - ## Preferences (用户的偏好，如喜欢早上6:00起床，早餐喜欢喝牛奶等)
        - ## Project Context (用户正在推进的具体项目、长期目标、架构决策或关键文件的状态等)
        - ## Important Notes：(必须遵守的特殊规则、一起踩过的坑、或者动态产生的全局约束)
        如果新发现的事实与已有事实冲突，请将该事实以【更改】开头。
        如果没有新的，请原样返回现有的内容。
        
        ## 当前的长期事实内容 (MEMORY.md)
        {current_memory}
        
        ## 近期对话记录
        {dialogue}

        ## 当前时间
        {current_time}
        
        请注意：
        1、生成的历史日志摘要必须以 "[{current_time}]" 开头，例如 "[{current_time}] 用户提到了...".
        2、生成的长期事实内容必须严格遵循原本的长期事实内容结构。
        """

        try:
            logger.info("[MemoryManager] 开始后台记忆提取...")
            result: MemoryUpdateResponse = await self.llm.ainvoke([
                SystemMessage(content="你是一个遵循严格 Markdown 结构的记忆管理员助手。"),
                HumanMessage(content=prompt)
            ])
            
            # 写入 HISTORY.md（result.history_update 已包含正确时间戳）
            if result.history_update:
                with open(self.history_file, "a", encoding="utf-8") as f:
                    f.write(result.history_update.strip() + "\n\n")
            
            # 覆写 MEMORY.md 
            if result.memory_update and result.memory_update.strip() != current_memory.strip():
                self.memory_file.write_text(result.memory_update, encoding="utf-8")
                logger.info("[MemoryManager] MEMORY.md 已按照预设结构更新")
                
        except Exception as e:
            logger.error(f"[MemoryManager] 后台记忆更新失败: {e}")
            ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            with open(self.history_file, "a", encoding="utf-8") as f:
                f.write(f"[{ts}] [RAW ARCHIVE] {len(recent_messages)} messages dumped due to LLM error.\n\n")