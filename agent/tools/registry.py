# agent/tools/registry.py
"""
工具注册表：统一管理本地技能工具和 MCP 外部工具。
本地工具：
  - web_search       : Tavily 网络搜索
  - bash_exec        : 执行 shell 命令（为 weather/github/tmux 等 CLI skill 提供运行时）
  - read_file        : 读取文件内容
  - write_file       : 写入文件内容
  - edit_file        : 追加内容到文件
  - list_skills      : 列出所有可用 skill 及其说明

MCP 工具（可选）：
  - 读取 config/mcp.yml，连接配置的 MCP Server，动态转换为 LangChain Tools
"""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

import yaml
from langchain_core.tools import  BaseTool
from utils.logger_handler import logger
from utils.path_tool import get_abs_path
from .agent_tools import (
    web_search,
    bash_exec,
    read_file,
    write_file,
    edit_file,
    list_skills
)

# ─────────────────────────────────────────────
# Skills 文档上下文构建
# ─────────────────────────────────────────────
from .agent_tools import _scan_skills

def build_skills_context() -> str:
    """
    将所有 SKILL.md 的正文拼接为上下文字符串，
    供 context.py 注入 system prompt（尤其是 always=true 的技能）。
    """
    skills = _scan_skills()
    if not skills:
        return ""
    sections = []
    for s in skills:
        header = f"## Skill: {s['name']}\n_{s['description']}_"
        sections.append(f"{header}\n\n{s['body']}")
    return "# 已加载技能文档\n\n" + "\n\n---\n\n".join(sections)

# ─────────────────────────────────────────────
# MCP 工具加载（可选）
# ─────────────────────────────────────────────

def _load_mcp_tools() -> list[BaseTool]:
    """
    从 config/mcp.yml 读取 MCP Server 配置，动态加载工具。
    若配置文件不存在或依赖未安装，静默跳过。

    mcp.yml 格式示例：
      servers:
        - name: filesystem
          transport: stdio
          command: npx
          args: ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
        - name: my_sse_server
          transport: sse
          url: http://localhost:8080/sse
    """
    mcp_config_path = Path(get_abs_path("config/mcp.yml"))
    if not mcp_config_path.exists():
        logger.debug("[registry] config/mcp.yml 不存在，跳过 MCP 工具加载")
        return []

    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient
    except ImportError:
        logger.warning("[registry] langchain-mcp-adapters 未安装，跳过 MCP 工具加载。"
                       "安装命令: pip install langchain-mcp-adapters")
        return []

    try:
        config = yaml.safe_load(mcp_config_path.read_text(encoding="utf-8"))
        servers = config.get("servers", [])
        if not servers:
            return []

        mcp_servers = {}
        for srv in servers:
            name = srv["name"]
            transport = srv.get("transport", "stdio")
            if transport == "stdio":
                mcp_servers[name] = {
                    "command": srv["command"],
                    "args": srv.get("args", []),
                    "transport": "stdio",
                }
            elif transport == "sse":
                mcp_servers[name] = {
                    "url": srv["url"],
                    "transport": "sse",
                }

        import asyncio

        async def _fetch():
            async with MultiServerMCPClient(mcp_servers) as client:
                return client.get_tools()

        tools = asyncio.run(_fetch())
        logger.info(f"[registry] 已加载 {len(tools)} 个 MCP 工具: {[t.name for t in tools]}")
        return tools
    except Exception as e:
        logger.error(f"[registry] MCP 工具加载失败: {e}")
        return []


# ─────────────────────────────────────────────
# 统一注册入口
# ─────────────────────────────────────────────

BASE_TOOLS: list[BaseTool] = [
    web_search,
    bash_exec,
    read_file,
    write_file,
    edit_file,
    list_skills,
]

def get_all_tools() -> list[BaseTool]:
    """
    返回所有可用工具：本地基础工具 + MCP 外部工具。
    每次调用都会重新尝试加载 MCP 工具（支持热更新配置）。
    """
    mcp_tools = _load_mcp_tools()
    all_tools = BASE_TOOLS + mcp_tools
    logger.info(f"[registry] 共注册 {len(all_tools)} 个工具: {[t.name for t in all_tools]}")
    return all_tools