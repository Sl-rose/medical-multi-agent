"""1 号智能体：识别用户意图，并准备后续检索参数。

区分健康咨询、报告解读、用药指导、挂号导诊和闲聊。
医疗类意图会抽出适合 Neo4j 的实体词，以及适合向量检索的长句。
"""
import json
import logging
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))
from model.deepseek import My_model_client

logger = logging.getLogger(__name__)
llm = My_model_client()

MEDICAL_INTENTS = {"健康咨询", "报告解读", "用药指导"}


def _parse_intent_json(raw_result: str, fallback_query: str) -> dict:
    clean_json_str = raw_result.strip().replace("```json", "").replace("```", "").strip()
    parsed_result = json.loads(clean_json_str)
    current_intent = parsed_result.get("intent", "未知意图")
    need_search = current_intent in MEDICAL_INTENTS
    return {
        "intent": current_intent,
        "need_graph": need_search and bool(parsed_result.get("neo4j_entity")),
        "need_vector": need_search and bool(parsed_result.get("chroma_query")),
        "neo4j_entity": parsed_result.get("neo4j_entity", ""),
        "chroma_query": parsed_result.get("chroma_query", ""),
    }


def _build_intent_system_prompt() -> str:
    intents = ["挂号导诊", "健康咨询", "报告解读", "用药指导", "闲聊", "未知意图"]
    intent_text = "\n".join([f"- {item}" for item in intents])
    return f"""你是一个顶级的医疗意图解析专家。你需要分析用户的提问，并严格按指定的 JSON 格式输出。

【意图候选项】
{intent_text}

【要求】
必须从上述候选项中挑选一个填入 "intent" 字段。同时，你需要为后置的知识库提取检索词：
1. neo4j_entity: 适合图数据库匹配的核心医学实体（如：具体的疾病名、检查项目名、药物名）。
2. chroma_query: 适合向量数据库语义检索的扩展长句。

【请严格按以下 JSON 格式输出，不要包含 Markdown 标记（如 ```json）或任何多余文字】：
{{
    "intent": "选出的意图名称",
    "neo4j_entity": "标准医学实体词",
    "chroma_query": "适合向量库匹配的语义句"
}}"""


def run_intent_detection_agent(state: dict) -> dict:
    """
    1号 Agent 入口函数：识别医疗意图，并分解出适合 Neo4j 和 ChromaDB 的检索参数，写入 state
    """
    logger.info("[1号 Agent] 语义识别与意图路由启动")
    
    query = state.get("raw_query", "")
    if not state.get("original_query"):
        state["original_query"] = query

    raw_result = llm.ask(query=query, system_prompt=_build_intent_system_prompt())

    try:
        state["intent_analysis"] = _parse_intent_json(raw_result, query)
    except Exception as e:
        logger.warning("1号 Agent 解析大模型 JSON 失败，触发安全兜底配置: %s", e)
        state["intent_analysis"] = {
            "intent": "未知意图",
            "need_graph": True,
            "need_vector": True,
            "neo4j_entity": query,
            "chroma_query": query,
        }
        
    logger.info(
        "[1号 Agent] 识别完成。意图: [%s] | 图匹配实体: '%s'",
        state["intent_analysis"]["intent"],
        state["intent_analysis"]["neo4j_entity"],
    )
    return state


def run_search_intent_refresh(state: dict) -> dict:
    """问诊完成后，基于完整病情重新提取检索参数。"""
    logger.info("[1号 Agent] 基于问诊汇总刷新检索参数")
    original = state.get("original_query", "")
    summary = state.get("dialogue_summary", "")
    query = f"用户主诉：{original}\n问诊汇总：{summary}"
    current_intent = state.get("intent_analysis", {}).get("intent", "健康咨询")

    raw_result = llm.ask(query=query, system_prompt=_build_intent_system_prompt())

    try:
        refreshed = _parse_intent_json(raw_result, query)
        refreshed["intent"] = current_intent
        if current_intent not in MEDICAL_INTENTS:
            refreshed["need_graph"] = False
            refreshed["need_vector"] = False
        state["intent_analysis"] = refreshed
    except Exception as e:
        logger.warning("检索参数刷新失败，使用问诊汇总作为检索词: %s", e)
        state["intent_analysis"] = {
            **state.get("intent_analysis", {}),
            "need_graph": True,
            "need_vector": True,
            "neo4j_entity": summary or original,
            "chroma_query": query,
        }

    logger.info(
        "[1号 Agent] 刷新完成。图匹配实体: '%s' | 向量检索句: '%s...'",
        state["intent_analysis"]["neo4j_entity"],
        state["intent_analysis"]["chroma_query"][:40],
    )
    return state

# 当脚本被直接运行时（用于本地独立测试 1号 Agent）

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger.info("开始独立测试 1号意图识别 Agent")
    
    # 模拟最顶层流转进来的初始空 State
    mock_state = {
        "session_id": "session-step-1",
        "raw_query": "我肚子疼，怀疑是急性肠胃炎，需要吃点什么药？",
        "dialogue_history": []
    }
    
    # 运行 1号 Agent
    updated_state = run_intent_detection_agent(mock_state)
    
    logger.info("[测试输出] 1号 Agent 处理后的完整全局 State 字典:\n%s", json.dumps(updated_state, ensure_ascii=False, indent=2))
