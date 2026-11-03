"""Web 服务入口。

用 FastAPI 提供会话、聊天、历史记录和健康检查接口，并托管 static/ 页面。
当前轮次状态放在会话存储里，长期对话写入 MySQL。
"""
import logging
import os
import re
import uuid
from contextlib import asynccontextmanager
from typing import Literal, Any

from logging_config import configure_logging
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from chat_history import build_chat_history_store
from main_graph import (
    close_search_agent,
    get_search_agent_status,
    initialize_search_agent,
    run_session_turn,
)
from model.deepseek import My_model_client, get_llm_status
from session_store import SessionStore, build_session_store, create_initial_state

configure_logging()
logger = logging.getLogger(__name__)

PROJECT_ROOT = __import__("pathlib").Path(__file__).parent
STATIC_DIR = PROJECT_ROOT / "static"

session_store: SessionStore = build_session_store()
history_store = build_chat_history_store()
title_llm = My_model_client()
ANSWER_CACHE_ENABLED = os.getenv("ANSWER_CACHE_ENABLED", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
ANSWER_CACHE_MIN_QUERY_LENGTH = int(os.getenv("ANSWER_CACHE_MIN_QUERY_LENGTH", "12"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.search_agent_startup_error = None
    try:
        history_store.init_db()
        logger.info("Chat history store initialized")
    except Exception as exc:
        logger.exception("Chat history store initialization failed")
        raise
    try:
        initialize_search_agent()
        logger.info("Search agent initialized")
    except Exception as exc:
        app.state.search_agent_startup_error = f"{type(exc).__name__}: {exc}"
        logger.warning("Search agent startup failed: %s", exc)
    try:
        yield
    finally:
        close_search_agent()
        logger.info("Search agent closed")


fastapi_app = FastAPI(title="医疗多智能体问诊", lifespan=lifespan)
fastapi_app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


class ChatRequest(BaseModel):
    session_id: str
    message: str = Field(..., min_length=1, max_length=2000)


class ChatResponse(BaseModel):
    session_id: str
    status: Literal["asking", "complete"]
    reply: str
    turn_count: int


class SessionResponse(BaseModel):
    session_id: str


class SessionSummary(BaseModel):
    session_id: str
    title: str
    updated_at: float
    dialogue_complete: bool
    turn_count: int


class SessionDetail(BaseModel):
    session_id: str
    title: str
    messages: list[dict[str, str]]
    dialogue_complete: bool
    turn_count: int
    final_answer: str = ""


def _fallback_title(text: str) -> str:
    compact = re.sub(r"\s+", "", text or "")
    return compact[:10] or "新对话"


def generate_session_title(message: str) -> str:
    prompt = (
        "请为下面这段医疗问诊内容生成一个中文短标题，不超过10个字。"
        "只输出标题，不要标点，不要解释。"
    )
    try:
        title = title_llm.ask(query=message, system_prompt=prompt)
    except Exception as exc:
        logger.warning("Session title generation failed, using fallback: %s", exc)
        return _fallback_title(message)

    title = re.sub(r"[\s\"'“”‘’《》：:，,。.!！?？、；;]+", "", title or "")
    return (title[:10] or _fallback_title(message))


def state_from_history(history: dict) -> dict:
    state = create_initial_state(history["session_id"])
    messages = list(history.get("messages", []))
    state["title"] = history.get("title") or "新对话"
    state["dialogue_history"] = messages
    state["dialogue_complete"] = bool(history.get("dialogue_complete"))
    state["final_answer"] = history.get("final_answer", "")
    user_messages = [message["content"] for message in messages if message.get("role") == "user"]
    if user_messages:
        state["original_query"] = user_messages[0]
        state["raw_query"] = user_messages[-1]
    if state["dialogue_complete"]:
        state["dialogue_summary"] = state["final_answer"] or state["raw_query"]
    return state


@fastapi_app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@fastapi_app.get("/api/health")
async def health():
    search_agent = get_search_agent_status()
    session_store_health = session_store.health()
    llm = get_llm_status()
    return {
        "status": "ok"
        if search_agent["initialized"] and llm["configured"]
        else "degraded",
        "active_sessions": session_store_health["active_sessions"],
        "session_store": session_store_health,
        "history_store": history_store.health(),
        "search_agent": search_agent,
        "llm": llm,
        "answer_cache": {
            "enabled": ANSWER_CACHE_ENABLED,
            "min_query_length": ANSWER_CACHE_MIN_QUERY_LENGTH,
        },
    }


@fastapi_app.post("/api/session", response_model=SessionResponse)
async def create_session():
    session_id = str(uuid.uuid4())
    session_store.create(session_id)
    history_store.create_session(session_id)
    logger.info("Created session: %s", session_id)
    return SessionResponse(session_id=session_id)


@fastapi_app.get("/api/sessions", response_model=list[SessionSummary])
async def list_sessions():
    return history_store.list_sessions()


@fastapi_app.get("/api/session/{session_id}", response_model=SessionDetail)
async def get_session(session_id: str):
    history = history_store.get_session(session_id)
    if history is not None:
        session_store.set(session_id, state_from_history(history))
        return SessionDetail(
            session_id=history["session_id"],
            title=history["title"],
            messages=history["messages"],
            dialogue_complete=history["dialogue_complete"],
            turn_count=history["turn_count"],
            final_answer=history.get("final_answer", ""),
        )

    state = session_store.get(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    messages: list[dict[str, str]] = list(state.get("dialogue_history", []))
    final_answer = state.get("final_answer", "")
    if final_answer and (
        not messages
        or messages[-1].get("role") != "assistant"
        or messages[-1].get("content") != final_answer
    ):
        messages.append({"role": "assistant", "content": final_answer})
    return SessionDetail(
        session_id=session_id,
        title=state.get("title") or "新对话",
        messages=messages,
        dialogue_complete=bool(state.get("dialogue_complete")),
        turn_count=len(messages) // 2,
        final_answer=final_answer,
    )


@fastapi_app.post("/api/chat", response_model=ChatResponse)
async def chat(body: ChatRequest):
    state = session_store.get(body.session_id)
    if state is None:
        history = history_store.get_session(body.session_id)
        if history is None:
            raise HTTPException(status_code=404, detail="会话不存在，请刷新页面或新建对话")
        state = state_from_history(history)
        session_store.set(body.session_id, state)

    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="消息不能为空")

    if state.get("dialogue_complete"):
        state = create_initial_state(body.session_id)
        session_store.set(body.session_id, state)

    is_first_turn = not state.get("original_query") and not state.get("dialogue_history")
    if is_first_turn and state.get("title") in {None, "", "新对话"}:
        state["title"] = generate_session_title(message)
        session_store.set(body.session_id, state)
        history_store.sync_state(state)

    if (
        ANSWER_CACHE_ENABLED
        and is_first_turn
        and len(message) >= ANSWER_CACHE_MIN_QUERY_LENGTH
    ):
        cached_answer = session_store.get_cached_answer(message)
        if cached_answer:
            updated = create_initial_state(body.session_id)
            updated["original_query"] = message
            updated["raw_query"] = message
            updated["dialogue_complete"] = True
            updated["dialogue_summary"] = message
            updated["final_answer"] = cached_answer
            updated["dialogue_history"] = [
                {"role": "user", "content": message},
                {"role": "assistant", "content": cached_answer},
            ]
            session_store.set(body.session_id, updated)
            history_store.sync_state(updated)
            logger.info("Answer cache hit. session=%s", body.session_id)
            return ChatResponse(
                session_id=body.session_id,
                status="complete",
                reply=cached_answer,
                turn_count=1,
            )

    try:
        updated = run_session_turn(state, message)
    except Exception as exc:
        logger.exception("Chat turn failed for session %s", body.session_id)
        raise HTTPException(status_code=500, detail=f"处理失败: {exc}") from exc

    session_store.set(body.session_id, updated)
    history_store.sync_state(updated)
    turn_count = len(updated.get("dialogue_history", [])) // 2
    if (
        ANSWER_CACHE_ENABLED
        and updated.get("dialogue_complete")
        and updated.get("final_answer")
        and turn_count <= 1
        and len(updated.get("original_query", "")) >= ANSWER_CACHE_MIN_QUERY_LENGTH
    ):
        session_store.set_cached_answer(
            updated["original_query"],
            updated["final_answer"],
        )
        logger.info("Answer cached. session=%s", body.session_id)
    logger.info(
        "Processed chat turn. session=%s complete=%s turn_count=%s",
        body.session_id,
        updated.get("dialogue_complete"),
        turn_count,
    )

    if updated.get("dialogue_complete"):
        return ChatResponse(
            session_id=body.session_id,
            status="complete",
            reply=updated.get("final_answer", ""),
            turn_count=turn_count,
        )

    reply = updated.get("final_answer") or updated.get("assistant_reply", "")
    return ChatResponse(
        session_id=body.session_id,
        status="asking",
        reply=reply,
        turn_count=turn_count,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api:fastapi_app", host="0.0.0.0", port=8088, reload=False)
