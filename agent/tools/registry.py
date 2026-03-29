import os
import yaml
from pathlib import Path
from typing import List, Optional

from langchain_core.tools import BaseTool
from utils.logger_handler import logger
from utils.helpers import get_abs_path
from .agent_tools import (
    write_file,
    edit_file,
    get_skill_details,
    cron_tool
)

class ToolRegistry:
    """
    统一工具注册中心：
    1. 注册本地工具
    2. 注册 MCP 工具
    """

    def __init__(self, workspace_path: Optional[Path] = None):
        self.workspace = workspace_path or Path.cwd()

        # 基础本地工具定义
        self._base_tools: List[BaseTool] = [
            write_file,
            edit_file,
            get_skill_details,
            cron_tool
            ]

        self._mcp_tools: List[BaseTool] = []
        self._mcp_client = None

    async def _load_mcp_tools_async(self) -> List[BaseTool]:
        """👉 修改 2: 改为原生异步方法，确保与 Agent 在同一个主事件循环中"""
        mcp_config_path = Path(get_abs_path("config/mcp.yml"))
        if not mcp_config_path.exists():
            return []

        try:
            from langchain_mcp_adapters.client import MultiServerMCPClient
        except ImportError:
            logger.warning("未安装 langchain-mcp-adapters，跳过 MCP 加载。")
            return []

        try:
            # 直接加载 YAML，它解析出来的字典就是 MultiServerMCPClient 需要的格式
            config = yaml.safe_load(mcp_config_path.read_text(encoding="utf-8"))
            
            # 直接传入配置，不再需要遍历和 pop
            self._mcp_client = MultiServerMCPClient(config)
            
            # 直接 await 获取工具
            tools = await self._mcp_client.get_tools()
            return tools
            
        except Exception as e:
            logger.error(f"MCP 工具加载失败: {e}")
            return []

    async def get_all_tools(self, refresh_mcp: bool = False) -> List[BaseTool]:
        """👉 修改 4: 改为异步方法"""
        if refresh_mcp or not self._mcp_tools:
            self._mcp_tools = await self._load_mcp_tools_async()

        all_tools = self._base_tools + self._mcp_tools
        logger.info(f"注册表更新: {len(self._base_tools)} 本地, {len(self._mcp_tools)} MCP")
        return all_tools

# ─────────────────────────────────────────────
# 单例实例化
# ─────────────────────────────────────────────
registry = ToolRegistry(workspace_path=Path(os.getcwd()))

# ─────────────────────────────────────────────
# 接口（供 react_agent.py 等调用）
# ─────────────────────────────────────────────
async def get_all_tools() -> List[BaseTool]:
    """👉 修改 5: 对外暴露的接口也改为异步"""
    return await registry.get_all_tools()
