import uuid
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from agent.react_agent import ReactAgent

app = FastAPI()

# 全局 agent 实例（复用同一个 checkpointer 连接）
agent = ReactAgent()

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/favicon.ico")
def favicon():
    return Response(status_code=204)

@app.get("/")
def index():
    return FileResponse("static/index.html")


# ---------- 数据模型 ----------
class ChatRequest(BaseModel):
    message: str


# ---------- 会话管理 ----------
@app.get("/threads")
def get_threads():
    all_ids = agent.get_all_threads()
    threads = []
    for tid in all_ids:
        history = agent.get_history(tid)
        title = "新对话"
        first_user = next((m["content"] for m in history if m["role"] == "user"), None)
        if first_user:
            title = first_user[:20] + ("..." if len(first_user) > 20 else "")
        threads.append({"thread_id": tid, "title": title})
    # 若数据库为空，返回一个默认会话
    if not threads:
        threads = [{"thread_id": "default", "title": "新对话"}]
    return threads

@app.post("/threads")
def create_thread():
    new_id = uuid.uuid4().hex
    return {"thread_id": new_id, "title": "新对话"}

@app.delete("/threads/{thread_id}")
def delete_thread(thread_id: str):
    agent.delete_thread(thread_id)
    return {"ok": True}


@app.get("/threads/{thread_id}/messages")
def get_messages(thread_id: str):
    return agent.get_history(thread_id)


# ---------- 流式对话 ----------
@app.post("/threads/{thread_id}/chat")
def chat(thread_id: str, req: ChatRequest):
    def generate():
        for token in agent.execute_stream(req.message, thread_id=thread_id):
            yield f"data: {token}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"X-Accel-Buffering": "no", 
                                      "Cache-Control": "no-cache",
                                      "Connection": "keep-alive"})
