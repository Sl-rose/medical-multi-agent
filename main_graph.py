"""LangGraph 工作流：把四个智能体串成一轮问诊。

先识别意图，再决定继续追问还是检索知识并生成回答。
检索组件启动失败时服务仍可响应，但相关能力会在健康检查里标为不可用。
"""
import os
import logging
from pathlib import Path
from typing import TypedDict, List, Dict, Any, TYPE_CHECKING

from dotenv import load_dotenv
from langgraph.graph import StateGraph, START, END

from agent.agent1 import run_intent_detection_agent, run_search_intent_refresh
from agent.agent2 import run_dialogue_agent
from agent.agent4 import run_answer_synthesizer_agent

if TYPE_CHECKING:
    from agent.agent3 import MedicalKnowledgeSearchAgent

load_dotenv()

PROJECT_ROOT = Path(__file__).parent
MEDICAL_INTENTS = {"健康咨询", "报告解读", "用药指导"}
logger = logging.getLogger(__name__)

search_agent_instance: "MedicalKnowledgeSearchAgent | None" = None
search_agent_error: str | None = None


def initialize_search_agent() -> "MedicalKnowledgeSearchAgent":
    """Initialize external search dependencies when the application starts."""
    global search_agent_instance, search_agent_error
    if search_agent_instance is None:
        from agent.agent3 import MedicalKnowledgeSearchAgent

        try:
            logger.info("Initializing search agent")
            search_agent_instance = MedicalKnowledgeSearchAgent(
                chroma_path=os.getenv("CHROMA_PATH") or str(PROJECT_ROOT / "chromadb"),
                neo4j_uri=os.getenv("NEO4J_URI", "neo4j://127.0.0.1:7687"),
                neo4j_auth=(
                    os.getenv("NEO4J_USER", "neo4j"),
                    os.getenv("NEO4J_PASSWORD", ""),
                ),
            )
            search_agent_error = None
        except Exception as exc:
            search_agent_error = f"{type(exc).__name__}: {exc}"
            logger.exception("Search agent initialization failed")
            raise
    return search_agent_instance


def close_search_agent() -> None:
    """Release external search resources when the application stops."""
    global search_agent_instance
    if search_agent_instance is not None:
        search_agent_instance.close()
        search_agent_instance = None
        logger.info("Search agent resource released")


def get_search_agent_status() -> dict:
    """Return non-sensitive runtime status for health checks."""
    return {
        "initialized": search_agent_instance is not None,
        "chroma_path": os.getenv("CHROMA_PATH") or str(PROJECT_ROOT / "chromadb"),
        "neo4j_uri": os.getenv("NEO4J_URI", "neo4j://127.0.0.1:7687"),
        "last_error": search_agent_error,
    }


def search_agent_node_wrapper(state: dict) -> dict:
    if search_agent_instance is None:
        initialize_search_agent()
    return search_agent_instance.run(state)


class AgentState(TypedDict):
    session_id: str
    original_query: str
    raw_query: str
    dialogue_history: List[Dict[str, str]]
    dialogue_complete: bool
    dialogue_summary: str
    assistant_reply: str
    intent_analysis: Dict[str, Any]
    retrieved_knowledge: Dict[str, Any]
    final_answer: str


def route_entry(state: dict) -> str:
    """续接会话时跳过意图识别，直接进入问诊。"""
    if (
        state.get("intent_analysis")
        and state.get("dialogue_history") is not None
        and not state.get("dialogue_complete")
    ):
        return "dialogue_agent"
    return "intent_agent"


def route_after_intent(state: dict) -> str:
    intent = state.get("intent_analysis", {}).get("intent", "")
    if intent in MEDICAL_INTENTS:
        return "dialogue_agent"
    return "answer_agent"


def route_after_dialogue(state: dict) -> str:
    if state.get("dialogue_complete"):
        return "refresh_intent"
    return END


def route_after_refresh(state: dict) -> str:
    intent = state.get("intent_analysis", {})
    if intent.get("need_graph") or intent.get("need_vector"):
        return "search_agent"
    return "answer_agent"


workflow = StateGraph(AgentState)

workflow.add_node("intent_agent", run_intent_detection_agent)
workflow.add_node("dialogue_agent", run_dialogue_agent)
workflow.add_node("refresh_intent", run_search_intent_refresh)
workflow.add_node("search_agent", search_agent_node_wrapper)
workflow.add_node("answer_agent", run_answer_synthesizer_agent)

workflow.add_conditional_edges(
    START,
    route_entry,
    {
        "intent_agent": "intent_agent",
        "dialogue_agent": "dialogue_agent",
    },
)
workflow.add_conditional_edges(
    "intent_agent",
    route_after_intent,
    {
        "dialogue_agent": "dialogue_agent",
        "answer_agent": "answer_agent",
    },
)
workflow.add_conditional_edges(
    "dialogue_agent",
    route_after_dialogue,
    {
        "refresh_intent": "refresh_intent",
        END: END,
    },
)
workflow.add_conditional_edges(
    "refresh_intent",
    route_after_refresh,
    {
        "search_agent": "search_agent",
        "answer_agent": "answer_agent",
    },
)
workflow.add_edge("search_agent", "answer_agent")
workflow.add_edge("answer_agent", END)

app = workflow.compile()


def run_session_turn(state: dict, user_message: str) -> dict:
    """处理一轮用户输入，返回更新后的 state。"""
    if not state.get("original_query"):
        state["original_query"] = user_message
    state["raw_query"] = user_message
    state.setdefault("dialogue_history", [])
    state.setdefault("dialogue_complete", False)
    state.setdefault("intent_analysis", {})
    state.setdefault("retrieved_knowledge", {})
    state.setdefault("final_answer", "")
    return app.invoke(state)


if __name__ == "__main__":
    from logging_config import configure_logging

    configure_logging()
    state: dict = {
        "session_id": "session_2026",
        "original_query": "",
        "raw_query": "",
        "dialogue_history": [],
        "dialogue_complete": False,
        "dialogue_summary": "",
        "assistant_reply": "",
        "intent_analysis": {},
        "retrieved_knowledge": {},
        "final_answer": "",
    }

    user_turns = [
        "我肚子疼",
        "小腹位置，疼了大概3小时",
        "没有发烧",
    ]

    initialize_search_agent()
    try:
        for i, user_msg in enumerate(user_turns, 1):
            logger.info("%s\n[第 %s 轮] 用户: %s", "=" * 50, i, user_msg)
            state = run_session_turn(state, user_msg)

            if state.get("dialogue_complete"):
                logger.info("最终回答:\n%s", state["final_answer"])
                break

            logger.info(
                "助手追问: %s",
                state.get("final_answer", state.get("assistant_reply", "")),
            )
        else:
            logger.warning("已达最大轮次，问诊尚未完成")
    finally:
        close_search_agent()
