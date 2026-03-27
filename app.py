import os
import time
import uuid
import asyncio
import threading
import queue
import streamlit as st
from agent.react_agent import ReactAgent

# ---------- Async Runner Helper (核心桥接层) ----------
# 解决 Streamlit 刷新导致 aiosqlite 连接不同 Loop 的问题
def start_background_loop(loop: asyncio.AbstractEventLoop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

if "async_loop" not in st.session_state:
    _loop = asyncio.new_event_loop()
    st.session_state["async_loop"] = _loop
    # 开启一个后台守护线程专门跑 async 事件循环
    t = threading.Thread(target=start_background_loop, args=(_loop,), daemon=True)
    t.start()

def run_async(coro):
    """在后台事件循环中同步执行异步函数，并返回结果"""
    future = asyncio.run_coroutine_threadsafe(coro, st.session_state["async_loop"])
    return future.result()


# ---------- 页面配置 ----------
st.set_page_config(page_title="智能助手", layout="wide")
st.title("智能助手 🤖")
st.divider()

# 确保图片临时上传目录存在
UPLOAD_DIR = "tmp_uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ---------- 初始化 session_state ----------
if "agent" not in st.session_state:
    agent = ReactAgent()
    # 异步初始化 Agent（加载数据库、心跳等）
    run_async(agent.initialize())
    st.session_state["agent"] = agent

# 存储所有对话的元信息（thread_id 和标题）
if "threads" not in st.session_state:
    # 异步获取历史线程
    all_threads = run_async(st.session_state["agent"].get_all_threads())
    if all_threads:
        threads = []
        for tid in all_threads:
            # 异步获取具体记录
            history = run_async(st.session_state["agent"].get_history(tid))
            title = "未命名对话"
            if history:
                for m in history:
                    if m["role"] == "user":
                        content = m["content"]
                        text_content = content if isinstance(content, str) else next((item["text"] for item in content if item.get("type") == "text"), "")
                        if text_content:
                            if "[Runtime Context" in text_content:
                                text_content = text_content.split("\n\n", 1)[-1] if "\n\n" in text_content else text_content
                            title = text_content[:20] + ("..." if len(text_content) > 20 else "")
                            break
            threads.append({"thread_id": tid, "title": title})
        st.session_state["threads"] = threads
        st.session_state["current_thread"] = threads[0]["thread_id"]
    else:
        default_id = "default"
        st.session_state["threads"] = [{"thread_id": default_id, "title": "新对话"}]
        st.session_state["current_thread"] = default_id
else:
    if st.session_state["current_thread"] not in [t["thread_id"] for t in st.session_state["threads"]]:
        st.session_state["current_thread"] = st.session_state["threads"][0]["thread_id"]

# ---------- 侧边栏：对话管理与附件 ----------
with st.sidebar:
    st.header("对话管理")

    if st.button("➕ 新对话"):
        new_id = uuid.uuid4().hex
        st.session_state["threads"].append({"thread_id": new_id, "title": "新对话"})
        st.session_state["current_thread"] = new_id
        st.rerun()

    st.divider()
    st.subheader("对话列表")

    for idx, thread in enumerate(st.session_state["threads"]):
        col1, col2 = st.columns([4, 1])
        with col1:
            button_label = f"✅ {thread['title']}" if thread["thread_id"] == st.session_state["current_thread"] else thread["title"]
            if st.button(button_label, key=f"thread_{thread['thread_id']}", use_container_width=True):
                if thread["thread_id"] != st.session_state["current_thread"]:
                    st.session_state["current_thread"] = thread["thread_id"]
                    st.rerun()
        with col2:
            if len(st.session_state["threads"]) > 1:
                if st.button("🗑️", key=f"del_{thread['thread_id']}"):
                    # 异步删除线程
                    run_async(st.session_state["agent"].delete_thread(thread["thread_id"]))
                    st.session_state["threads"] = [t for t in st.session_state["threads"] if t["thread_id"] != thread["thread_id"]]
                    if st.session_state["current_thread"] == thread["thread_id"]:
                        st.session_state["current_thread"] = st.session_state["threads"][0]["thread_id"]
                    st.rerun()
    
    st.divider()
    st.subheader("📎 附件上传")
    uploaded_files = st.file_uploader("上传图片给 AI (可选)", type=["png", "jpg", "jpeg"], accept_multiple_files=True)

# ---------- 主区域：显示当前对话的消息 ----------
current_thread = st.session_state["current_thread"]
# 异步获取当前线程历史
history = run_async(st.session_state["agent"].get_history(thread_id=current_thread))

def render_message_content(content):
    """渲染可能包含图片和 Runtime Context 的多模态消息"""
    if isinstance(content, str):
        display_text = content.split("\n\n", 1)[-1] if "[Runtime Context" in content else content
        st.markdown(display_text)
    elif isinstance(content, list):
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    text = item.get("text", "")
                    if "[Runtime Context" in text:
                        text = text.split("\n\n", 1)[-1] if "\n\n" in text else ""
                    if text.strip():
                        st.markdown(text)
                elif item.get("type") == "image_url":
                    img_data = item["image_url"]["url"]
                    st.image(img_data, width=300)

for message in history:
    with st.chat_message(message["role"]):
        render_message_content(message["content"])

# ---------- 用户输入 ----------
prompt = st.chat_input("输入你的问题...")

if prompt:
    media_paths = []
    if uploaded_files:
        for f in uploaded_files:
            file_path = os.path.join(UPLOAD_DIR, f.name)
            with open(file_path, "wb") as out:
                out.write(f.read())
            media_paths.append(file_path)

    with st.chat_message("user"):
        st.markdown(prompt)
        for path in media_paths:
            st.image(path, width=300)

    if len(history) == 0:
        new_title = prompt[:20] + ("..." if len(prompt) > 20 else "")
        for t in st.session_state["threads"]:
            if t["thread_id"] == current_thread:
                t["title"] = new_title
                break

    # 4. 调用 agent 流式生成回复（通过队列桥接异步生成器和同步前端）
    with st.spinner("思考中..."):
        def stream_response(query, tid, medias):
            q = queue.Queue()
            
            # 👈 核心修复点 1：在主线程提前将 agent 取出，赋值给局部变量
            current_agent = st.session_state["agent"]
            
            async def _stream():
                try:
                    kwargs = {"thread_id": tid}
                    if medias: 
                        kwargs["media"] = medias 
                        
                    # 👈 核心修复点 2：这里使用 current_agent，而不是 st.session_state["agent"]
                    async for chunk in current_agent.execute_stream(query, **kwargs):
                        q.put(chunk)
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    q.put(f"\n[Error] {str(e)}")
                finally:
                    q.put(None) # 发送结束信号

            # 提交到后台循环执行
            asyncio.run_coroutine_threadsafe(_stream(), st.session_state["async_loop"])
            
            # 主线程同步读取队列并 yield 给 st.write_stream
            while True:
                chunk = q.get()
                if chunk is None:
                    break
                yield chunk

        with st.chat_message("assistant"):
            st.write_stream(stream_response(prompt, current_thread, media_paths))

    st.rerun()