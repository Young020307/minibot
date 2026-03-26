import os
import asyncio
import yaml
from pathlib import Path
from typing import List, Dict, Any, Optional

from langchain_core.tools import BaseTool
from utils.logger_handler import logger
from utils.path_tool import get_abs_path

# 导入之前的 SkillsLoader
from skills import SkillsLoader 
from .agent_tools import (
    web_search,
    bash_exec,
    read_file,
    write_file,
    edit_file,
    list_skills
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
        # 初始化技能加载器
        self.skills_loader = SkillsLoader(workspace=self.workspace)
        
        # 基础本地工具定义
        self._base_tools: List[BaseTool] = [
            web_search,
            bash_exec,
            read_file,
            write_file,
            edit_file,
            list_skills,
        ]
        
        self._mcp_tools: List[BaseTool] = []
        self._last_mcp_config_hash = None

    def build_discovery_skills(self) -> str:
        """生成发现层信息：仅包含技能名和简短描述"""
        skills = self.skills_loader.list_skills(filter_unavailable=True)
        if not skills:
            return "当前无可用技能。"
        
        lines = ["# 可用技能索引 (Discovery Layer)", "你可以通过 'get_skill_details' 工具查看以下技能的详细操作指南："]
        for s in skills:
            desc = self.skills_loader._get_skill_description(s["name"])
            lines.append(f"- {s['name']}: {desc}")
        
        return "\n".join(lines)

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
            # 这里简单实现，生产环境建议维护长连接 client
            config = yaml.safe_load(mcp_config_path.read_text(encoding="utf-8"))
            servers = {srv["name"]: srv for srv in config.get("servers", [])}
            
            async with MultiServerMCPClient(servers) as client:
                return await client.get_tools()

        try:
            # 兼容已有事件循环的环境
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 如果在异步环境下运行（如 FastAPI/LangGraph），需特殊处理
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
# 获取当前工作目录作为默认 workspace
registry = ToolRegistry(workspace_path=Path(os.getcwd()))

# 向后兼容原有的函数接口
def build_skills_context():
    return registry.build_skills_context()

def get_all_tools():
    return registry.get_all_tools()