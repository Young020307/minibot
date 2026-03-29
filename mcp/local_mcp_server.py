# C:\Users\Younson\Desktop\Agent\minibot\mcp_server.py
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from mcp.server.fastmcp import FastMCP
import subprocess
from pathlib import Path
from utils.config_handler import api_conf
from tavily import TavilyClient

# 初始化一个名为 MinibotTools 的 MCP Server
mcp = FastMCP("MinibotTools")

#初始化Tavily
tavily_client = TavilyClient(api_key=api_conf.get("TAVILY_API_KEY"))

@mcp.tool()
def bash_exec(command: str, timeout: int = 60) -> str:
    """Run a shell command and return stdout+stderr."""
    _BLOCKED = ["rm -rf /", "format ", "dd if=", "shutdown", "mkfs"]
    if any(b in command for b in _BLOCKED):
        return f"[拒绝] 该命令已被安全策略阻止：{command}"
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = (result.stdout + result.stderr).strip()
        if len(output) > 10000:
            output = output[:10000] + "\n...[输出已截断]"
        return output or "(无输出)"
    except subprocess.TimeoutExpired:
        return f"[超时] 命令执行超过 {timeout} 秒"
    except Exception as e:
        return f"[错误] {e}"

@mcp.tool()
def read_file(path: str) -> str:
    """Read a file and return its text content."""
    try:
        # 这里为了演示简化了路径处理，实际可保留你原本的 get_abs_path 逻辑
        p = Path(path)
        return p.read_text(encoding="utf-8")
    except Exception as e:
        return f"[错误] 无法读取文件 {path}: {e}"
    
@mcp.tool()
def web_search(query: str) -> str:
    """Search the web and return the results."""
    search_results = tavily_client.search(
        query = query,
        search_depth = "basic",  # 爬取方式网页正文
        max_results=3,  # 控制返回结果数量，避免Agent处理过载
        include_answer=True,  # 返回AI总结的答案
        include_raw_content=False  # 简化结果，只返回摘要（如需完整内容可改为True）
    )
    # 格式化结果（让Agent更容易理解和使用）
    formatted_results = []
    # 优先用Tavily的AI总结答案
    if search_results.get("answer"):
        formatted_results.append(f"【AI网页总结】: {search_results['answer']}\n")
    # 补充原始搜索结果（带来源，增强可信度）
    for idx, result in enumerate(search_results["results"], 1):
        formatted_results.append(
            f"【结果{idx}】\n"
            f"标题: {result['title']}\n"
            f"链接: {result['url']}\n"
            f"内容: {result['content'][:500]}...\n"  # 截断过长内容
        )
    return "\n".join(formatted_results)


if __name__ == "__main__":
    # 以 stdio 模式运行 MCP Server
    mcp.run()