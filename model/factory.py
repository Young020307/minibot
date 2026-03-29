import os
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))
from langchain_community.chat_models.tongyi import ChatTongyi
from langchain_openai import ChatOpenAI
from utils.config_handler import agent_conf

# 对话模型（保持原样）
chat_model = ChatOpenAI(
    model="qwen-turbo", 
    api_key=os.environ.get("DASH_SCOPE_API_KEY"),
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    max_retries=3,
)

# 记忆模型 → 改成和上面一样的简洁格式
memory_model = ChatTongyi(
    model=agent_conf["memory_model_name"],
    verbose=False,

    # 如果你需要加 api_key，就补上这行：
    # api_key=os.environ.get("DASH_SCOPE_API_KEY"),
)