import os
import asyncio
import yaml
from pathlib import Path
from typing import List, Optional

from langchain_core.tools import BaseTool
from utils.logger_handler import logger
from utils.helpers import get_abs_path
from .agent_tools import (
    web_search,
    bash_exec,
    read_file,
    write_file,
    edit_file,
    get_skill_details,
    cron_tool
)

class ToolRegistry:
    """
    统一工具注册中心：
    1. 管理本地原子工具 (Atomic Tools)
    2. 管理基于 Markdown 的技能文档 (Skills)
    3. 动态加载 MCP 外部工具
    """

    def __init__(self, workspace_path: Optional[Path] = None):
        self.workspace = workspace_path or Path.cwd()

        # 基础本地工具定义
        self._base_tools: List[BaseTool] = [
            web_search,
            bash_exec,
            read_file,
            write_file,
            edit_file,
            get_skill_details,
            cron_tool
            ]

        self._mcp_tools: List[BaseTool] = []
        self._last_mcp_config_hash = None

    def _load_mcp_tools_sync(self) -> List[BaseTool]:
        """同步包装异步 MCP 加载过程"""
        mcp_config_path = Path(get_abs_path("config/mcp.yml"))
        if not mcp_config_path.exists():
            return []

        try:
            from langchain_mcp_adapters.client import MultiServerMCPClient
        except ImportError:
            logger.warning("未安装 langchain-mcp-adapters，跳过 MCP 加载。")
            return []

        async def fetch_tools():
            config = yaml.safe_load(mcp_config_path.read_text(encoding="utf-8"))
            servers = {srv["name"]: srv for srv in config.get("servers", [])}

            async with MultiServerMCPClient(servers) as client:
                return await client.get_tools()

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import nest_asyncio
                nest_asyncio.apply()

            return asyncio.run(fetch_tools())
        except Exception as e:
            logger.error(f"MCP 工具加载失败: {e}")
            return []

    def get_all_tools(self, refresh_mcp: bool = False) -> List[BaseTool]:
        """
        获取所有工具。
        :param refresh_mcp: 是否强制重新扫描 MCP 配置文件
        """
        if refresh_mcp or not self._mcp_tools:
            self._mcp_tools = self._load_mcp_tools_sync()

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
def get_all_tools() -> List[BaseTool]:
    return registry.get_all_tools()
