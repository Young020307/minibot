let currentThreadId = null;
let threads = [];  // [{thread_id, title}]

// ---------- 初始化 ----------
async function init() {
  threads = await fetch("/threads").then(r => r.json());
  if (threads.length === 0) {
    const t = await fetch("/threads", { method: "POST" }).then(r => r.json());
    threads = [t];
  }
  renderThreadList();
  await switchThread(threads[0].thread_id);
}

// ---------- 渲染侧边栏 ----------
function renderThreadList() {
  const list = document.getElementById("thread-list");
  list.innerHTML = "";
  threads.forEach(t => {
    const item = document.createElement("div");
    item.className = "thread-item" + (t.thread_id === currentThreadId ? " active" : "");
    item.dataset.id = t.thread_id;

    const title = document.createElement("span");
    title.className = "thread-title";
    title.textContent = t.title;

    const delBtn = document.createElement("button");
    delBtn.className = "btn-del";
    delBtn.textContent = "🗑";
    delBtn.onclick = (e) => { e.stopPropagation(); deleteThread(t.thread_id); };

    item.appendChild(title);
    if (threads.length > 1) item.appendChild(delBtn);
    item.onclick = () => switchThread(t.thread_id);
    list.appendChild(item);
  });
}

// ---------- 切换会话 ----------
async function switchThread(threadId) {
  currentThreadId = threadId;
  renderThreadList();
  const messages = await fetch(`/threads/${threadId}/messages`).then(r => r.json());
  const box = document.getElementById("messages");
  box.innerHTML = "";
  messages.forEach(m => appendMessage(m.role, m.content));
  scrollToBottom();
}

// ---------- 新建会话 ----------
document.getElementById("btn-new").onclick = async () => {
  const t = await fetch("/threads", { method: "POST" }).then(r => r.json());
  threads.unshift(t);
  renderThreadList();
  await switchThread(t.thread_id);
};

// ---------- 删除会话 ----------
async function deleteThread(threadId) {
  await fetch(`/threads/${threadId}`, { method: "DELETE" });
  threads = threads.filter(t => t.thread_id !== threadId);
  if (threads.length === 0) {
    const t = await fetch("/threads", { method: "POST" }).then(r => r.json());
    threads = [t];
  }
  renderThreadList();
  if (currentThreadId === threadId) {
    await switchThread(threads[0].thread_id);
  }
}

// ---------- 发送消息 ----------
async function sendMessage() {
  const input = document.getElementById("input");
  const msg = input.value.trim();
  if (!msg) return;

  input.value = "";
  input.style.height = "auto";
  document.getElementById("btn-send").disabled = true;

  // 更新标题（首条消息）
  const thread = threads.find(t => t.thread_id === currentThreadId);
  if (thread && thread.title === "新对话") {
    thread.title = msg.slice(0, 20) + (msg.length > 20 ? "..." : "");
    renderThreadList();
  }

  appendMessage("user", msg);
  scrollToBottom();

  // 创建 assistant 气泡（流式填充）
  const bubble = appendMessage("assistant", "");
  scrollToBottom();

  const resp = await fetch(`/threads/${currentThreadId}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message: msg }),
  });

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    // 用双换行分割 SSE 事件
    const events = buffer.split("\n\n");
    buffer = events.pop();  // 保留最后一个不完整事件
    for (const event of events) {
      const line = event.trim();
      if (!line.startsWith("data: ")) continue;
      const data = line.slice(6);
      if (data === "[DONE]") break;
      bubble.textContent += data;
      scrollToBottom();
    }
  }

  document.getElementById("btn-send").disabled = false;
}

document.getElementById("btn-send").onclick = sendMessage;

document.getElementById("input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

// 自动撑高输入框
document.getElementById("input").addEventListener("input", function () {
  this.style.height = "auto";
  this.style.height = Math.min(this.scrollHeight, 120) + "px";
});

// ---------- 工具函数 ----------
function appendMessage(role, content) {
  const box = document.getElementById("messages");
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  div.textContent = content;
  box.appendChild(div);
  return div;
}

function scrollToBottom() {
  const box = document.getElementById("messages");
  box.scrollTop = box.scrollHeight;
}

init();
