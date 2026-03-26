import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))
from abc import ABC, abstractmethod
from langchain_community.chat_models.tongyi import BaseChatModel
from langchain_community.chat_models.tongyi import ChatTongyi
from utils.config_handler import agent_conf

class BaseModelFactory(ABC):
    @abstractmethod
    def generator(self) -> BaseChatModel:
        pass

class ChatModelFactory(BaseModelFactory):
    def generator(self) -> BaseChatModel:
        return ChatTongyi(model=agent_conf["chat_model_name"])

class MemoryModelFactory(BaseModelFactory):
    def generator(self) -> BaseChatModel:
        return ChatTongyi(model=agent_conf["memory_model_name"])
    
chat_model = ChatModelFactory().generator()
memory_model = MemoryModelFactory().generator()

