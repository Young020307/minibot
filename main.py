from agent.react_agent import ReactAgent
import asyncio

async def main():
    # ✅ 实例化 + 初始化，心跳自动绑定启动
    agent = ReactAgent()
    await agent.initialize()

    thread_id = "terminal_session_01"
    print("==================================================")
    print("🤖 你的专属助手已启动！")
    print("💡 提示：输入 'exit' 或按下 Ctrl + C 即可结束对话。")
    print("==================================================")

    try:
        while True:
            user_input = (await asyncio.to_thread(input, "\n😃 Young: ")).strip()

            if not user_input:
                continue

            if user_input.lower() in ['exit', 'quit']:
                print("\n👋 收到!助手已下线，咱们下次聊。")
                break

            print("🤖 助手: ", end="", flush=True)

            async for chunk in agent.execute_stream(user_input, thread_id=thread_id):
                print(chunk, end="", flush=True)

            print()

    except KeyboardInterrupt:
        print("\n\n🛑 检测到中断信号 (Ctrl+C)，强制退出对话。拜拜！")
    except Exception as e:
        import traceback
        print(f"\n❌ 哎呀，出错了: {e}")
        traceback.print_exc()
    finally:
        await agent.close()

if __name__ == "__main__":
    asyncio.run(main())