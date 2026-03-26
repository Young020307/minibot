import os
import time
import uuid
import streamlit as st
from agent.react_agent import ReactAgent

# ---------- 页面配置 ----------
st.set_page_config(page_title="智能助手", layout="wide")
st.title("智能助手 🤖")
st.divider()

# 确保图片临时上传目录存在
UPLOAD_DIR = "tmp_uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ---------- 初始化 session_state ----------
if "agent" not in st.session_state:
    st.session_state["agent"] = ReactAgent()

# 存储所有对话的元信息（thread_id 和标题）
if "threads" not in st.session_state:
    all_threads = st.session_state["agent"].get_all_threads()
    if all_threads:
        threads = []
        for tid in all_threads:
            history = st.session_state["agent"].get_history(tid)
            title = "未命名对话"
            if history:
                # 寻找第一条用户消息作为标题
                for m in history:
                    if m["role"] == "user":
                        # 处理多模态内容（如果是列表，取文本部分）
                        content = m["content"]
                        text_content = content if isinstance(content, str) else next((item["text"] for item in content if item.get("type") == "text"), "")
                        if text_content:
                            # 过滤掉注入的 Runtime Context
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
                    st.session_state["agent"].delete_thread(thread["thread_id"])
                    st.session_state["threads"] = [t for t in st.session_state["threads"] if t["thread_id"] != thread["thread_id"]]
                    if st.session_state["current_thread"] == thread["thread_id"]:
                        st.session_state["current_thread"] = st.session_state["threads"][0]["thread_id"]
                    st.rerun()
    
    st.divider()
    st.subheader("📎 附件上传")
    uploaded_files = st.file_uploader("上传图片给 AI (可选)", type=["png", "jpg", "jpeg"], accept_multiple_files=True)

# ---------- 主区域：显示当前对话的消息 ----------
current_thread = st.session_state["current_thread"]
history = st.session_state["agent"].get_history(thread_id=current_thread)

def render_message_content(content):
    """渲染可能包含图片和 Runtime Context 的多模态消息"""
    if isinstance(content, str):
        # 纯文本模式下过滤上下文
        display_text = content.split("\n\n", 1)[-1] if "[Runtime Context" in content else content
        st.markdown(display_text)
    elif isinstance(content, list):
        # 多模态列表模式
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    text = item.get("text", "")
                    # 过滤掉不需要让用户看到的系统时间戳
                    if "[Runtime Context" in text:
                        text = text.split("\n\n", 1)[-1] if "\n\n" in text else ""
                    if text.strip():
                        st.markdown(text)
                elif item.get("type") == "image_url":
                    # 渲染 Base64 图片
                    img_data = item["image_url"]["url"]
                    st.image(img_data, width=300)

for message in history:
    with st.chat_message(message["role"]):
        render_message_content(message["content"])

# ---------- 用户输入 ----------
prompt = st.chat_input("输入你的问题...")

if prompt:
    # 1. 处理上传的图片附件
    media_paths = []
    if uploaded_files:
        for f in uploaded_files:
            file_path = os.path.join(UPLOAD_DIR, f.name)
            with open(file_path, "wb") as out:
                out.write(f.read())
            media_paths.append(file_path)

    # 2. 界面上先显示用户输入的内容（优化体验，不刷新页面立即显示）
    with st.chat_message("user"):
        st.markdown(prompt)
        for path in media_paths:
            st.image(path, width=300)

    # 3. 更新对话标题（如果是新对话）
    if len(history) == 0:
        new_title = prompt[:20] + ("..." if len(prompt) > 20 else "")
        for t in st.session_state["threads"]:
            if t["thread_id"] == current_thread:
                t["title"] = new_title
                break

    # 4. 调用 agent 流式生成回复
    with st.spinner("思考中..."):
        # 注意这里传入了 media_paths 数组
        response_generator = st.session_state["agent"].execute_stream(
            prompt, 
            thread_id=current_thread, 
            media=media_paths
        )

        def capture_and_stream(generator, cache):
            for chunk in generator:
                cache.append(chunk)
                for char in chunk:
                    time.sleep(0.01)
                    yield char

        response_chunks = []
        with st.chat_message("assistant"):
            st.write_stream(capture_and_stream(response_generator, response_chunks))

    # 5. 执行完毕后刷新页面，加载正式的结构化历史记录
    st.rerun()