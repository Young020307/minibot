import asyncio
from pathlib import Path
from utils.logger_handler import logger

from agent.react_agent import ReactAgent
from agent.heartbeat.service import HeartbeatService
from model.dashscope import DashScopeProvider

async def main():
    # 1. 初始化 ReactAgent (执行器)
    agent = ReactAgent()
    logger.info("ReactAgent 启动成功。")

    # 2. 定义回调函数：当心跳服务发现任务时，该怎么做？
    async def on_heartbeat_execute(tasks: str) -> str:
        logger.info(f"👉 收到心跳任务，转交 Agent 执行: {tasks}")
        # 调用我们刚刚在 ReactAgent 中新增的方法
        response = await agent.execute_background_task(tasks, thread_id="background_tasks")
        return response

    # 3. 定义通知函数：Agent 觉得需要通知时，发往哪里？
    async def on_heartbeat_notify(response: str):
        # 这里可以接入微信、钉钉、Telegram 或前端 WebSocket 弹窗
        logger.info(f"🔔 【系统通知】 Agent 完成了后台任务:\n{response}")

    # 4. 初始化心跳服务 (触发器)
    # 注意：需要传入 HeartbeatService 所需的 provider，你可以复用 ReactAgent 里的模型对象
    heartbeat = HeartbeatService(
        workspace=Path(__file__).resolve().parent, # 指向你的工作区
        provider=DashScopeProvider(), # 替换为 HeartbeatService 需要的 Provider 实例
        model="qwen-max",             # 替换为你的模型名
        interval_s= 60*30 ,          # 例如 30 分钟检查一次
        on_execute=on_heartbeat_execute,
        on_notify=on_heartbeat_notify
    )

    # 5. 启动心跳服务 (后台运行)
    await heartbeat.start()

    # 保持主程序运行 
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        heartbeat.stop()
        logger.info("系统关闭。")

if __name__ == "__main__":
    asyncio.run(main())